"""Reference baseline implementations for Dawid-Skene inference."""

import numpy as np
from typing import Dict, List


def run_baseline(name: str, events: List[Dict]) -> Dict:
    """
    Run a baseline inference method.

    Args:
        name: Baseline name ("majority", "weighted_majority", or "batch_ds")
        events: List of dicts with structure:
            {"event_id": int, "claims": [{"outlet_id": int, "observation": 0|1, "certainty": float}]}

    Returns:
        Dict with:
            - "posteriors": {event_id: float P(state=1)}
            - "outlet_params": {outlet_id: {"sens": float, "spec": float}}

    Raises:
        ValueError: If name is not recognized.
    """
    if name == "majority":
        return _majority_vote(events)
    elif name == "weighted_majority":
        return _weighted_majority_vote(events)
    elif name == "batch_ds":
        return _batch_ds(events)
    else:
        raise ValueError(f"Unknown baseline: {name}")


def _majority_vote(events: List[Dict]) -> Dict:
    """
    Majority vote baseline.

    Per event: P(state=1) = fraction of claims with observation==1 (ties → 0.5).
    Outlet params: sensitivity and specificity computed from agreement with majority label.
    """
    posteriors = {}
    outlet_stats = {}  # {outlet_id: {tp, fp, tn, fn}}

    # E-step: compute posteriors and collect contingency counts per outlet
    for event in events:
        event_id = event["event_id"]
        claims = event["claims"]

        # Compute majority posterior
        ones_count = sum(1 for c in claims if c["observation"] == 1)
        total_count = len(claims)
        posterior = ones_count / total_count if total_count > 0 else 0.5
        posteriors[event_id] = posterior

        # Assign majority label (threshold at 0.5)
        majority_label = 1 if posterior > 0.5 else (0 if posterior < 0.5 else 0.5)

        # Track outlet contingency table against majority label
        for claim in claims:
            outlet_id = claim["outlet_id"]
            obs = claim["observation"]

            if outlet_id not in outlet_stats:
                outlet_stats[outlet_id] = {"tp": 0, "fp": 0, "tn": 0, "fn": 0}

            # True state is majority_label (proxy ground truth)
            # Observation is obs
            if majority_label == 1:
                if obs == 1:
                    outlet_stats[outlet_id]["tp"] += 1
                else:
                    outlet_stats[outlet_id]["fn"] += 1
            elif majority_label == 0:
                if obs == 1:
                    outlet_stats[outlet_id]["fp"] += 1
                else:
                    outlet_stats[outlet_id]["tn"] += 1
            # If majority_label == 0.5 (tie), skip or handle as missing

    # M-step: compute outlet params from contingency table
    outlet_params = {}
    for outlet_id, stats in outlet_stats.items():
        tp = stats["tp"]
        fn = stats["fn"]
        tn = stats["tn"]
        fp = stats["fp"]

        # sensitivity: P(outlet reports 1 | true state 1) = TP / (TP + FN)
        sens = tp / (tp + fn) if (tp + fn) > 0 else 0.5

        # specificity: P(outlet reports 0 | true state 0) = TN / (TN + FP)
        spec = tn / (tn + fp) if (tn + fp) > 0 else 0.5

        outlet_params[outlet_id] = {"sens": sens, "spec": spec}

    return {"posteriors": posteriors, "outlet_params": outlet_params}


def _weighted_majority_vote(events: List[Dict]) -> Dict:
    """
    Weighted majority vote baseline.

    Per event: P(state=1) = sum(certainty for claims with observation==1) / sum(certainties).
    Outlet params: sensitivity and specificity weighted by certainty.
    """
    posteriors = {}
    outlet_stats = {}  # {outlet_id: {tp, fp, tn, fn}} with weighted counts

    # E-step: compute weighted posteriors
    for event in events:
        event_id = event["event_id"]
        claims = event["claims"]

        # Compute weighted majority posterior
        weighted_ones = sum(c["certainty"] for c in claims if c["observation"] == 1)
        total_weight = sum(c["certainty"] for c in claims)
        posterior = weighted_ones / total_weight if total_weight > 0 else 0.5
        posteriors[event_id] = posterior

        # Assign majority label
        majority_label = 1 if posterior > 0.5 else (0 if posterior < 0.5 else 0.5)

        # Track outlet weighted contingency table against majority label
        for claim in claims:
            outlet_id = claim["outlet_id"]
            obs = claim["observation"]
            cert = claim.get("certainty", 0.5)

            if outlet_id not in outlet_stats:
                outlet_stats[outlet_id] = {"tp": 0.0, "fp": 0.0, "tn": 0.0, "fn": 0.0}

            # True state is majority_label (proxy ground truth)
            # Observation is obs
            # Weighted by certainty
            if majority_label == 1:
                if obs == 1:
                    outlet_stats[outlet_id]["tp"] += cert
                else:
                    outlet_stats[outlet_id]["fn"] += cert
            elif majority_label == 0:
                if obs == 1:
                    outlet_stats[outlet_id]["fp"] += cert
                else:
                    outlet_stats[outlet_id]["tn"] += cert

    # M-step: compute outlet params from weighted contingency table
    outlet_params = {}
    for outlet_id, stats in outlet_stats.items():
        tp = stats["tp"]
        fn = stats["fn"]
        tn = stats["tn"]
        fp = stats["fp"]

        # sensitivity: P(outlet reports 1 | true state 1) = TP / (TP + FN)
        sens = tp / (tp + fn) if (tp + fn) > 0 else 0.5

        # specificity: P(outlet reports 0 | true state 0) = TN / (TN + FP)
        spec = tn / (tn + fp) if (tn + fp) > 0 else 0.5

        outlet_params[outlet_id] = {"sens": sens, "spec": spec}

    return {"posteriors": posteriors, "outlet_params": outlet_params}


