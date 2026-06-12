"""Unit tests for UCI News Aggregator loader."""

import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

from stapled.db import connect
from stapled.ingest.uci import load_uci


def test_load_uci_mocked():
    """Test load_uci with mocked iter_remote_lines (5 fixture rows)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Fixture rows:
        # - 2 rows same STORY id, different HOSTNAME → same event_id
        # - 1 negation title → action='not-occurred'
        # - 1 platform-domain row (youtube.com) → skip
        # - 1 short/malformed row (missing TITLE) → skip
        mock_batch = [
            {
                "ID": "1",
                "TITLE": "Breaking News on Elections",
                "URL": "https://example.com/news1",
                "PUBLISHER": "Example",
                "CATEGORY": "b",
                "STORY": "story123",
                "HOSTNAME": "example.com",
                "TIMESTAMP": "1609459200000",  # 2021-01-01 00:00:00 UTC
            },
            {
                "ID": "2",
                "TITLE": "Similar Story elsewhere",
                "URL": "https://news.org/story1",
                "PUBLISHER": "News Org",
                "CATEGORY": "b",
                "STORY": "story123",  # Same story as row 1
                "HOSTNAME": "news.org",
                "TIMESTAMP": "1609459200000",
            },
            {
                "ID": "3",
                "TITLE": "Report denies false claims about the event",
                "URL": "https://trusted.com/article",
                "PUBLISHER": "Trusted",
                "CATEGORY": "t",
                "STORY": "story456",
                "HOSTNAME": "trusted.com",
                "TIMESTAMP": "1609545600000",
            },
            {
                "ID": "4",
                "TITLE": "Video shows incident",
                "URL": "https://youtube.com/watch?v=abc",
                "PUBLISHER": "YouTube",
                "CATEGORY": "e",
                "STORY": "story789",
                "HOSTNAME": "youtube.com",  # Platform domain → skip
                "TIMESTAMP": "1609632000000",
            },
            {
                "ID": "5",
                "TITLE": "",  # Missing TITLE → skip
                "URL": "https://incomplete.com/x",
                "PUBLISHER": "Incomplete",
                "CATEGORY": "m",
                "STORY": "story999",
                "HOSTNAME": "incomplete.com",
                "TIMESTAMP": "1609718400000",
            },
        ]

        def mock_iter_remote_lines(url, batch_bytes, conn, **kwargs):
            yield mock_batch
            return

        with patch(
            "stapled.ingest.uci.iter_remote_lines", side_effect=mock_iter_remote_lines
        ):
            counts = load_uci(conn, batch_bytes=524288)

        # Assertions: 3 loaded (rows 1, 2, 3), skip 2 (youtube, empty title)
        assert counts["articles_loaded"] == 3
        assert counts["skipped"] == 2
        assert counts["outlets_created"] == 3  # example.com, news.org, trusted.com
        assert counts["events_created"] == 2  # story123, story456
        assert counts["labels_written"] == 3

        # Check that story123 rows share the same event_id
        cursor = conn.execute(
            """SELECT DISTINCT us.event_id FROM uci_story us
               WHERE us.story_id = 'story123'"""
        )
        story123_events = cursor.fetchall()
        assert len(story123_events) == 1

        event_id = story123_events[0][0]

        # Both articles from story123 should have claims pointing to same event_id
        cursor = conn.execute(
            """SELECT COUNT(*) FROM claim WHERE event_id = ?""",
            (event_id,),
        )
        claim_count = cursor.fetchone()[0]
        assert claim_count == 2

        # Check negation detection (row 3: "denies false claims")
        cursor = conn.execute(
            """SELECT action FROM claim
               WHERE article_id IN (
                   SELECT id FROM article WHERE title LIKE '%denies%'
               )"""
        )
        action = cursor.fetchone()
        assert action is not None
        assert action[0] == "not-occurred"

        # Check non-negation action (row 1: "Breaking News")
        cursor = conn.execute(
            """SELECT action FROM claim
               WHERE article_id IN (
                   SELECT id FROM article WHERE title LIKE '%Breaking%'
               )"""
        )
        action = cursor.fetchone()
        assert action is not None
        assert action[0] == "occurred"

        # Check articles table
        cursor = conn.execute("SELECT COUNT(*) FROM article")
        articles = cursor.fetchone()[0]
        assert articles == 3

        # Check outlets table (3 unique domains)
        cursor = conn.execute("SELECT COUNT(*) FROM outlet")
        outlets = cursor.fetchone()[0]
        assert outlets == 3

        # Check labels
        cursor = conn.execute("SELECT COUNT(*) FROM article_label")
        labels = cursor.fetchone()[0]
        assert labels == 3


def test_uci_story_table_migration():
    """Test migration 004 creates uci_story table."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # uci_story table should exist after migration
        cursor = conn.execute(
            """SELECT name FROM sqlite_master
               WHERE type='table' AND name='uci_story'"""
        )
        assert cursor.fetchone() is not None


