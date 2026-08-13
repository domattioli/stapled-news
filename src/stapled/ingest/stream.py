"""Streaming remote CSV ingestion with cursor resumption."""

import codecs
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
    delimiter: str = ",",
    fieldnames: Optional[List[str]] = None,
    quoting: bool = True,
) -> Generator[List[Dict[str, str]], None, None]:
    """
    Resume from source_cursor using etag + Range header (HTTP 206).
    Yield lists of CSV rows (dicts), batch_bytes ≈ bytes yielded before yield.
    Record splitting: if quoting=True, split on newlines OUTSIDE quotes (RFC 4180).
    If quoting=False, split on plain newlines (no quote logic).
    On completion, set done=1 in source_cursor.

    Args:
        url: Remote CSV URL
        batch_bytes: Target batch size in bytes
        conn: Database connection
        delimiter: Field delimiter (default ',')
        fieldnames: Pre-defined field names. If provided, skip header parsing.
        quoting: If True, use RFC 4180 quote-aware splitting. If False, use plain newline split.

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

    headers = fieldnames if fieldnames else None

    # On resume (byte_offset > 0), fetch header from byte 0 to initialize headers
    if byte_offset > 0 and fieldnames is None:
        try:
            header_req = urllib.request.Request(url)
            header_req.add_header("Range", "bytes=0-4095")
            with urllib.request.urlopen(header_req) as header_response:
                header_chunk = header_response.read().decode("utf-8", errors="replace")
                # Extract first line as header
                header_line = header_chunk.split("\n")[0]
                if header_line:
                    try:
                        reader = csv.reader(io.StringIO(header_line), delimiter=delimiter)
                        headers = [h.strip() for h in next(reader)]
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

            # Incremental decoder: carries any partial multi-byte UTF-8 sequence
            # across the 8192-byte read boundary instead of mangling it into
            # U+FFFD replacement chars (which would also drift consumed_bytes,
            # since it's derived by re-encoding the decoded text).
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

            for chunk in iter(lambda: response.read(8192), b""):
                buffer += decoder.decode(chunk)

                # Split records: quoted (RFC 4180) or plain newline split
                if quoting:
                    records = _split_quoted_records(buffer)
                else:
                    records = _split_plain_records(buffer)
                buffer = records[-1]  # Last element is incomplete record
                complete_records = records[:-1]

                for record_text in complete_records:
                    record_bytes = len(record_text.encode("utf-8")) + 1  # +1 for newline

                    # At offset==0, first record is header (only if fieldnames not provided)
                    if byte_offset == 0 and consumed_bytes == 0 and fieldnames is None:
                        try:
                            reader = csv.reader(io.StringIO(record_text), delimiter=delimiter)
                            row = next(reader)
                            headers = [h.strip() for h in row]
                            consumed_bytes += record_bytes
                            continue
                        except Exception:
                            pass

                    # Parse data row
                    if headers is not None:
                        try:
                            if quoting:
                                reader = csv.reader(io.StringIO(record_text), delimiter=delimiter)
                                row = next(reader)
                                values = [v.strip() for v in row]
                            else:
                                # Plain split: no quote logic
                                values = [v.strip() for v in record_text.split(delimiter)]
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

            # Flush any pending bytes trapped in the incremental decoder at EOF.
            buffer += decoder.decode(b"", final=True)

            # Handle final incomplete record (file without trailing newline)
            if buffer:
                consumed_bytes += len(buffer.encode("utf-8"))
            if buffer.strip() and headers is not None:
                try:
                    if quoting:
                        reader = csv.reader(io.StringIO(buffer), delimiter=delimiter)
                        row = next(reader)
                        values = [v.strip() for v in row]
                    else:
                        # Plain split: no quote logic
                        values = [v.strip() for v in buffer.split(delimiter)]
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


def _split_plain_records(text: str) -> List[str]:
    """
    Split unquoted records on plain newlines (no quote logic).
    For unquoted tab-separated data where titles may contain stray quotes.

    Returns list where last element is the incomplete trailing record.
    """
    records = text.split('\n')
    # Keep last element even if empty (mirrors _split_quoted_records contract)
    return records


def dedup_new_articles(conn: sqlite3.Connection, article_ids: List[int]) -> None:
    """
    Insert article_ids into simhash_bucket (4 bands × 16-bit buckets), then join
    each new article against whatever already shares a band bucket (Hamming
    distance <= 6) so streamed near-duplicates get dedup_cluster_id set
    incrementally, without re-clustering the whole table.

    Args:
        conn: Database connection
        article_ids: List of article IDs to bucket
    """
    from stapled.ingest.dedup import _simhash, _get_band_bits, _hamming_distance

    cursor = conn.execute(
        "SELECT id, body FROM article WHERE id IN ({})".format(
            ",".join("?" * len(article_ids))
        ),
        article_ids,
    )
    articles = cursor.fetchall()

    hashes = {}
    for article_id, body in articles:
        h = _simhash(body)
        hashes[article_id] = h
        for band in range(4):
            bucket_bits = _get_band_bits(h, band)
            conn.execute(
                """INSERT OR IGNORE INTO simhash_bucket (band, bucketkey, article_id)
                   VALUES (?, ?, ?)""",
                (band, bucket_bits, article_id),
            )

    conn.commit()

    if not hashes:
        return

    # Seed the cluster ID counter past whatever dedup_articles() has already
    # assigned, so incremental joins never collide with batch-assigned clusters.
    next_cluster_id = (
        conn.execute("SELECT COALESCE(MAX(dedup_cluster_id), 0) FROM article").fetchone()[0]
        + 1
    )

    for article_id, h in hashes.items():
        candidate_ids = set()
        for band in range(4):
            bucket_bits = _get_band_bits(h, band)
            rows = conn.execute(
                """SELECT article_id FROM simhash_bucket
                   WHERE band = ? AND bucketkey = ? AND article_id != ?""",
                (band, bucket_bits, article_id),
            ).fetchall()
            candidate_ids.update(r[0] for r in rows)

        if not candidate_ids:
            continue

        cand_rows = conn.execute(
            "SELECT id, body, dedup_cluster_id FROM article WHERE id IN ({})".format(
                ",".join("?" * len(candidate_ids))
            ),
            list(candidate_ids),
        ).fetchall()

        matched_clusters = set()
        matched_unclustered = []
        for cand_id, cand_body, cand_cluster in cand_rows:
            cand_hash = hashes.get(cand_id) or _simhash(cand_body)
            if _hamming_distance(h, cand_hash) <= 6:
                if cand_cluster is not None:
                    matched_clusters.add(cand_cluster)
                else:
                    matched_unclustered.append(cand_id)

        if not matched_clusters and not matched_unclustered:
            continue  # band collision only; not an actual near-duplicate

        if matched_clusters:
            target_cluster = min(matched_clusters)
            for other in matched_clusters - {target_cluster}:
                conn.execute(
                    "UPDATE article SET dedup_cluster_id = ? WHERE dedup_cluster_id = ?",
                    (target_cluster, other),
                )
        else:
            target_cluster = next_cluster_id
            next_cluster_id += 1

        conn.execute(
            "UPDATE article SET dedup_cluster_id = ? WHERE id = ?",
            (target_cluster, article_id),
        )
        for uid in matched_unclustered:
            conn.execute(
                "UPDATE article SET dedup_cluster_id = ? WHERE id = ?",
                (target_cluster, uid),
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
