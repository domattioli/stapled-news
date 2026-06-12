"""Streaming remote CSV ingestion with cursor resumption."""

import sqlite3
import urllib.request
import urllib.error
import csv
import io
from datetime import datetime
from typing import List, Dict, Generator, Optional


def iter_remote_lines(
    url: str, batch_bytes: int, conn: sqlite3.Connection,
    malformed_threshold: float = 0.01,
) -> Generator[List[Dict[str, str]], None, None]:
    """
    Resume from source_cursor using etag + Range header (HTTP 206).
    Yield lists of CSV rows (dicts), batch_bytes ≈ bytes yielded before yield.
    Quote-aware record splitting: records are split on newlines that fall OUTSIDE quotes.
    On completion, set done=1 in source_cursor.

    Args:
        url: Remote CSV URL
        batch_bytes: Target batch size in bytes
        conn: Database connection

    Yields:
        Lists of CSV row dicts
    """
    # Load or create cursor
    cursor = conn.execute(
        "SELECT id, byte_offset, etag, rows_ingested, done FROM source_cursor WHERE source_url = ?",
        (url,),
    )
    row = cursor.fetchone()

    if row:
        cursor_id, byte_offset, etag, rows_ingested, done = row
        if done:
            return  # Already fully ingested
    else:
        cursor_id = _init_cursor(conn, url)
        byte_offset = 0
        rows_ingested = 0

    headers = None

    # On resume (byte_offset > 0), fetch header from byte 0 to initialize headers
    if byte_offset > 0:
        try:
            header_req = urllib.request.Request(url)
            header_req.add_header("Range", "bytes=0-4095")
            with urllib.request.urlopen(header_req) as header_response:
                header_chunk = header_response.read().decode("utf-8", errors="replace")
                # Extract first line as header
                header_line = header_chunk.split("\n")[0]
                if header_line:
                    try:
                        headers = [h.strip() for h in next(csv.reader(io.StringIO(header_line)))]
                    except Exception:
                        pass
        except Exception:
            pass  # If we fail to get header, it will be loaded from the resumed request if at record boundary

    # Fetch remote file
    req = urllib.request.Request(url)
    if byte_offset > 0:
        req.add_header("Range", f"bytes={byte_offset}-")

    try:
        with urllib.request.urlopen(req) as response:
            # Get etag from headers
            new_etag = response.headers.get("ETag")

            # Determine total file size from Content-Range or Content-Length
            total_size = None
            content_range = response.headers.get("Content-Range")
            if content_range:
                # Format: "bytes START-END/TOTAL"
                try:
                    total_size = int(content_range.split("/")[-1])
                except (ValueError, IndexError):
                    pass
            if total_size is None:
                content_length = response.headers.get("Content-Length")
                if content_length:
                    try:
                        total_size = byte_offset + int(content_length)
                    except ValueError:
                        pass

            # Read response in chunks, using quote-aware record splitting
            buffer = ""
            batch_rows = []
            batch_byte_count = 0
            consumed_bytes = 0  # Track exact UTF-8 bytes consumed from all complete records
            malformed_count = 0
            total_records = 0

            for chunk in iter(lambda: response.read(8192), b""):
                buffer += chunk.decode("utf-8", errors="replace")

                # Split on newlines that fall OUTSIDE quotes (RFC 4180 aware)
                records = _split_quoted_records(buffer)
                buffer = records[-1]  # Last element is incomplete record
                complete_records = records[:-1]

                for record_text in complete_records:
                    record_bytes = len(record_text.encode("utf-8")) + 1  # +1 for newline

                    # At offset==0, first record is header
                    if headers is None and byte_offset == 0 and consumed_bytes == 0:
                        try:
                            row = next(csv.reader(io.StringIO(record_text)))
                            headers = [h.strip() for h in row]
                            consumed_bytes += record_bytes
                            continue
                        except Exception:
                            pass

                    # Parse data row
                    if headers is not None:
                        try:
                            row = next(csv.reader(io.StringIO(record_text)))
                            values = [v.strip() for v in row]
                            if len(values) == len(headers):
                                row_dict = dict(zip(headers, values))
                                batch_rows.append(row_dict)
                                batch_byte_count += record_bytes
                                rows_ingested += 1
                                total_records += 1
                            else:
                                malformed_count += 1
                        except Exception:
                            malformed_count += 1

                    consumed_bytes += record_bytes

                    # Yield batch if size exceeded
                    if batch_byte_count >= batch_bytes and batch_rows:
                        yield batch_rows
                        byte_offset += consumed_bytes
                        _update_cursor(conn, cursor_id, byte_offset, new_etag, rows_ingested)
                        batch_rows = []
                        batch_byte_count = 0
                        consumed_bytes = 0

            # Handle final incomplete record (file without trailing newline)
            if buffer:
                consumed_bytes += len(buffer.encode("utf-8"))
            if buffer.strip() and headers is not None:
                try:
                    row = next(csv.reader(io.StringIO(buffer)))
                    values = [v.strip() for v in row]
                    if len(values) == len(headers):
                        row_dict = dict(zip(headers, values))
                        batch_rows.append(row_dict)
                        rows_ingested += 1
                        total_records += 1
                    else:
                        malformed_count += 1
                except Exception:
                    malformed_count += 1

            # Yield remaining batch; always advance cursor past consumed tail bytes
            if batch_rows:
                yield batch_rows
            if consumed_bytes:
                byte_offset += consumed_bytes
                _update_cursor(conn, cursor_id, byte_offset, new_etag, rows_ingested)

            # Check malformed rate before marking done
            if total_records > 0:
                malformed_rate = malformed_count / total_records
                if malformed_rate > malformed_threshold:
                    raise RuntimeError(
                        f"Malformed record rate {malformed_rate:.2%} exceeds "
                        f"{malformed_threshold:.0%} threshold "
                        f"({malformed_count} malformed of {total_records} total records)"
                    )

            # Mark as done only if we've read all bytes
            is_complete = total_size is None or byte_offset >= total_size
            if is_complete:
                conn.execute(
                    "UPDATE source_cursor SET done=1, updated_at=? WHERE id=?",
                    (datetime.utcnow().isoformat(), cursor_id),
                )
                conn.commit()

    except urllib.error.HTTPError as e:
        if e.code == 416:
            # Range not satisfiable; file is done
            conn.execute(
                "UPDATE source_cursor SET done=1, updated_at=? WHERE id=?",
                (datetime.utcnow().isoformat(), cursor_id),
            )
            conn.commit()
        else:
            raise


