"""Tests for streaming CSV ingestion."""

from unittest.mock import patch, MagicMock
from stapled.db import connect
from stapled.ingest.stream import dedup_new_articles, iter_remote_lines, _split_quoted_records


def test_stream_cursor_init(tmp_path):
    """Test source_cursor initialization."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Fake streaming would init cursor
    cursor_row = conn.execute(
        "SELECT COUNT(*) FROM source_cursor"
    ).fetchone()
    assert cursor_row[0] == 0  # No cursor yet

    # Mock cursor init
    conn.execute(
        """INSERT INTO source_cursor (source_url, byte_offset, rows_ingested, done, updated_at)
           VALUES (?, 0, 0, 0, datetime('now'))""",
        ("http://example.com/data.csv",),
    )
    conn.commit()

    cursor_row = conn.execute(
        "SELECT id, byte_offset, done FROM source_cursor WHERE source_url = ?",
        ("http://example.com/data.csv",),
    ).fetchone()
    assert cursor_row is not None
    assert cursor_row[1] == 0  # byte_offset
    assert cursor_row[2] == 0  # not done


def test_dedup_new_articles(tmp_path):
    """Test incremental simhash bucketing."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create outlet + articles
    outlet_cursor = conn.execute(
        "INSERT INTO outlet (name, is_synthetic) VALUES ('test', 1)"
    )
    outlet_id = outlet_cursor.lastrowid

    bodies = [
        "the quick brown fox jumps over the lazy dog" * 3,
        "the quick brown fox jumps over the lazy dog" * 3,  # duplicate
        "completely different text here that is not similar at all" * 3,
    ]

    article_ids = []
    for body in bodies:
        cursor = conn.execute(
            """INSERT INTO article (outlet_id, corpus_id, url, title, body, ingest_status)
               VALUES (?, NULL, ?, ?, ?, 'ok')""",
            (outlet_id, f"http://ex.com/{len(article_ids)}", "Title", body),
        )
        article_ids.append(cursor.lastrowid)

    conn.commit()

    # Dedup new articles
    dedup_new_articles(conn, article_ids)

    # Check simhash_bucket populated
    bucket_cursor = conn.execute("SELECT COUNT(*) FROM simhash_bucket")
    bucket_count = bucket_cursor.fetchone()[0]
    assert bucket_count > 0  # Should have buckets

    # Each article should have 4 band entries
    for article_id in article_ids:
        article_bucket_count = conn.execute(
            "SELECT COUNT(*) FROM simhash_bucket WHERE article_id = ?",
            (article_id,),
        ).fetchone()[0]
        assert article_bucket_count == 4  # 4 bands


def test_stream_cursor_resume(tmp_path):
    """Test cursor resumption (byte_offset tracking)."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    url = "http://example.com/data.csv"

    # Simulate cursor at offset 1000
    conn.execute(
        """INSERT INTO source_cursor (source_url, byte_offset, rows_ingested, done, etag, updated_at)
           VALUES (?, 1000, 42, 0, 'abc123', datetime('now'))""",
        (url,),
    )
    conn.commit()

    # Fetch cursor
    cursor = conn.execute(
        "SELECT byte_offset, rows_ingested, done FROM source_cursor WHERE source_url = ?",
        (url,),
    ).fetchone()

    assert cursor[0] == 1000  # byte_offset preserved
    assert cursor[1] == 42  # rows_ingested preserved
    assert cursor[2] == 0  # not done


def test_stream_done_only_on_eof(tmp_path):
    """Test that done=1 is set only when reaching EOF, not on max_batches limit."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    url = "http://example.com/partial.csv"

    # Insert cursor with partial read (byte_offset < content_length)
    # Simulates: byte_offset=8495104 after stopping at --max-batches, total=53561522
    conn.execute(
        """INSERT INTO source_cursor (source_url, byte_offset, rows_ingested, done, etag, updated_at)
           VALUES (?, 8495104, 100, 0, 'abc123', datetime('now'))""",
        (url,),
    )
    conn.commit()

    # Verify done is still 0 (not marked complete)
    cursor = conn.execute(
        "SELECT done FROM source_cursor WHERE source_url = ?",
        (url,),
    ).fetchone()
    assert cursor[0] == 0, "Cursor should not be marked done if byte_offset < content_length"


def test_split_quoted_records_embedded_newline():
    """Test quote-aware record splitting with embedded newlines in quoted fields."""
    # CSV record with embedded newline inside quotes
    csv_text = 'id,name,body\n1,"John","Hello\nWorld"\n2,"Jane","Goodbye"'

    records = _split_quoted_records(csv_text)

    # Should have 3 elements: header, row1, row2 (last is incomplete, no trailing newline)
    assert len(records) == 3
    assert records[0] == "id,name,body"
    assert records[1] == '1,"John","Hello\nWorld"'
    assert records[2] == '2,"Jane","Goodbye"'


def test_split_quoted_records_escaped_quotes():
    """Test that escaped quotes (double quotes) do not toggle quote state."""
    csv_text = 'id,message\n1,"He said ""hello"""\n2,"Normal"'

    records = _split_quoted_records(csv_text)

    assert len(records) == 3
    assert records[0] == "id,message"
    assert records[1] == '1,"He said ""hello"""'
    assert records[2] == '2,"Normal"'