def test_resume_uses_cursor():
    """Test that resume creates cursor row for source URL."""
    from stapled.ingest.uci import UCI_URL

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Mock HTTP response with UCI field names (TAB-delimited, no header)
        csv_content = (
            "1\tTest Article\thttps://example.com/test\tExample\tb\tstory1\t"
            "example.com\t1609459200000\n"
        )

        mock_response = MagicMock()
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None
        mock_response.read = MagicMock(
            side_effect=[csv_content.encode("utf-8"), b""]
        )
        mock_response.headers = {
            "Content-Length": str(len(csv_content.encode("utf-8"))),
            "ETag": "test-etag",
        }

        with patch("urllib.request.urlopen", return_value=mock_response):
            load_uci(conn, batch_bytes=524288)

        # Check that source_cursor row was created for UCI_URL
        cursor = conn.execute(
            "SELECT id FROM source_cursor WHERE source_url = ?",
            (UCI_URL,),
        )
        assert cursor.fetchone() is not None


def test_iter_remote_lines_delimiter_fieldnames():
    """Test iter_remote_lines backward-compatible delimiter and fieldnames params."""
    from stapled.ingest.stream import iter_remote_lines

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Mock HTTP response with TAB-delimited data (no header — fieldnames supplied)
        csv_content = "value1\tvalue2\nvalue3\tvalue4\n"

        mock_response = MagicMock()
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None
        mock_response.read = MagicMock(
            side_effect=[csv_content.encode("utf-8"), b""]
        )
        mock_response.headers = {
            "Content-Length": str(len(csv_content.encode("utf-8"))),
            "ETag": "test-etag",
        }

        with patch("urllib.request.urlopen", return_value=mock_response):
            # Call with TAB delimiter and fieldnames
            batches = list(
                iter_remote_lines(
                    "https://example.com/test.csv",
                    262144,
                    conn,
                    delimiter="\t",
                    fieldnames=["COL1", "COL2"],
                )
            )
            # Should get batches with parsed rows
            assert len(batches) > 0
            assert len(batches[0]) == 2
            assert batches[0][0]["COL1"] == "value1"
            assert batches[0][0]["COL2"] == "value2"


def test_iter_remote_lines_unquoted_stray_quotes():
    """Test quoting=False with TAB-delimited unquoted data containing stray quotes."""
    from stapled.ingest.stream import iter_remote_lines

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Mock HTTP response with TAB-delimited unquoted data
        # Row 1: normal
        # Row 2: title contains stray quote (Fed's "tapering" plan)
        # Row 3: normal
        # With quoting=True, the stray quote would flip in_quotes, gluing rows 2+3
        # With quoting=False, plain newline split should parse all 3 correctly
        csv_content = (
            "1\tNormal Title\thttps://example.com/1\texample.com\n"
            "2\tFed's \"tapering\" plan announced\thttps://example.com/2\texample.com\n"
            "3\tAnother story\thttps://example.com/3\texample.com\n"
        )

        mock_response = MagicMock()
        mock_response.__enter__ = lambda self: self
        mock_response.__exit__ = lambda self, *args: None
        mock_response.read = MagicMock(
            side_effect=[csv_content.encode("utf-8"), b""]
        )
        mock_response.headers = {
            "Content-Length": str(len(csv_content.encode("utf-8"))),
            "ETag": "test-etag",
        }

        with patch("urllib.request.urlopen", return_value=mock_response):
            # Call with quoting=False (unquoted mode)
            batches = list(
                iter_remote_lines(
                    "https://example.com/test.csv",
                    262144,
                    conn,
                    delimiter="\t",
                    fieldnames=["ID", "TITLE", "URL", "HOSTNAME"],
                    quoting=False,
                )
            )
            # Should get all 3 rows parsed correctly (no gluing)
            assert len(batches) > 0
            all_rows = [row for batch in batches for row in batch]
            assert len(all_rows) == 3
            # Row 1
            assert all_rows[0]["ID"] == "1"
            assert all_rows[0]["TITLE"] == "Normal Title"
            # Row 2 (with stray quotes)
            assert all_rows[1]["ID"] == "2"
            assert 'tapering' in all_rows[1]["TITLE"]
            # Row 3
            assert all_rows[2]["ID"] == "3"
            assert all_rows[2]["TITLE"] == "Another story"