def _split_quoted_records(text: str) -> List[str]:
    """
    Split CSV text on newlines that fall OUTSIDE quotes (RFC 4180).
    Track quote parity: toggle in_quotes on '"' (but '""' inside quotes = two toggles → net unchanged).

    Returns list where last element is the incomplete trailing record.
    """
    records = []
    current = ""
    in_quotes = False
    i = 0

    while i < len(text):
        char = text[i]

        if char == '"':
            # Check for escaped quote ('""')
            if in_quotes and i + 1 < len(text) and text[i + 1] == '"':
                current += '""'
                i += 2
                continue
            else:
                in_quotes = not in_quotes
                current += char
        elif char == '\n' and not in_quotes:
            # Record boundary
            records.append(current)
            current = ""
        else:
            current += char

        i += 1

    # Append incomplete final record
    records.append(current)
    return records


def dedup_new_articles(conn: sqlite3.Connection, article_ids: List[int]) -> None:
    """
    Insert article_ids into simhash_bucket (4 bands × 16-bit buckets).
    Do NOT re-cluster; just bucket the new IDs for incremental joins later.

    Args:
        conn: Database connection
        article_ids: List of article IDs to bucket
    """
    from stapled.ingest.dedup import _simhash, _get_band_bits

    cursor = conn.execute(
        "SELECT id, body FROM article WHERE id IN ({})".format(
            ",".join("?" * len(article_ids))
        ),
        article_ids,
    )
    articles = cursor.fetchall()

    for article_id, body in articles:
        h = _simhash(body)
        for band in range(4):
            bucket_bits = _get_band_bits(h, band)
            conn.execute(
                """INSERT OR IGNORE INTO simhash_bucket (band, bucketkey, article_id)
                   VALUES (?, ?, ?)""",
                (band, bucket_bits, article_id),
            )

    conn.commit()


def _init_cursor(conn: sqlite3.Connection, url: str) -> int:
    """Create new cursor row. Returns cursor_id."""
    cursor = conn.execute(
        """INSERT INTO source_cursor (source_url, byte_offset, rows_ingested, done, updated_at)
           VALUES (?, 0, 0, 0, ?)""",
        (url, datetime.utcnow().isoformat()),
    )
    conn.commit()
    return cursor.lastrowid


def _update_cursor(
    conn: sqlite3.Connection, cursor_id: int, byte_offset: int, etag: Optional[str], rows_ingested: int
) -> None:
    """Update cursor with byte_offset, etag, rows_ingested."""
    conn.execute(
        """UPDATE source_cursor SET byte_offset=?, etag=?, rows_ingested=?, updated_at=?
           WHERE id=?""",
        (byte_offset, etag, rows_ingested, datetime.utcnow().isoformat(), cursor_id),
    )
    conn.commit()
