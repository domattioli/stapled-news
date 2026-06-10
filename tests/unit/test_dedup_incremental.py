"""Unit tests for incremental dedup."""

from stapled.db import connect
from stapled.ingest.stream import dedup_new_articles


def test_dedup_new_articles_creates_buckets(tmp_path):
    """Test dedup_new_articles creates simhash_bucket entries."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create outlet
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('TestOutlet', 0)")
    outlet_id = cursor.lastrowid

    # Create 2 articles
    article_ids = []
    for i in range(2):
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, corpus_id, url, body, ingest_status) VALUES (?, NULL, ?, ?, 'ok')",
            (outlet_id, f"http://ex.com/{i}", f"Article body {i}"),
        )
        article_ids.append(cursor.lastrowid)

    conn.commit()

    # Call dedup_new_articles
    dedup_new_articles(conn, article_ids)

    # Check: simhash_bucket should have 2 * 4 = 8 entries (4 bands per article)
    cursor = conn.execute("SELECT COUNT(*) FROM simhash_bucket")
    count = cursor.fetchone()[0]
    assert count == 8

    # Check: both articles are in the buckets
    cursor = conn.execute("SELECT COUNT(DISTINCT article_id) FROM simhash_bucket")
    distinct = cursor.fetchone()[0]
    assert distinct == 2


def test_dedup_new_articles_band_distribution(tmp_path):
    """Test dedup_new_articles distributes across 4 bands."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('Out1', 0)")
    outlet_id = cursor.lastrowid

    cursor = conn.execute(
        "INSERT INTO article (outlet_id, corpus_id, url, body, ingest_status) VALUES (?, NULL, ?, ?, 'ok')",
        (outlet_id, "http://ex.com/1", "Test body for article one"),
    )
    article_id = cursor.lastrowid
    conn.commit()

    dedup_new_articles(conn, [article_id])

    # Check bands 0-3 are populated
    for band in range(4):
        cursor = conn.execute(
            "SELECT COUNT(*) FROM simhash_bucket WHERE band = ? AND article_id = ?",
            (band, article_id),
        )
        count = cursor.fetchone()[0]
        assert count == 1, f"Band {band} should have 1 entry"
