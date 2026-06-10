"""Tests for claim extraction."""

import tempfile
from pathlib import Path

from stapled.db import connect, insert_and_get_id
from stapled.extract.claims import extract_claims_from_article
from stapled.extract.framing import update_framing_for_article


def test_extract_claims_basic():
    """Test basic claim extraction."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        outlet_id = insert_and_get_id(
            conn,
            "INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)",
            ("test", 0),
        )

        article_id = insert_and_get_id(
            conn,
            """INSERT INTO article
               (outlet_id, url, title, body, ingest_status)
               VALUES (?, ?, ?, ?, 'ok')""",
            (
                outlet_id,
                "url1",
                "Congress Passes Bill",
                "Congress passed a new bill on healthcare. The bill was approved by 220 to 215.",
            ),
        )

        counts = extract_claims_from_article(
            conn,
            article_id,
            "Congress Passes Bill",
            "Congress passed a new bill on healthcare. The bill was approved by 220 to 215.",
        )

        assert counts["claims_created"] > 0

        # Check claims exist
        cursor = conn.execute("SELECT COUNT(*) FROM claim WHERE article_id = ?", (article_id,))
        claim_count = cursor.fetchone()[0]
        assert claim_count > 0


def test_extract_claims_with_framing():
    """Test that framing metadata is extracted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        outlet_id = insert_and_get_id(
            conn,
            "INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)",
            ("test", 0),
        )

        article_id = insert_and_get_id(
            conn,
            """INSERT INTO article
               (outlet_id, url, title, body, ingest_status)
               VALUES (?, ?, ?, ?, 'ok')""",
            (
                outlet_id,
                "url1",
                "Official Denies Report",
                "Officials denied that the program was expanded. The spokesman issued a statement refuting the allegations.",
            ),
        )

        extract_claims_from_article(
            conn,
            article_id,
            "Official Denies Report",
            "Officials denied that the program was expanded. The spokesman issued a statement refuting the allegations.",
        )

        update_framing_for_article(
            conn,
            article_id,
            "Officials denied that the program was expanded. The spokesman issued a statement refuting the allegations.",
        )

        # Check that claims have framing metadata
        cursor = conn.execute(
            "SELECT attribution, hedging FROM claim WHERE article_id = ?",
            (article_id,),
        )
        rows = cursor.fetchall()
        assert len(rows) > 0
        # Should have some claims with attribution
        attributions = [row[0] for row in rows]
        assert any(attr in ["official", "direct"] for attr in attributions)
