"""Recovery scoring: compare inferred states vs ground truth."""

import sqlite3
import numpy as np
from scipy import stats


def score(conn: sqlite3.Connection, run_id: int) -> dict:
    """Score a synthetic run against ground truth. Returns {verdict, accuracy, rank_corr, ...}."""
    # Load run
    cursor = conn.execute(
        "SELECT corpus_id, status FROM inference_run WHERE id = ?", (run_id,)
    )
    row = cursor.fetchone()
    if not row:
        raise ValueError(f"Run {run_id} not found")

    corpus_id, run_status = row

    if not corpus_id:
        raise ValueError(f"Run {run_id} is not synthetic (corpus_id is NULL)")

    # Check corpus is PASSED
    from stapled.gates import assert_corpus_passed

    assert_corpus_passed(conn, corpus_id)

    # Load ground truth and inferred states
    cursor = conn.execute(
        """
        SELECT e.id, e.true_state, rer.inferred_state
        FROM event e
        JOIN run_event_result rer ON e.id = rer.event_id
        WHERE e.corpus_id = ? AND rer.run_id = ?
    """,
        (corpus_id, run_id),
    )

    true_inferred_pairs = cursor.fetchall()
    if not true_inferred_pairs:
        raise ValueError(f"No event results found for run {run_id}")

    true_states = np.array([t[1] for t in true_inferred_pairs])
    inferred_states = np.array([t[2] for t in true_inferred_pairs])

    # Accuracy
    state_accuracy = np.mean(true_states == inferred_states)

    # Load seeded reliabilities
    cursor = conn.execute(
        """
        SELECT outlet_id, reliability FROM outlet_truth WHERE corpus_id = ?
    """,
        (corpus_id,),
    )
    seeded_reliability = {row[0]: row[1] for row in cursor.fetchall()}

    # Load estimated reliabilities
    cursor = conn.execute(
        """
        SELECT outlet_id, est_reliability FROM run_outlet_result WHERE run_id = ?
    """,
        (run_id,),
    )
    est_reliability = {row[0]: row[1] for row in cursor.fetchall()}

    # Rank correlation
    common_outlets = sorted(set(seeded_reliability.keys()) & set(est_reliability.keys()))
    if len(common_outlets) >= 2:
        seeded_ranks = [seeded_reliability[o] for o in common_outlets]
        est_ranks = [est_reliability[o] for o in common_outlets]
        rank_corr, _ = stats.spearmanr(seeded_ranks, est_ranks)
    else:
        rank_corr = 0.0

    # Verdict
    verdict = "PASS" if state_accuracy >= 0.85 and rank_corr >= 0.8 else "FAIL"

    # Persist recovery_report
    cursor = conn.execute(
        """
        INSERT INTO recovery_report
        (run_id, corpus_id, state_accuracy, reliability_rank_corr, verdict)
        VALUES (?, ?, ?, ?, ?)
    """,
        (run_id, corpus_id, state_accuracy, rank_corr, verdict),
    )
    conn.commit()

    return {
        "state_accuracy": state_accuracy,
        "reliability_rank_corr": rank_corr,
        "verdict": verdict,
        "run_status": run_status,
    }
