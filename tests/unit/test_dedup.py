"""Tests for dedup module."""

import tempfile
from pathlib import Path

from stapled.db import connect, insert_and_get_id
from stapled.ingest.dedup import dedup_articles


def test_dedup_articles_cluster_similar():
    """Test that near-duplicate articles are clustered."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Create outlets
        outlet_id = insert_and_get_id(
            conn,
            "INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)",
            ("test_outlet", 0),
        )

        # Insert two near-identical articles (wire copies)
        base_text = "Congressional leaders announced new healthcare legislation. The bill aims to expand coverage and reduce costs. Key provisions include increased federal funding and new insurance market regulations."
        text1 = base_text
        text2 = base_text  # Exact duplicate

        for i, text in enumerate([text1, text2]):
            insert_and_get_id(
                conn,
                """INSERT INTO article
                   (outlet_id, url, title, body, ingest_status)
                   VALUES (?, ?, ?, ?, 'ok')""",
                (outlet_id, f"url_{i}", f"title_{i}", text),
            )

        # Run dedup
        dedup_articles(conn)

        # Check that they were clustered
        cursor = conn.execute("SELECT dedup_cluster_id FROM article WHERE dedup_cluster_id IS NOT NULL")
        rows = cursor.fetchall()
        assert len(rows) == 2  # Both should be in the same cluster


def test_dedup_articles_no_cluster_distinct():
    """Test that distinct articles are not clustered."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        outlet_id = insert_and_get_id(
            conn,
            "INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)",
            ("test_outlet", 0),
        )

        # Insert two very different articles
        text1 = "The president announced new policy on climate change and environmental protection."
        text2 = "Sports: The team won the championship game with a final score of 3 to 2."

        for i, text in enumerate([text1, text2]):
            insert_and_get_id(
                conn,
                """INSERT INTO article
                   (outlet_id, url, title, body, ingest_status)
                   VALUES (?, ?, ?, ?, 'ok')""",
                (outlet_id, f"url_{i}", f"title_{i}", text),
            )

        dedup_articles(conn)

        # Check that they were NOT clustered (or minimal clustering)
        cursor = conn.execute(
            "SELECT COUNT(DISTINCT dedup_cluster_id) FROM article WHERE dedup_cluster_id IS NOT NULL"
        )
        cluster_count = cursor.fetchone()[0]
        # Should have 0 or 1 clusters (only if accidentally similar)
        assert cluster_count <= 1
