"""
A/B test: naive-count vs reliability-weighted pyramid scoring, on the full
real US-headlines corpus, with cross-validation and an independent anchor.

Design directly answers the 5 findings from the prior single-event PoC's
adversarial review (see .claude/handoffs/2026-09-07-stapled-pyramid-headline.md
in agents_Inc for the original review):

  1. Anchor / label-switching: outlets with an MBFC "fact: high" external
     rating (independent of this corpus's own EM fit) are held out entirely
     from reliability estimation and used only as a proxy ground-truth panel.
  2. Absence-as-denial: uses the real claim/article/event tables, where a
     missing claim row IS "not mentioned" (absent from the query result),
     never coded as an asserted "false" observation=0. No PoC-style
     `1 if fn(headline) else 0` keyword coding anywhere in this script.
  3. Circularity: outlet reliability is fit via EM on a TRAIN split of
     events only, then applied unchanged to score a disjoint TEST split.
     Anchor outlets are excluded from the fit entirely, and only their
     TEST-side assertions are read, so the validation panel never leaks
     into the weights being validated.
  4. No-ground-truth: correctness is not inferred from "the two schemes'
     scores differ" (that alone proves nothing, per finding 4). Instead,
     each scheme's TEST-side event score (built only from non-anchor
     outlets) is checked against the anchor panel's own independent
     majority assertion for that same event -- an externally sourced
     signal neither scheme's weights were fit on.
  5. SCU independence: units of analysis are the pipeline's real aligned
     events (`align-cmd`, TF-IDF + entity clustering), not hand-picked
     causally entangled sub-claims of one story treated as fake
     independent "events."

This is a proxy-ground-truth test, not a truth oracle: "the anchor panel
says X" is not metaphysically "X is true," only an independently-sourced
signal not derived from the weights under test. That caveat is preserved
in the reported results, not laundered into a stronger claim.
"""

import json
import random
import sqlite3
from pathlib import Path

import numpy as np

from stapled.infer.em import _run_em_single
from stapled.infer.model import RunConfig

DB_PATH = "stapled.db"
SEED = 42
TRAIN_FRACTION = 0.7
MIN_OUTLETS_PER_EVENT = 3  # need >=2 non-anchor + >=1 anchor after split


def load_real_claims(conn: sqlite3.Connection) -> dict[int, list[dict]]:
    """Same semantics as em._load_claims_by_event(is_real=True): a row only
    exists if that outlet actually made that claim. Absence = no row, never
    observation=0."""
    query = """
        SELECT c.event_id, a.outlet_id,
               CASE WHEN NOT c.action LIKE 'not-%' THEN 1 ELSE 0 END AS observation,
               c.certainty
        FROM claim c
        JOIN article a ON c.article_id = a.id
        WHERE a.corpus_id IS NULL AND c.event_id IS NOT NULL
        ORDER BY c.event_id
    """
    claims_by_event: dict[int, list[dict]] = {}
    for event_id, outlet_id, obs, certainty in conn.execute(query).fetchall():
        claims_by_event.setdefault(event_id, []).append(
            {"outlet_id": outlet_id, "observation": obs, "certainty": certainty or 0.5}
        )
    return claims_by_event


def get_anchor_outlets(conn: sqlite3.Connection) -> set[int]:
    """Outlets with an MBFC fact='high' external rating -- independent of
    anything this corpus's own EM has ever estimated."""
    rows = conn.execute(
        """
        SELECT o.id FROM outlet o
        JOIN outlet_external_label l ON l.domain = o.name
        WHERE l.fact = 'high'
        """
    ).fetchall()
    return {r[0] for r in rows}


