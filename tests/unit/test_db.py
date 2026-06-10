"""Unit tests for DB schema and migrations."""

import pytest
import sqlite3
from stapled.db import connect


def test_connect_creates_db(tmp_path):
    """Test that connect() creates database and enables features."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Check WAL mode
    cursor = conn.execute("PRAGMA journal_mode")
    assert cursor.fetchone()[0] == "wal"

    # Check foreign keys enabled
    cursor = conn.execute("PRAGMA foreign_keys")
    assert cursor.fetchone()[0] == 1

    conn.close()


def test_schema_migrations_applied(tmp_path):
    """Test that all tables are created."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Check all tables exist
    cursor = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
    )
    tables = {row[0] for row in cursor.fetchall()}

    expected_tables = {
        "outlet",
        "article",
        "event",
        "claim",
        "corpus",
        "outlet_truth",
        "inference_run",
        "run_event_result",
        "run_outlet_result",
        "recovery_report",
        "schema_migrations",
    }
    assert expected_tables.issubset(tables)

    conn.close()


def test_outlet_unique_constraint(tmp_path):
    """Test that outlet name is unique."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('test-outlet', 1)")
    conn.commit()

    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('test-outlet', 1)")
        conn.commit()

    conn.close()


def test_article_unique_outlet_url(tmp_path):
    """Test that (outlet_id, url) is unique."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create outlet
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid
    conn.commit()

    # Create article
    conn.execute(
        "INSERT INTO article (outlet_id, url, published_at, title, body, ingest_status) "
        "VALUES (?, ?, '2024-01-01', 'Title', 'Body', 'ok')",
        (outlet_id, "http://example.com/article1"),
    )
    conn.commit()

    # Try duplicate
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO article (outlet_id, url, published_at, title, body, ingest_status) "
            "VALUES (?, ?, '2024-01-01', 'Title', 'Body', 'ok')",
            (outlet_id, "http://example.com/article1"),
        )
        conn.commit()

    conn.close()


def test_claim_certainty_check(tmp_path):
    """Test that certainty must be in [0,1]."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Setup: outlet, article, event
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status) VALUES (?, ?, 'ok')",
        (outlet_id, "http://ex.com/1"),
    )
    article_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO event (label) VALUES (?)", ("test event",)
    )
    event_id = cursor.lastrowid
    conn.commit()

    # Valid certainty
    conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.0, 0.9)",
        (article_id, event_id),
    )
    conn.commit()

    # Invalid certainty > 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
            "VALUES (?, ?, 1.5, 0.0, 0.9)",
            (article_id, event_id),
        )
        conn.commit()

    # Invalid certainty < 0
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
            "VALUES (?, ?, -0.1, 0.0, 0.9)",
            (article_id, event_id),
        )
        conn.commit()

    conn.close()


def test_claim_valence_check(tmp_path):
    """Test that valence must be in [-1,1]."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Setup
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status) VALUES (?, ?, 'ok')",
        (outlet_id, "http://ex.com/1"),
    )
    article_id = cursor.lastrowid
    cursor = conn.execute("INSERT INTO event (label) VALUES (?)", ("test event",))
    event_id = cursor.lastrowid
    conn.commit()

    # Valid
    conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.5, 0.9)",
        (article_id, event_id),
    )
    conn.commit()

    # Invalid > 1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
            "VALUES (?, ?, 0.5, 1.5, 0.9)",
            (article_id, event_id),
        )
        conn.commit()

    # Invalid < -1
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
            "VALUES (?, ?, 0.5, -1.5, 0.9)",
            (article_id, event_id),
        )
        conn.commit()

    conn.close()


def test_recovery_report_verdict_check(tmp_path):
    """Test that recovery_report.verdict is constrained."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Setup
    conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'PASSED')")
    corpus_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO inference_run (created_at, corpus_id, status) VALUES (?, ?, 'converged')",
        ("2024-01-01", corpus_id),
    )
    run_id = cursor.lastrowid
    conn.commit()

    # Valid verdict
    conn.execute(
        "INSERT INTO recovery_report (run_id, corpus_id, verdict) VALUES (?, ?, 'PASS')",
        (run_id, corpus_id),
    )
    conn.commit()

    # Invalid verdict
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO recovery_report (run_id, corpus_id, verdict) VALUES (?, ?, 'MAYBE')",
            (run_id, corpus_id),
        )
        conn.commit()

    conn.close()