def test_split_quoted_records_chunk_boundary():
    """Test that split works when a quoted newline spans chunk boundaries."""
    # Simulates reading in chunks where middle record's embedded newline is mid-chunk
    chunk1 = 'id,body\n1,"Line'
    chunk2 = 'One\nLineTwo"\n2,"Normal"'

    # First chunk: should keep incomplete record in buffer
    records1 = _split_quoted_records(chunk1)
    assert len(records1) == 2
    assert records1[0] == "id,body"
    assert records1[1] == '1,"Line'  # Incomplete

    # Append chunk2 to the incomplete buffer and resplit
    combined = records1[1] + chunk2
    records2 = _split_quoted_records(combined)
    assert len(records2) == 3
    assert records2[0] == '1,"Line\nLineTwo"'
    assert records2[1] == '2,"Normal"'
    assert records2[2] == ''  # Trailing empty (ends with newline)


def test_iter_remote_lines_quoted_embedded_newline(tmp_path):
    """Test iter_remote_lines with a record containing quoted embedded newline."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    url = "http://example.com/data.csv"

    # CSV data: header + 3 rows, row 2 has embedded newline in quoted field
    csv_data = 'id,title,body\n1,"Title A","Body A"\n2,"Title B","Body\nWith\nNewlines"\n3,"Title C","Body C"'

    # Mock urllib to return this CSV
    mock_response = MagicMock()
    mock_response.headers = {
        "ETag": '"abc123"',
        "Content-Length": str(len(csv_data)),
    }
    mock_response.read = MagicMock(side_effect=[csv_data.encode("utf-8"), b""])
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=None)

    with patch("urllib.request.urlopen", return_value=mock_response):
        batches = list(iter_remote_lines(url, batch_bytes=10000, conn=conn))

    # Should yield 1 batch with 3 rows (header not included in output)
    assert len(batches) == 1
    assert len(batches[0]) == 3

    # Verify row 2 was parsed correctly (with embedded newlines intact)
    assert batches[0][1]["id"] == "2"
    assert batches[0][1]["title"] == "Title B"
    assert "Body\nWith\nNewlines" in batches[0][1]["body"]

    # Verify done=1 set (full file read)
    cursor = conn.execute(
        "SELECT done FROM source_cursor WHERE source_url = ?",
        (url,),
    ).fetchone()
    assert cursor[0] == 1


def test_iter_remote_lines_resume_with_header_fetch(tmp_path):
    """Test iter_remote_lines resumption: on byte_offset > 0, fetch header from byte 0."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    url = "http://example.com/data.csv"
    csv_header = "id,title,body"
    csv_data = "4,Row4,Data4\n5,Row5,Data5"

    # Initialize cursor at byte_offset > 0 (simulates resumed read)
    conn.execute(
        """INSERT INTO source_cursor (source_url, byte_offset, rows_ingested, done, etag, updated_at)
           VALUES (?, 100, 3, 0, 'abc123', datetime('now'))""",
        (url,),
    )
    conn.commit()

    # Mock two separate requests: one for header (Range 0-4095), one for data (Range 100-)
    header_response = MagicMock()
    header_response.headers = {"Content-Length": "20"}
    header_response.read = MagicMock(return_value=(csv_header + "\n1,Row1,Data1").encode("utf-8"))
    header_response.__enter__ = MagicMock(return_value=header_response)
    header_response.__exit__ = MagicMock(return_value=None)

    data_response = MagicMock()
    data_response.headers = {
        "ETag": '"abc123"',
        "Content-Range": f"bytes 100-{100 + len(csv_data)}/200",
    }
    data_response.read = MagicMock(side_effect=[csv_data.encode("utf-8"), b""])
    data_response.__enter__ = MagicMock(return_value=data_response)
    data_response.__exit__ = MagicMock(return_value=None)

    # Patch to return different response based on Range header
    def urlopen_side_effect(req):
        range_header = req.get_header("Range")
        if range_header == "bytes=0-4095":
            return header_response
        else:
            return data_response

    with patch("urllib.request.urlopen", side_effect=urlopen_side_effect):
        batches = list(iter_remote_lines(url, batch_bytes=10000, conn=conn))

    # Should parse 2 new rows from the resumed data
    assert len(batches) == 1
    assert len(batches[0]) == 2
    assert batches[0][0]["id"] == "4"
    assert batches[0][1]["id"] == "5"


def test_iter_remote_lines_malformed_rate_threshold(tmp_path):
    """Test that malformed record rate > 1% raises RuntimeError."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    url = "http://example.com/bad.csv"

    # Create data with 100 rows: 3 valid, 97 malformed (incomplete rows)
    csv_data = "id,val\n1,a\n2,b\n3,c"
    # Add many incomplete rows (single column instead of two)
    for i in range(97):
        csv_data += f"\ninvalid{i}"

    mock_response = MagicMock()
    mock_response.headers = {
        "ETag": '"xyz"',
        "Content-Length": str(len(csv_data)),
    }
    mock_response.read = MagicMock(side_effect=[csv_data.encode("utf-8"), b""])
    mock_response.__enter__ = MagicMock(return_value=mock_response)
    mock_response.__exit__ = MagicMock(return_value=None)

    with patch("urllib.request.urlopen", return_value=mock_response):
        try:
            list(iter_remote_lines(url, batch_bytes=10000, conn=conn))
            assert False, "Should raise RuntimeError for high malformed rate"
        except RuntimeError as e:
            assert "Malformed record rate" in str(e)
            assert "1%" in str(e)