def main() -> None:
    conn = sqlite3.connect(DB_PATH)
    rng = random.Random(SEED)

    claims_by_event = load_real_claims(conn)
    anchor_outlets = get_anchor_outlets(conn)
    print(f"loaded {len(claims_by_event)} real events, {len(anchor_outlets)} anchor outlets")

    # Only events with enough distinct outlets to have both a non-anchor
    # weighting signal and an anchor-side proxy label.
    eligible_events = {}
    for eid, claims in claims_by_event.items():
        outlets_here = {c["outlet_id"] for c in claims}
        if len(outlets_here) >= MIN_OUTLETS_PER_EVENT and outlets_here & anchor_outlets:
            eligible_events[eid] = claims
    print(f"{len(eligible_events)} events have >= {MIN_OUTLETS_PER_EVENT} outlets and >=1 anchor outlet")

    event_ids = sorted(eligible_events.keys())
    rng.shuffle(event_ids)
    split = int(len(event_ids) * TRAIN_FRACTION)
    train_ids, test_ids = set(event_ids[:split]), set(event_ids[split:])
    print(f"train events: {len(train_ids)}  test events: {len(test_ids)}")

    # --- Fit reliability on TRAIN events only, EXCLUDING anchor outlets
    # from the fit entirely (finding 3: no leakage from the validation panel
    # into the weights being validated).
    train_claims = {
        eid: [c for c in claims if c["outlet_id"] not in anchor_outlets]
        for eid, claims in eligible_events.items()
        if eid in train_ids
    }
    train_claims = {eid: c for eid, c in train_claims.items() if len(c) >= 2}

    train_outlets = sorted({c["outlet_id"] for claims in train_claims.values() for c in claims})
    outlet_idx = {o: i for i, o in enumerate(train_outlets)}
    config = RunConfig(max_iter=200, tol=1e-6, restarts=5, concentration_threshold=0.9)

    best, best_ll = None, -np.inf
    for r in range(config.restarts):
        run = _run_em_single(train_claims, train_outlets, outlet_idx, config, seed=SEED + r)
        if run and run["status"] != "degenerate" and run["log_likelihood"] > best_ll:
            best_ll, best = run["log_likelihood"], run
    if best is None:
        raise SystemExit("EM failed to converge on train split without degeneracy")
    print(f"train EM: status={best['status']} iters={best['iterations']} ll={best_ll:.2f}")

    reliability = {
        train_outlets[i]: float((best["sens"][i] + best["spec"][i]) / 2)
        for i in range(len(train_outlets))
    }

    # --- Score TEST events under both schemes, using only non-anchor
    # outlets' claims for the weighting itself, then compare to the
    # anchor panel's own majority assertion (held out, independent).
    rows = []
    for eid in sorted(test_ids):
        claims = eligible_events[eid]
        anchor_claims = [c for c in claims if c["outlet_id"] in anchor_outlets]
        non_anchor_claims = [c for c in claims if c["outlet_id"] not in anchor_outlets]
        if not anchor_claims or len(non_anchor_claims) < 2:
            continue

        anchor_label = 1 if np.mean([c["observation"] for c in anchor_claims]) >= 0.5 else 0

        naive_score = float(np.mean([c["observation"] for c in non_anchor_claims]))

        weights = [reliability.get(c["outlet_id"], 0.5) for c in non_anchor_claims]
        obs = [c["observation"] for c in non_anchor_claims]
        w_sum = sum(weights)
        reliability_score = float(sum(w * o for w, o in zip(weights, obs)) / w_sum) if w_sum > 0 else naive_score

        rows.append(
            {
                "event_id": eid,
                "n_non_anchor": len(non_anchor_claims),
                "n_anchor": len(anchor_claims),
                "anchor_label": anchor_label,
                "naive_score": naive_score,
                "reliability_score": reliability_score,
            }
        )

    print(f"{len(rows)} test events scored against an anchor panel")

    naive_err = [abs(r["naive_score"] - r["anchor_label"]) for r in rows]
    rel_err = [abs(r["reliability_score"] - r["anchor_label"]) for r in rows]
    naive_acc = np.mean([(r["naive_score"] >= 0.5) == bool(r["anchor_label"]) for r in rows])
    rel_acc = np.mean([(r["reliability_score"] >= 0.5) == bool(r["anchor_label"]) for r in rows])

    result = {
        "n_train_events": len(train_claims),
        "n_test_events": len(rows),
        "n_train_outlets": len(train_outlets),
        "n_anchor_outlets": len(anchor_outlets),
        "train_em_status": best["status"],
        "naive_mae_vs_anchor": float(np.mean(naive_err)),
        "reliability_mae_vs_anchor": float(np.mean(rel_err)),
        "naive_accuracy_vs_anchor": float(naive_acc),
        "reliability_accuracy_vs_anchor": float(rel_acc),
    }
    print(json.dumps(result, indent=2))

    out_path = Path("results_us/ab_test_reliability_pyramid.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({"summary": result, "per_event": rows}, indent=2))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    main()
