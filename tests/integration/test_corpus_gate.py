"""Integration test: corpus validation gate."""

import pytest
from stapled.db import connect
from stapled.gates import GateError, assert_corpus_passed
from stapled.infer.em import run_em
from stapled.infer.model import RunConfig


def test_infer_rejects_unvalidated_corpus(tmp_path):
    """Test that infer --synthetic rejects corpus with validation_status != PASSED."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create corpus with pending status
    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'pending')")
    corpus_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO event (corpus_id, label, true_state) VALUES (?, ?, ?)",
        (corpus_id, "Event 1", 1),
    )
    event_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO article (outlet_id, corpus_id, url, ingest_status) "
        "VALUES (?, ?, ?, 'ok')",
        (outlet_id, corpus_id, "http://ex.com/1"),
    )
    article_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
        "VALUES (?, ?, 'occurred', 0.9, 0.0, 1.0)",
        (article_id, event_id),
    )
    conn.commit()

    # Try to infer without validation
    with pytest.raises(GateError):
        assert_corpus_passed(conn, corpus_id)


def test_infer_rejects_rejected_corpus(tmp_path):
    """Test that infer --synthetic rejects corpus with validation_status = REJECTED."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create corpus with REJECTED status
    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'REJECTED')")
    corpus_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO event (corpus_id, label, true_state) VALUES (?, ?, ?)",
        (corpus_id, "Event 1", 1),
    )
    event_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO article (outlet_id, corpus_id, url, ingest_status) "
        "VALUES (?, ?, ?, 'ok')",
        (outlet_id, corpus_id, "http://ex.com/1"),
    )
    article_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
        "VALUES (?, ?, 'occurred', 0.9, 0.0, 1.0)",
        (article_id, event_id),
    )
    conn.commit()

    # Try to infer without validation
    with pytest.raises(GateError):
        assert_corpus_passed(conn, corpus_id)


def test_infer_accepts_passed_corpus(tmp_path):
    """Test that infer --synthetic accepts corpus with validation_status = PASSED."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create corpus with PASSED status
    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'PASSED')")
    corpus_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO event (corpus_id, label, true_state) VALUES (?, ?, ?)",
        (corpus_id, "Event 1", 1),
    )
    event_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO article (outlet_id, corpus_id, url, ingest_status) "
        "VALUES (?, ?, ?, 'ok')",
        (outlet_id, corpus_id, "http://ex.com/1"),
    )
    article_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
        "VALUES (?, ?, 'occurred', 0.9, 0.0, 1.0)",
        (article_id, event_id),
    )
    conn.commit()

    # Gate should pass
    assert_corpus_passed(conn, corpus_id)

    # And inference should work
    config = RunConfig(max_iter=10, restarts=1)
    run_id = run_em(conn, corpus_id, config)
    assert run_id is not None
