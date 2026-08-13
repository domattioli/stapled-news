"""Dawid-Skene binary EM inference with degeneracy checks."""

import sqlite3
import numpy as np
import json
from datetime import datetime
from hashlib import sha256

from stapled.infer.model import RunConfig


def run_em(
    conn: sqlite3.Connection, corpus_id: int, config: RunConfig, is_real: bool = False
) -> int:
    """
    Run EM inference on corpus (synthetic) or real claims (corpus_id=None).
    Returns run_id.
    """
    # Load claims grouped by event
    claims_by_event = _load_claims_by_event(conn, corpus_id, is_real=is_real)

    if not claims_by_event:
        corpus_name = "corpus" if corpus_id else "real claims"
        raise ValueError(f"No claims found for {corpus_name}")

    # For real data, filter to events with >= 2 distinct outlets (single-outlet events lack corroboration signal)
    if is_real:
        claims_by_event_filtered = {}
        for event_id, claims_list in claims_by_event.items():
            outlets = set(c['outlet_id'] for c in claims_list)
            if len(outlets) >= 2:
                claims_by_event_filtered[event_id] = claims_list
        claims_by_event = claims_by_event_filtered

        if not claims_by_event:
            raise ValueError("No events with >= 2 distinct outlets in real claims")

    # Get unique outlets
    outlets = set()
    for event_id, claims_list in claims_by_event.items():
        for claim in claims_list:
            outlets.add(claim["outlet_id"])

    outlets = sorted(outlets)
    outlet_idx = {o: i for i, o in enumerate(outlets)}

    # Try multiple restarts
    best_run = None
    best_ll = -np.inf

    for restart_idx in range(config.restarts):
        run = _run_em_single(
            claims_by_event,
            outlets,
            outlet_idx,
            config,
            seed=42 + restart_idx,
        )
        if run and run["log_likelihood"] > best_ll:
            best_ll = run["log_likelihood"]
            best_run = run

    if not best_run:
        raise ValueError("EM failed to produce any valid run")

    # Persist run
    run_id = _persist_run(
        conn,
        corpus_id,
        best_run,
        claims_by_event,
        outlets,
        config,
    )

    return run_id


def _load_claims_by_event(
    conn: sqlite3.Connection, corpus_id: int, is_real: bool = False
) -> dict:
    """
    Load claims grouped by event, with outlet and certainty info.
    If is_real=True, corpus_id is ignored and all unaligned real claims are loaded.
    """
    if is_real:
        query = """
            SELECT c.event_id, a.outlet_id,
                   CASE WHEN NOT c.action LIKE 'not-%' THEN 1 ELSE 0 END as observation,
                   c.certainty, c.magnitude_value
            FROM claim c
            JOIN article a ON c.article_id = a.id
            WHERE a.corpus_id IS NULL
            AND c.event_id IS NOT NULL
            ORDER BY c.event_id
        """
        cursor = conn.execute(query)
    else:
        cursor = conn.execute(
            """
            SELECT c.event_id, a.outlet_id,
                   CASE WHEN c.action = 'occurred' THEN 1 ELSE 0 END as observation,
                   c.certainty, c.magnitude_value
            FROM claim c
            JOIN article a ON c.article_id = a.id
            WHERE a.corpus_id = ?
            ORDER BY c.event_id
        """,
            (corpus_id,),
        )

    claims_by_event = {}
    for event_id, outlet_id, obs, certainty, magnitude in cursor.fetchall():
        if event_id not in claims_by_event:
            claims_by_event[event_id] = []
        claims_by_event[event_id].append(
            {
                "outlet_id": outlet_id,
                "observation": obs,
                "certainty": certainty if certainty else 0.5,
                "magnitude": magnitude,
            }
        )

    return claims_by_event


