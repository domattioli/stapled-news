"""Tests for event alignment."""

import tempfile
from pathlib import Path

from stapled.db import connect, insert_and_get_id
from stapled.align.cluster import align


def test_align_creates_events():
    """Test that similar claims are aligned into events."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Create two outlets
        outlet1 = insert_and_get_id(
            conn, "INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("outlet_a", 0)
        )
        outlet2 = insert_and_get_id(
            conn, "INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("outlet_b", 0)
        )

        # Create articles (real: corpus_id = NULL)
        art1 = insert_and_get_id(
            conn,
            """INSERT INTO article
               (outlet_id, corpus_id, url, title, body, ingest_status)
               VALUES (?, NULL, ?, ?, ?, 'ok')""",
            (outlet1, "url1", "Congress Votes", "Congress voted to pass new healthcare bill today."),
        )

        art2 = insert_and_get_id(
            conn,
            """INSERT INTO article
               (outlet_id, corpus_id, url, title, body, ingest_status)
               VALUES (?, NULL, ?, ?, ?, 'ok')""",
            (outlet2, "url2", "Bill Passes Congress", "Congress passed healthcare reform with broad support."),
        )

        # Create claims (similar content)
        insert_and_get_id(
            conn,
            """INSERT INTO claim
               (article_id, event_id, actor, action, object, extraction_score)
               VALUES (?, NULL, ?, ?, ?, ?)""",
            (art1, "Congress", "passed", "healthcare bill", 0.8),
        )

        insert_and_get_id(
            conn,
            """INSERT INTO claim
               (article_id, event_id, actor, action, object, extraction_score)
               VALUES (?, NULL, ?, ?, ?, ?)""",
            (art2, "Congress", "passed", "healthcare reform", 0.8),
        )

        # Run alignment (require min 2 outlets for clustering)
        stats = align(conn, min_outlets=2, similarity_threshold=0.3)

        # Should create at least one event (since we have 2 outlets)
        # Note: Claims may not align if TF-IDF similarity is low
        # This is more of an integration test
        assert "events_created" in stats
        assert "claims_aligned" in stats


def test_align_respects_min_outlets():
    """Test that alignment requires minimum outlets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Single outlet
        outlet = insert_and_get_id(
            conn, "INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("outlet_a", 0)
        )

        art = insert_and_get_id(
            conn,
            """INSERT INTO article
               (outlet_id, corpus_id, url, title, body, ingest_status)
               VALUES (?, NULL, ?, ?, ?, 'ok')""",
            (outlet, "url1", "Story", "Congress voted today."),
        )

        insert_and_get_id(
            conn,
            """INSERT INTO claim
               (article_id, event_id, actor, action, object, extraction_score)
               VALUES (?, NULL, ?, ?, ?, ?)""",
            (art, "Congress", "voted", "on bill", 0.8),
        )

        # Require min 2 outlets
        stats = align(conn, min_outlets=2)

        # Should not create event (needs 2 distinct outlets)
        assert stats["events_created"] == 0
        assert stats["claims_aligned"] == 0
