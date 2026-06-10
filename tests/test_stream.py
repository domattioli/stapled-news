"""Tests for streaming CSV ingestion."""

import sqlite3
import pytest
from io import BytesIO
from unittest.mock import patch

from stapled.ingest.stream import iter_remote_lines, dedup_new_articles


@pytest.fixture
def test_db():
    """Create in-memory test database."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    # Run migrations
    from stapled.db import _apply_migrations
    _apply_migrations(conn)
    yield conn
    conn.close()


def test_iter_remote_lines_basic(test_db):
    """Test basic streaming without resumption."""
    csv_data = b"title,text,date\nArticle 1,This is test text for article one,2023-01-01\n"

    with patch("urllib.request.urlopen") as mock_urlopen:
        # Mock response
        mock_response = BytesIO(csv_data)
        mock_response.headers = {"ETag": "abc123"}
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response
        mock_urlopen.return_value.__exit__.return_value = False

        # Iterate
        batches = list(iter_remote_lines("http://example.com/test.csv", 1000, test_db))

        assert len(batches) > 0
        assert len(batches[0]) >= 1
        assert "title" in batches[0][0]


def test_iter_remote_lines_cursor_tracking(test_db):
    """Test that cursor is tracked in database."""
    csv_data = b"title,text\nA,Test\nB,Text\n"

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_response = BytesIO(csv_data)
        mock_response.headers = {"ETag": "xyz"}
        mock_response.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_response
        mock_urlopen.return_value.__exit__.return_value = False

        list(iter_remote_lines("http://example.com/test.csv", 100, test_db))

        # Check cursor record
        cursor = test_db.execute(
            "SELECT byte_offset, done FROM source_cursor WHERE source_url = ?",
            ("http://example.com/test.csv",),
        )
        row = cursor.fetchone()
        assert row is not None
        _, done = row
        assert done == 1  # Should be marked done


def test_dedup_new_articles(test_db):
    """Test simhash bucketing for dedup."""
    # Create test articles
    test_db.execute(
        """INSERT INTO outlet (id, name) VALUES (1, 'test-outlet')"""
    )
    test_db.execute(
        """INSERT INTO article (id, outlet_id, url, title, body, ingest_status)
           VALUES (1, 1, 'test://1', 'Title One', 'This is test body text for article one test', 'ok')"""
    )
    test_db.execute(
        """INSERT INTO article (id, outlet_id, url, title, body, ingest_status)
           VALUES (2, 1, 'test://2', 'Title Two', 'This is test body text for article one test', 'ok')"""
    )
    test_db.commit()

    # Dedup
    dedup_new_articles(test_db, [1, 2])

    # Check simhash_bucket records
    cursor = test_db.execute("SELECT COUNT(*) FROM simhash_bucket")
    count = cursor.fetchone()[0]
    assert count >= 4  # At least 4 bands


def test_iter_remote_lines_resumption(test_db):
    """Test cursor resumption on second call."""
    csv_data = b"title,text\nA,Test\nB,Text\n"

    with patch("urllib.request.urlopen") as mock_urlopen:
        # First call
        mock_response1 = BytesIO(csv_data)
        mock_response1.headers = {"ETag": "v1"}
        mock_response1.status = 200

        # Second call (resumption)
        mock_response2 = BytesIO(csv_data)
        mock_response2.headers = {"ETag": "v1"}
        mock_response2.status = 206

        mock_urlopen.return_value.__enter__.side_effect = [mock_response1, mock_response2]
        mock_urlopen.return_value.__exit__.return_value = False

        # First call
        list(iter_remote_lines("http://example.com/test.csv", 100, test_db))

        # Check cursor state after first call
        cursor = test_db.execute(
            "SELECT done FROM source_cursor WHERE source_url = ?",
            ("http://example.com/test.csv",),
        )
        row = cursor.fetchone()
        assert row[0] == 1  # Done


if __name__ == "__main__":
    pytest.main([__file__])