def _run_em_single(
    claims_by_event: dict,
    outlets: list,
    outlet_idx: dict,
    config: RunConfig,
    seed: int,
) -> dict:
    """Run EM from one restart. Returns {status, iterations, log_likelihood, params, posteriors}."""
    rng = np.random.default_rng(seed)
    n_outlets = len(outlets)

    # Initialize sensitivity/specificity per outlet using majority-vote agreement per outlet
    sens = np.zeros(n_outlets)
    spec = np.zeros(n_outlets)

    for o_idx, outlet_id in enumerate(outlets):
        agreement_count = 0
        total_count = 0
        for event_id, claims_list in claims_by_event.items():
            # Get majority vote
            obs_sum = sum(c["observation"] for c in claims_list)
            majority = 1 if obs_sum > len(claims_list) / 2 else 0

            # Check this outlet's agreement with majority
            for claim in claims_list:
                if claim["outlet_id"] == outlet_id:
                    if claim["observation"] == majority:
                        agreement_count += 1
                    total_count += 1

        agreement = agreement_count / total_count if total_count > 0 else 0.5
        # Initialize sens/spec from agreement; clip to avoid extremes (but allow good outlets to be good)
        agreement = np.clip(agreement, 0.2, 0.95)
        if seed != 42:
            # Perturb non-baseline restarts so their first E-step (which is
            # what actually determines the trajectory - see posteriors init
            # below) starts from a different point instead of silently
            # reproducing restart 0 every time.
            agreement = np.clip(agreement + rng.normal(0, 0.05), 0.01, 0.99)
        sens[o_idx] = agreement
        spec[o_idx] = agreement

    # posteriors is populated by the first E-step below (it unconditionally
    # assigns every event_id before any consumer reads the dict); restart
    # diversity comes from the sens/spec perturbation above, not from a
    # posteriors init.
    posteriors = {}

    pi = 0.5  # prior on state=1

    log_likelihoods = []
    previous_ll = -np.inf
    converged = False

    for iteration in range(config.max_iter):
        # E-step: compute posterior P(state|observations)
        for event_id, claims_list in claims_by_event.items():
            # Likelihood per state
            ll_s0 = (1 - pi) * np.prod(
                [
                    _likelihood_obs(
                        claim["observation"],
                        0,
                        sens[outlet_idx[claim["outlet_id"]]],
                        spec[outlet_idx[claim["outlet_id"]]],
                        claim["certainty"],
                    )
                    for claim in claims_list
                ]
            )
            ll_s1 = pi * np.prod(
                [
                    _likelihood_obs(
                        claim["observation"],
                        1,
                        sens[outlet_idx[claim["outlet_id"]]],
                        spec[outlet_idx[claim["outlet_id"]]],
                        claim["certainty"],
                    )
                    for claim in claims_list
                ]
            )

            # Normalize
            total = ll_s0 + ll_s1
            if total > 0:
                posteriors[event_id] = np.array([ll_s0 / total, ll_s1 / total])
            else:
                posteriors[event_id] = np.array([0.5, 0.5])

        # M-step: update sensitivity/specificity per outlet
        for o_idx, outlet_id in enumerate(outlets):
            numerator_sens = 0
            denominator_sens = 0
            numerator_spec = 0
            denominator_spec = 0

            for event_id, claims_list in claims_by_event.items():
                p_s1 = posteriors[event_id][1]
                p_s0 = posteriors[event_id][0]

                for claim in claims_list:
                    if claim["outlet_id"] != outlet_id:
                        continue

                    obs = claim["observation"]
                    cert = claim["certainty"]

                    # Weighted by posterior and certainty
                    if obs == 1:
                        numerator_sens += p_s1 * cert
                        denominator_sens += p_s1 * cert
                    else:
                        denominator_sens += p_s1 * cert

                    if obs == 0:
                        numerator_spec += p_s0 * cert
                        denominator_spec += p_s0 * cert
                    else:
                        denominator_spec += p_s0 * cert

            sens[o_idx] = (
                numerator_sens / denominator_sens
                if denominator_sens > 0
                else 0.5
            )
            spec[o_idx] = (
                numerator_spec / denominator_spec
                if denominator_spec > 0
                else 0.5
            )
            sens[o_idx] = np.clip(sens[o_idx], 0.01, 0.99)
            spec[o_idx] = np.clip(spec[o_idx], 0.01, 0.99)

        # Update prior
        pi = np.mean([posteriors[e][1] for e in claims_by_event])

        # Compute log-likelihood
        current_ll = 0
        for event_id, claims_list in claims_by_event.items():
            p_s0 = posteriors[event_id][0]
            p_s1 = posteriors[event_id][1]

            for claim in claims_list:
                obs = claim["observation"]
                o_idx = outlet_idx[claim["outlet_id"]]
                cert = claim["certainty"]

                ll_s0 = _likelihood_obs(obs, 0, sens[o_idx], spec[o_idx], cert)
                ll_s1 = _likelihood_obs(obs, 1, sens[o_idx], spec[o_idx], cert)

                current_ll += np.log(p_s0 * ll_s0 + p_s1 * ll_s1 + 1e-10)

        log_likelihoods.append(current_ll)

        # Check convergence (skip check for first 5 iterations to allow EM to stabilize)
        if iteration >= 5:
            delta_ll = current_ll - previous_ll

            if 0 <= delta_ll < config.tol:
                # Converged
                converged = True
                break

        previous_ll = current_ll

    # Check for degeneracy: concentration of reliability mass
    reliabilities = (sens + spec) / 2
    rel_contribution = reliabilities / (reliabilities.sum() + 1e-10)
    max_contribution = rel_contribution.max()

    if max_contribution > config.concentration_threshold:
        status = "degenerate"
    elif not converged:
        status = "nonconverged"
    else:
        status = "converged"

    # Label-switching fix: if mean reliability < 0.5, flip
    if np.mean(reliabilities) < 0.5:
        sens_copy = sens.copy()
        sens = 1 - spec
        spec = 1 - sens_copy
        for event_id in posteriors:
            posteriors[event_id] = posteriors[event_id][::-1]

    return {
        "status": status,
        "iterations": iteration + 1,
        "log_likelihood": current_ll,
        "sens": sens,
        "spec": spec,
        "posteriors": posteriors,
        "pi": pi,
        "ll_trace": log_likelihoods,
    }