def _batch_ds(events: List[Dict], n_iter: int = 20) -> Dict:
    """
    Batch Dawid-Skene EM (binary case).

    20 iterations of EM:
    - Init posteriors from majority vote.
    - M-step: sens_j = (Σ w_i1 * [D_ij=1] + 0.01) / (Σ w_i1 + 0.02)
                spec_j = (Σ w_i0 * [D_ij=0] + 0.01) / (Σ w_i0 + 0.02)
                π = mean of posteriors
    - E-step: standard product likelihood with updated prior.
    - Clip params to [0.01, 0.99].
    """
    if not events:
        return {"posteriors": {}, "outlet_params": {}}

    # Initialize from majority vote
    result = _majority_vote(events)
    posteriors = result["posteriors"].copy()

    # Collect all outlets
    all_outlets = set()
    for event in events:
        for claim in event["claims"]:
            all_outlets.add(claim["outlet_id"])

    # Collect observation matrix: obs[event_id][outlet_id] = obs (or None if missing)
    obs_matrix = {}
    for event in events:
        event_id = event["event_id"]
        obs_matrix[event_id] = {}
        for claim in event["claims"]:
            outlet_id = claim["outlet_id"]
            obs_matrix[event_id][outlet_id] = claim["observation"]

    # Initialize outlet params (from majority vote or defaults)
    outlet_params = {oid: {"sens": 0.5, "spec": 0.5} for oid in all_outlets}
    for oid, params in result["outlet_params"].items():
        outlet_params[oid] = params.copy()

    # EM iterations
    for iteration in range(n_iter):
        # M-step: update outlet params based on current posteriors
        for outlet_id in all_outlets:
            # Compute sufficient statistics for this outlet
            exp_tp = 0.0  # Σ w_i1 * [D_ij=1]
            exp_fn = 0.0  # Σ w_i1 * [D_ij=0]
            exp_tn = 0.0  # Σ w_i0 * [D_ij=0]
            exp_fp = 0.0  # Σ w_i0 * [D_ij=1]

            for event_id, obs_for_event in obs_matrix.items():
                if outlet_id not in obs_for_event:
                    continue

                posterior = posteriors[event_id]
                obs = obs_for_event[outlet_id]

                # w_i1 = posterior, w_i0 = 1 - posterior
                w_i1 = posterior
                w_i0 = 1.0 - posterior

                if obs == 1:
                    exp_tp += w_i1
                    exp_fp += w_i0
                else:
                    exp_fn += w_i1
                    exp_tn += w_i0

            # Update sensitivity and specificity with smoothing
            sens_num = exp_tp + 0.01
            sens_denom = exp_tp + exp_fn + 0.02
            sens = sens_num / sens_denom if sens_denom > 0 else 0.5

            spec_num = exp_tn + 0.01
            spec_denom = exp_tn + exp_fp + 0.02
            spec = spec_num / spec_denom if spec_denom > 0 else 0.5

            # Clip to [0.01, 0.99]
            sens = np.clip(sens, 0.01, 0.99)
            spec = np.clip(spec, 0.01, 0.99)

            outlet_params[outlet_id] = {"sens": float(sens), "spec": float(spec)}

        # E-step: update posteriors based on current outlet params
        pi = np.mean(list(posteriors.values()))  # Update prior

        for event in events:
            event_id = event["event_id"]
            claims = event["claims"]

            # Compute likelihood per state
            ll_s0 = 1.0 - pi
            ll_s1 = pi

            for claim in claims:
                outlet_id = claim["outlet_id"]
                obs = claim["observation"]

                sens = outlet_params[outlet_id]["sens"]
                spec = outlet_params[outlet_id]["spec"]

                if obs == 1:
                    # P(obs=1 | state=0) = 1 - spec (false positive)
                    # P(obs=1 | state=1) = sens (true positive)
                    ll_s0 *= (1.0 - spec)
                    ll_s1 *= sens
                else:
                    # P(obs=0 | state=0) = spec (true negative)
                    # P(obs=0 | state=1) = 1 - sens (false negative)
                    ll_s0 *= spec
                    ll_s1 *= (1.0 - sens)

            # Update posterior
            if ll_s0 + ll_s1 > 0:
                posterior = ll_s1 / (ll_s0 + ll_s1)
            else:
                posterior = pi

            posteriors[event_id] = posterior

    return {"posteriors": posteriors, "outlet_params": outlet_params}
