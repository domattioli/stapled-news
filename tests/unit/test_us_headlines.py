"""Tests for US headlines CSV loader."""

import csv
import gzip
import tempfile
from pathlib import Path

import pytest

from stapled.db import connect
from stapled.ingest.us_headlines import load_us_headlines


@pytest.fixture
def tmp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))
        yield conn
        conn.close()


@pytest.fixture
def tmp_csv_dir():
    """Create a temporary directory for CSV files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield Path(tmpdir)


def test_load_basic(tmp_db, tmp_csv_dir):
    """Test basic load: 3 domains, one below floor (min_outlet_articles=2)."""
    csv_path = tmp_csv_dir / "headlines.csv"

    # Create CSV: domain,title,url,seendate,source
    rows = [
        {"domain": "bbc.com", "title": "Senate denies report on security", "url": "http://bbc.com/1", "seendate": "20260612T140000Z", "source": ""},
        {"domain": "bbc.com", "title": "Parliament approves new bill", "url": "http://bbc.com/2", "seendate": "20260612T150000Z", "source": ""},
        {"domain": "cnn.com", "title": "Breaking news today", "url": "http://cnn.com/1", "seendate": "20260612T160000Z", "source": ""},
        {"domain": "cnn.com", "title": "Another story", "url": "http://cnn.com/2", "seendate": "20260612T170000Z", "source": ""},
        {"domain": "nytimes.com", "title": "Only one from this outlet", "url": "http://nytimes.com/1", "seendate": "20260612T180000Z", "source": ""},
    ]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["domain", "title", "url", "seendate", "source"])
        writer.writeheader()
        writer.writerows(rows)

    # Load with min_outlet_articles=2 → only bbc.com and cnn.com kept
    counts = load_us_headlines(tmp_db, path=str(csv_path), min_outlet_articles=2)

    # Assertions
    assert counts["rows_read"] == 5
    assert counts["articles_new"] == 4  # bbc.com (2) + cnn.com (2)
    assert counts["articles_existing"] == 0
    assert counts["outlets_kept"] == 2  # bbc.com, cnn.com
    assert counts["outlets_dropped"] == 1  # nytimes.com

    # Check that outlets were created
    cursor = tmp_db.execute("SELECT COUNT(*) FROM outlet WHERE name IN ('bbc.com', 'cnn.com')")
    assert cursor.fetchone()[0] == 2

    # Check that nytimes outlet was NOT created
    cursor = tmp_db.execute("SELECT COUNT(*) FROM outlet WHERE name = 'nytimes.com'")
    assert cursor.fetchone()[0] == 0

    # Check claims were created: "denies" should trigger not-occurred
    cursor = tmp_db.execute(
        "SELECT action FROM claim WHERE article_id IN (SELECT id FROM article WHERE title LIKE 'Senate denies%')"
    )
    row = cursor.fetchone()
    assert row is not None
    assert row[0] == "not-occurred"


def test_idempotent_rerun(tmp_db, tmp_csv_dir):
    """Test idempotent rerun: second load has no new articles."""
    csv_path = tmp_csv_dir / "headlines.csv"

    rows = [
        {"domain": "bbc.com", "title": "Story 1", "url": "http://bbc.com/1", "seendate": "20260612T140000Z", "source": ""},
        {"domain": "bbc.com", "title": "Story 2", "url": "http://bbc.com/2", "seendate": "20260612T150000Z", "source": ""},
    ]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["domain", "title", "url", "seendate", "source"])
        writer.writeheader()
        writer.writerows(rows)

    # First load
    counts1 = load_us_headlines(tmp_db, path=str(csv_path), min_outlet_articles=1)
    assert counts1["articles_new"] == 2
    assert counts1["articles_existing"] == 0

    # Second load (same CSV)
    counts2 = load_us_headlines(tmp_db, path=str(csv_path), min_outlet_articles=1)
    assert counts2["articles_new"] == 0
    assert counts2["articles_existing"] == 2

    # Verify no duplicate articles in DB
    cursor = tmp_db.execute("SELECT COUNT(*) FROM article")
    assert cursor.fetchone()[0] == 2


def test_gz_and_plain(tmp_db, tmp_csv_dir):
    """Test both .gz and plain CSV paths work."""
    csv_path = tmp_csv_dir / "headlines.csv"
    gz_path = tmp_csv_dir / "headlines.csv.gz"

    rows = [
        {"domain": "bbc.com", "title": "Story 1", "url": "http://bbc.com/1", "seendate": "20260612T140000Z", "source": ""},
        {"domain": "bbc.com", "title": "Story 2", "url": "http://bbc.com/2", "seendate": "20260612T150000Z", "source": ""},
    ]

    # Create plain CSV
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["domain", "title", "url", "seendate", "source"])
        writer.writeheader()
        writer.writerows(rows)

    # Create gzipped CSV
    with gzip.open(gz_path, "wt", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["domain", "title", "url", "seendate", "source"])
        writer.writeheader()
        writer.writerows(rows)

    # Load plain
    counts_plain = load_us_headlines(tmp_db, path=str(csv_path), min_outlet_articles=1)
    assert counts_plain["articles_new"] == 2

    # Load gzipped (will be existing)
    counts_gz = load_us_headlines(tmp_db, path=str(gz_path), min_outlet_articles=1)
    assert counts_gz["articles_new"] == 0
    assert counts_gz["articles_existing"] == 2


def test_url_platform_skip(tmp_db, tmp_csv_dir):
    """Test that youtube.com URLs are skipped."""
    csv_path = tmp_csv_dir / "headlines.csv"

    rows = [
        {"domain": "", "title": "Video story", "url": "https://www.youtube.com/watch?v=abc123", "seendate": "20260612T140000Z", "source": ""},
        {"domain": "bbc.com", "title": "Real story", "url": "http://bbc.com/1", "seendate": "20260612T150000Z", "source": ""},
    ]

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["domain", "title", "url", "seendate", "source"])
        writer.writeheader()
        writer.writerows(rows)

    # Load with min_outlet_articles=1
    counts = load_us_headlines(tmp_db, path=str(csv_path), min_outlet_articles=1)

    # Only bbc.com article should load (youtube skipped)
    assert counts["rows_read"] == 2
    assert counts["articles_new"] == 1  # only bbc.com
    assert counts["skipped"] >= 1  # youtube skipped

    # Verify no youtube outlet
    cursor = tmp_db.execute("SELECT COUNT(*) FROM outlet WHERE name LIKE '%youtube%'")
    assert cursor.fetchone()[0] == 0