def _likelihood_obs(obs: int, true_state: int, sens: float, spec: float, cert: float) -> float:
    """Compute P(obs | true_state) weighted by certainty."""
    if true_state == 1:
        p_correct = sens
    else:
        p_correct = spec

    # Certainty as temperature
    p_correct = p_correct * cert + (1 - cert) * 0.5
    # Clip to avoid underflow in likelihood products
    p_correct = np.clip(p_correct, 1e-9, 1 - 1e-9)
    return p_correct if obs == true_state else 1 - p_correct


def _persist_run(
    conn: sqlite3.Connection,
    corpus_id: int,
    run: dict,
    claims_by_event: dict,
    outlets: list,
    config: RunConfig,
) -> int:
    """Persist run and results to DB. Returns run_id."""
    # Compute claim set hash
    claim_ids = []
    for event_id in sorted(claims_by_event.keys()):
        for claim in claims_by_event[event_id]:
            claim_ids.append((event_id, claim["outlet_id"], claim["observation"]))

    claim_set_hash = sha256(
        str(claim_ids).encode()
    ).hexdigest()

    # Insert inference_run
    config_json = json.dumps({
        "max_iter": config.max_iter,
        "tol": config.tol,
        "restarts": config.restarts,
        "concentration_threshold": config.concentration_threshold,
        "ll_trace": [float(x) for x in run.get("ll_trace", [])],
    })

    cursor = conn.execute(
        """
        INSERT INTO inference_run
        (created_at, corpus_id, claim_set_hash, status, iterations, log_likelihood, config_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """,
        (
            datetime.utcnow().isoformat(),
            corpus_id,
            claim_set_hash,
            run["status"],
            run["iterations"],
            run["log_likelihood"],
            config_json,
        ),
    )
    run_id = cursor.lastrowid

    # Insert run_event_result
    for event_id, claims_list in claims_by_event.items():
        inferred_state = int(np.argmax(run["posteriors"][event_id]))
        confidence = run["posteriors"][event_id][inferred_state]

        # Infer magnitude as modal claim value consistent with inferred state
        consistent_magnitudes = []
        for claim in claims_list:
            if claim["observation"] == inferred_state:
                if claim["magnitude"] is not None:
                    consistent_magnitudes.append(claim["magnitude"])

        inferred_magnitude = (
            int(np.median(consistent_magnitudes))
            if consistent_magnitudes
            else None
        )

        # Corroboration label
        from stapled.gates import corroboration_label

        corroboration = corroboration_label(conn, event_id)

        # Compute per-outlet weights
        weighting = []
        for o_idx, outlet_id in enumerate(outlets):
            outlet_claims = [c for c in claims_list if c["outlet_id"] == outlet_id]
            if outlet_claims:
                weight = run["posteriors"][event_id][inferred_state]  # Simplified
                reason = f"Outlet reliability: {(run['sens'][o_idx] + run['spec'][o_idx]) / 2:.2f}"
                weighting.append(
                    {
                        "outlet_id": outlet_id,
                        "weight": float(weight),
                        "reason": reason,
                    }
                )

        weighting_json = json.dumps(weighting)

        conn.execute(
            """
            INSERT INTO run_event_result
            (run_id, event_id, inferred_state, inferred_magnitude_bucket, confidence, corroboration, weighting_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
            (
                run_id,
                event_id,
                inferred_state,
                inferred_magnitude,
                confidence,
                corroboration,
                weighting_json,
            ),
        )

    # Insert run_outlet_result
    for o_idx, outlet_id in enumerate(outlets):
        est_reliability = (run["sens"][o_idx] + run["spec"][o_idx]) / 2
        est_bias = run["sens"][o_idx] - run["spec"][o_idx]
        est_calibration = 1.0  # Simplified

        conn.execute(
            """
            INSERT INTO run_outlet_result
            (run_id, outlet_id, est_reliability, est_bias, est_calibration)
            VALUES (?, ?, ?, ?, ?)
        """,
            (run_id, outlet_id, est_reliability, est_bias, est_calibration),
        )

    conn.commit()
    return run_id
