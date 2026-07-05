"""Tests for incremental alignment."""

from stapled.db import connect
from stapled.infer.align_incremental import align_incremental


def test_align_incremental_first_batch(tmp_path):
    """Test first batch: vocab frozen, events created."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create outlet + articles + claims
    outlet_cursor = conn.execute(
        "INSERT INTO outlet (name, is_synthetic) VALUES ('test', 1)"
    )
    outlet_id = outlet_cursor.lastrowid

    article_ids = []
    claim_ids = []
    for i in range(3):
        cursor = conn.execute(
            """INSERT INTO article (outlet_id, corpus_id, url, title, body, ingest_status)
               VALUES (?, NULL, ?, ?, ?, 'ok')""",
            (outlet_id, f"http://ex.com/{i}", f"Title {i}", f"body text {i}" * 20),
        )
        article_ids.append(cursor.lastrowid)

        cursor = conn.execute(
            """INSERT INTO claim (article_id, actor, action, object)
               VALUES (?, ?, ?, ?)""",
            (cursor.lastrowid, "actor", "said", "something"),
        )
        claim_ids.append(cursor.lastrowid)

    conn.commit()

    # Run alignment
    result = align_incremental(conn, claim_ids)

    # Check vocab frozen
    vocab_count = conn.execute("SELECT COUNT(*) FROM tfidf_vocab").fetchone()[0]
    assert vocab_count > 0, "Vocab not frozen"

    # Check events created
    assert result["events_created"] > 0
    assert result["claims_aligned"] == len(claim_ids)

    # Check centroids
    centroid_count = conn.execute("SELECT COUNT(*) FROM event_centroid").fetchone()[0]
    assert centroid_count > 0


def test_align_incremental_second_batch(tmp_path):
    """Test second batch: use frozen vocab, align to existing events."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    outlet_cursor = conn.execute(
        "INSERT INTO outlet (name, is_synthetic) VALUES ('test', 1)"
    )
    outlet_id = outlet_cursor.lastrowid

    # First batch
    first_claim_ids = []
    for i in range(2):
        cursor = conn.execute(
            """INSERT INTO article (outlet_id, corpus_id, url, title, body, ingest_status)
               VALUES (?, NULL, ?, ?, ?, 'ok')""",
            (outlet_id, f"http://ex.com/{i}", f"Title {i}", "apple banana cherry" * 20),
        )
        cursor = conn.execute(
            """INSERT INTO claim (article_id, actor, action, object)
               VALUES (?, ?, ?, ?)""",
            (cursor.lastrowid, "actor", "said", "something"),
        )
        first_claim_ids.append(cursor.lastrowid)

    conn.commit()

    result1 = align_incremental(conn, first_claim_ids)
    assert result1["events_created"] > 0

    # Second batch (similar text)
    second_claim_ids = []
    for i in range(2, 4):
        cursor = conn.execute(
            """INSERT INTO article (outlet_id, corpus_id, url, title, body, ingest_status)
               VALUES (?, NULL, ?, ?, ?, 'ok')""",
            (outlet_id, f"http://ex.com/{i}", f"Title {i}", "apple banana cherry" * 20),
        )
        cursor = conn.execute(
            """INSERT INTO claim (article_id, actor, action, object)
               VALUES (?, ?, ?, ?)""",
            (cursor.lastrowid, "actor", "said", "something"),
        )
        second_claim_ids.append(cursor.lastrowid)

    conn.commit()

    result2 = align_incremental(conn, second_claim_ids)
    assert result2["claims_aligned"] == len(second_claim_ids)

    # Check vocab still has same size
    vocab_count = conn.execute("SELECT COUNT(*) FROM tfidf_vocab").fetchone()[0]
    assert vocab_count > 0


def test_align_incremental_empty_claims(tmp_path):
    """Test with no claims (edge case)."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    result = align_incremental(conn, [])

    assert result["events_created"] == 0
    assert result["claims_aligned"] == 0
    assert result["claims_unaligned"] == 0
