"""Unit tests for FakeNewsNet loader."""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from stapled.db import connect
from stapled.ingest.fakenewsnet import normalize_domain, load_fakenewsnet, load_external_labels


def test_normalize_domain():
    """Test domain normalization."""
    # Full URL with www
    assert normalize_domain("http://www.nfib-sbet.org/x") == "nfib-sbet.org"

    # URL with m. subdomain
    assert normalize_domain("https://m.cnn.com/story") == "cnn.com"

    # URL without scheme
    assert normalize_domain("people.com/a") == "people.com"

    # amp. subdomain
    assert normalize_domain("https://amp.example.com") == "example.com"

    # Empty string
    assert normalize_domain("") is None

    # No dot (bare hostname)
    assert normalize_domain("notaurl") is None

    # With port
    assert normalize_domain("http://example.com:8080/path") == "example.com"

    # Already normalized
    assert normalize_domain("example.com") == "example.com"

    # Case insensitivity
    assert normalize_domain("EXAMPLE.COM") == "example.com"

    # None input
    assert normalize_domain(None) is None

    # Empty whitespace
    assert normalize_domain("   ") is None


def test_load_fakenewsnet_mocked():
    """Test load_fakenewsnet with mocked iter_remote_lines."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Mock data: 3 rows (one with bad news_url)
        mock_batch = [
            {
                "id": "1",
                "news_url": "http://www.example.com/article1",
                "title": "Article One",
                "tweet_ids": "",
            },
            {
                "id": "2",
                "news_url": "",  # Bad: empty news_url
                "title": "Article Two",
                "tweet_ids": "",
            },
            {
                "id": "3",
                "news_url": "https://news.example.org/story",
                "title": "Article Three",
                "tweet_ids": "",
            },
        ]

        def mock_iter_remote_lines(url, batch_bytes, conn):
            # Only for politifact_real
            if "politifact_real" in url:
                yield mock_batch
            return

        with patch(
            "stapled.ingest.fakenewsnet.iter_remote_lines", side_effect=mock_iter_remote_lines
        ):
            counts = load_fakenewsnet(conn, batch_bytes=262144, datasets=["politifact_real"])

        # Should have loaded 2 articles (skipped 1 with empty news_url)
        assert counts["articles_loaded"] == 2
        assert counts["labels_written"] == 2

        # Check outlets created (2 unique domains)
        cursor = conn.execute("SELECT COUNT(*) FROM outlet")
        outlets = cursor.fetchone()[0]
        assert outlets == 2

        # Check articles
        cursor = conn.execute("SELECT COUNT(*) FROM article")
        articles = cursor.fetchone()[0]
        assert articles == 2

        # Check labels
        cursor = conn.execute("SELECT COUNT(*) FROM article_label")
        labels = cursor.fetchone()[0]
        assert labels == 2

        # Verify body == title (FakeNewsNet has no body text)
        cursor = conn.execute(
            "SELECT title, body FROM article WHERE title = 'Article One'"
        )
        row = cursor.fetchone()
        assert row[0] == row[1]  # title == body

        # Verify dataset and label in article_label
        cursor = conn.execute(
            "SELECT dataset, label FROM article_label ORDER BY article_id LIMIT 1"
        )
        row = cursor.fetchone()
        assert row[0] == "politifact_real"
        assert row[1] == "real"


def test_load_external_labels_mocked():
    """Test load_external_labels with mocked urllib response."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Mock TSV response
        tsv_content = (
            "source_url\tsource_url_normalized\tref\tfact\tbias\n"
            "http://example.com\twww.example.com\tref1\thigh\tleft\n"
            "http://news.org\tnews.org\tref2\tmedium\tcenter\n"
        )

        def mock_urlopen(req, timeout=None):
            mock_response = MagicMock()
            mock_response.read.return_value = tsv_content.encode("utf-8")
            mock_response.__enter__.return_value = mock_response
            mock_response.__exit__.return_value = None
            return mock_response

        with patch("urllib.request.urlopen", side_effect=mock_urlopen):
            count = load_external_labels(conn)

        # Should have inserted 2 rows
        assert count == 2

        # Check outlet_external_label table
        cursor = conn.execute("SELECT COUNT(*) FROM outlet_external_label")
        rows = cursor.fetchone()[0]
        assert rows == 2

        # Verify domain normalization (www. stripped)
        cursor = conn.execute(
            "SELECT fact, bias FROM outlet_external_label WHERE domain = 'example.com'"
        )
        row = cursor.fetchone()
        assert row[0] == "high"
        assert row[1] == "left"

        # Verify source is set correctly
        cursor = conn.execute(
            "SELECT source FROM outlet_external_label WHERE domain = 'news.org'"
        )
        row = cursor.fetchone()
        assert row[0] == "mbfc_acl2020"


def test_migration_tables_exist():
    """Test that migration 003 creates the required tables."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Check article_label table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='article_label'"
        )
        assert cursor.fetchone() is not None

        # Check outlet_external_label table exists
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='outlet_external_label'"
        )
        assert cursor.fetchone() is not None

        # Check schema of article_label
        cursor = conn.execute("PRAGMA table_info(article_label)")
        cols = {row[1]: row[2] for row in cursor.fetchall()}
        assert "article_id" in cols
        assert "dataset" in cols
        assert "label" in cols

        # Check schema of outlet_external_label
        cursor = conn.execute("PRAGMA table_info(outlet_external_label)")
        cols = {row[1]: row[2] for row in cursor.fetchall()}
        assert "domain" in cols
        assert "fact" in cols
        assert "bias" in cols
        assert "source" in cols
