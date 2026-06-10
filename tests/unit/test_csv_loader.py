"""Tests for CSV loader."""

import tempfile
from pathlib import Path

from stapled.db import connect
from stapled.ingest.csv_loader import load_isot, _parse_date, _strip_reuters_dateline, _normalize_subject


def test_parse_date():
    """Test date parsing."""
    assert _parse_date("December 31, 2017").startswith("2017-12-31")
    assert _parse_date("Jan 1, 2020").startswith("2020-01-01")
    assert _parse_date("2020-05-15") == "2020-05-15T00:00:00"
    assert _parse_date("invalid") is None
    assert _parse_date("") is None


def test_strip_reuters_dateline():
    """Test Reuters dateline stripping."""
    text = "WASHINGTON (Reuters) - Congress voted today."
    result = _strip_reuters_dateline(text)
    assert result == "Congress voted today."

    text = "NEW YORK, NY (Reuters) - Markets closed higher."
    result = _strip_reuters_dateline(text)
    assert result == "Markets closed higher."

    # No dateline
    text = "Congress voted today."
    assert _strip_reuters_dateline(text) == "Congress voted today."


def test_normalize_subject():
    """Test subject normalization to outlet name."""
    assert _normalize_subject("News") == "fake:news"
    assert _normalize_subject("U.S. Politics") == "fake:us-politics"
    assert _normalize_subject("World News") == "fake:world-news"


def test_load_isot_basic():
    """Test basic ISOT loading."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Create tiny test CSVs (with long enough text)
        true_text = "WASHINGTON (Reuters) - This is a test story about politics with important details that is definitely at least 200 chars long so it passes the minimum length requirement and will be loaded successfully by the loader system to ensure proper database insertion."
        fake_text = "This is a fake news story that contains misinformation and is at least 200 characters long to pass the minimum text length filter in the loader and ensure that the article gets properly loaded into the database system."

        true_csv = Path(tmpdir) / "true.csv"
        true_csv.write_text(
            "title,text,subject,date\n"
            f"Test Story,{true_text},Politics,January 1 2020\n"
        )

        fake_csv = Path(tmpdir) / "fake.csv"
        fake_csv.write_text(
            "title,text,subject,date\n"
            f"Fake Story,{fake_text},News,February 2 2020\n"
        )

        counts = load_isot(conn, str(true_csv), str(fake_csv), limit_per_outlet=10)

        assert counts["articles_loaded"] == 2
        assert counts["articles_skipped"] == 0
        assert counts["outlets_created"] == 2

        # Check outlets were created
        cursor = conn.execute("SELECT COUNT(*) FROM outlet")
        assert cursor.fetchone()[0] == 2

        # Check articles
        cursor = conn.execute("SELECT COUNT(*) FROM article WHERE ingest_status='ok'")
        assert cursor.fetchone()[0] == 2


def test_load_isot_skip_short():
    """Test that short articles are skipped."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        fake_text = "This is a fake news story that contains significant misinformation and political commentary with excessive length to pass the minimum text length filter requirement in the loader and ensure proper database insertion and subsequent processing of the articles in our system."

        true_csv = Path(tmpdir) / "true.csv"
        true_csv.write_text(
            "title,text,subject,date\n"
            "Short,Too short.,Politics,January 1 2020\n"
        )

        fake_csv = Path(tmpdir) / "fake.csv"
        fake_csv.write_text(
            "title,text,subject,date\n"
            f"Fake,{fake_text},News,February 2 2020\n"
        )

        counts = load_isot(conn, str(true_csv), str(fake_csv), limit_per_outlet=10)

        assert counts["articles_loaded"] == 1
        assert counts["articles_skipped"] == 1
