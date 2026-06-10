"""Tests for incremental alignment."""

import sqlite3
import pytest
import json

from stapled.infer.align_incremental import align_incremental


_test_counter = 0

@pytest.fixture
def test_db():
    """Create in-memory test database."""
    global _test_counter
    _test_counter = 0
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row  # Enable row access by name
    from stapled.db import _apply_migrations
    _apply_migrations(conn)
    yield conn
    conn.close()


def _setup_test_claims(conn, n_claims=3):
    """Helper to create test articles and claims."""
    global _test_counter

    # Create outlet (once)
    if _test_counter == 0:
        conn.execute("INSERT INTO outlet (name) VALUES (?)", ('test-outlet',))
        conn.commit()

    # Create articles and claims
    article_ids = []
    for i in range(n_claims):
        _test_counter += 1
        conn.execute(
            """INSERT INTO article (outlet_id, url, title, body, ingest_status)
               VALUES (?, ?, ?, ?, 'ok')""",
            (1, f"test://{_test_counter}", f"Title {_test_counter}", f"body text {_test_counter}"),
        )
        cursor = conn.execute("SELECT last_insert_rowid()")
        article_ids.append(cursor.fetchone()[0])

    # Create claims
    claim_ids = []
    for article_id in article_ids:
        conn.execute(
            """INSERT INTO claim (article_id, actor, action, object, event_id)
               VALUES (?, 'actor', 'action', 'object', NULL)""",
            (article_id,),
        )
        cursor = conn.execute("SELECT last_insert_rowid()")
        claim_ids.append(cursor.fetchone()[0])

    conn.commit()
    return claim_ids


def test_align_incremental_first_batch(test_db):
    """Test first batch: vocab freeze + event creation."""
    claim_ids = _setup_test_claims(test_db, 3)

    result = align_incremental(test_db, claim_ids)

    assert result["events_created"] >= 1
    assert result["claims_aligned"] == 3

    # Check vocab is frozen
    cursor = test_db.execute("SELECT COUNT(*) FROM tfidf_vocab")
    vocab_count = cursor.fetchone()[0]
    assert vocab_count > 0


def test_align_incremental_frozen_vocab(test_db):
    """Test second batch: use frozen vocab."""
    # First batch
    claim_ids_1 = _setup_test_claims(test_db, 2)
    align_incremental(test_db, claim_ids_1)

    # Second batch
    claim_ids_2 = _setup_test_claims(test_db, 2)
    result = align_incremental(test_db, claim_ids_2)

    assert result["claims_aligned"] > 0
    # May create new events or align to existing


def test_align_incremental_empty_claims(test_db):
    """Test with no claims."""
    result = align_incremental(test_db, [])

    assert result["events_created"] == 0
    assert result["claims_aligned"] == 0
    assert result["claims_unaligned"] == 0


def test_align_incremental_centroids_stored(test_db):
    """Test that event centroids are stored."""
    claim_ids = _setup_test_claims(test_db, 2)

    align_incremental(test_db, claim_ids)

    # Check centroids
    cursor = test_db.execute("SELECT COUNT(*) FROM event_centroid")
    count = cursor.fetchone()[0]
    assert count >= 1

    # Check centroid is valid JSON
    cursor = test_db.execute("SELECT vec_json FROM event_centroid LIMIT 1")
    row = cursor.fetchone()
    if row:
        vec = json.loads(row[0])
        assert isinstance(vec, list)


if __name__ == "__main__":
    pytest.main([__file__])
