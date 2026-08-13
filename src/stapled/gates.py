"""Stage-gate enforcement for the inference pipeline."""

import sqlite3


class GateError(Exception):
    """Raised when a stage gate is not passed."""

    pass


def assert_corpus_passed(conn: sqlite3.Connection, corpus_id: int) -> None:
    """Raise GateError unless corpus validation_status='PASSED'."""
    cursor = conn.execute(
        "SELECT validation_status FROM corpus WHERE id = ?", (corpus_id,)
    )
    row = cursor.fetchone()
    if not row:
        raise GateError(f"Corpus {corpus_id} not found")
    status = row[0]
    if status != "PASSED":
        raise GateError(
            f"Corpus {corpus_id} validation status is '{status}', not 'PASSED'. "
            "Run 'stapled synth validate --corpus {corpus_id}' first."
        )


def assert_recovery_passed(conn: sqlite3.Connection) -> None:
    """Raise GateError unless there exists a recovery_report with verdict='PASS'."""
    cursor = conn.execute(
        "SELECT id FROM recovery_report WHERE verdict = 'PASS' LIMIT 1"
    )
    row = cursor.fetchone()
    if not row:
        raise GateError(
            "No passing recovery report found. "
            "Run synthetic corpus inference and scoring first."
        )


def corroboration_label(conn: sqlite3.Connection, event_id: int) -> str:
    """Return 'triangulated' if claims supporting event come from >=2 distinct outlets
    AND >=2 distinct dedup-collapsed sources, else 'uncorroborated'."""
    # Two conditions, both required: >=2 distinct outlets, AND >=2 distinct
    # dedup-collapsed sources (articles sharing a dedup_cluster_id count as
    # one source). Outlet count alone is not enough — two different outlets
    # both republishing the same verbatim wire copy share one dedup cluster
    # and must not count as independent corroboration.
    cursor = conn.execute(
        """
        SELECT COUNT(DISTINCT a.outlet_id),
               COUNT(DISTINCT CASE WHEN a.dedup_cluster_id IS NOT NULL
                                    THEN 'c' || a.dedup_cluster_id
                                    ELSE 'a' || a.id END)
        FROM claim c
        JOIN article a ON c.article_id = a.id
        WHERE c.event_id = ?
    """,
        (event_id,),
    )
    row = cursor.fetchone()
    distinct_outlets = row[0] if row else 0
    distinct_sources = row[1] if row else 0
    if distinct_outlets >= 2 and distinct_sources >= 2:
        return "triangulated"
    return "uncorroborated"
