"""Load ISOT dataset (True.csv and Fake.csv) into database."""

import csv
import re
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict

from stapled.db import insert_and_get_id


def load_isot(
    conn: sqlite3.Connection,
    true_csv: str,
    fake_csv: str,
    limit_per_outlet: Optional[int] = None,
) -> Dict[str, int]:
    """
    Load ISOT dataset: True.csv (Reuters) and Fake.csv (misinformation).
    Returns dict with counts: {articles_loaded, articles_skipped, outlets_created}.
    """
    counts = {
        "articles_loaded": 0,
        "articles_skipped": 0,
        "outlets_created": 0,
    }

    # Create reuters outlet
    reuters_id = _get_or_create_outlet(
        conn, "reuters", feed_url=None, is_synthetic=0
    )
    counts["outlets_created"] += 1

    # Load True.csv (Reuters)
    counts = _load_true_csv(
        conn, true_csv, reuters_id, limit_per_outlet, counts
    )

    # Load Fake.csv (fake outlets)
    counts = _load_fake_csv(
        conn, fake_csv, limit_per_outlet, counts
    )

    conn.commit()
    return counts


def _get_or_create_outlet(
    conn: sqlite3.Connection,
    name: str,
    feed_url: Optional[str] = None,
    is_synthetic: int = 0,
) -> int:
    """Get existing outlet or create new one. Returns outlet_id."""
    cursor = conn.execute(
        "SELECT id FROM outlet WHERE name = ?", (name,)
    )
    row = cursor.fetchone()
    if row:
        return row[0]

    outlet_id = insert_and_get_id(
        conn,
        "INSERT INTO outlet (name, feed_url, is_synthetic) VALUES (?, ?, ?)",
        (name, feed_url, is_synthetic),
    )
    return outlet_id


def _load_true_csv(
    conn: sqlite3.Connection,
    csv_path: str,
    outlet_id: int,
    limit_per_outlet: Optional[int],
    counts: Dict[str, int],
) -> Dict[str, int]:
    """Load True.csv rows. Strip Reuters dateline from text."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"True.csv not found: {csv_path}")

    count = 0
    with open(path) as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            if limit_per_outlet and count >= limit_per_outlet:
                break

            title = (row.get("title") or "").strip()
            text = (row.get("text") or "").strip()
            date_str = (row.get("date") or "").strip()

            # Skip short/empty text
            if not text or len(text) < 200:
                counts["articles_skipped"] += 1
                continue

            # Parse date
            published_at = _parse_date(date_str)

            # Strip Reuters dateline from text
            text = _strip_reuters_dateline(text)

            # Create URL: isot://true/<row_idx>
            url = f"isot://true/{idx}"

            # Insert article
            try:
                insert_and_get_id(
                    conn,
                    """INSERT INTO article
                       (outlet_id, corpus_id, url, published_at, title, body,
                        dedup_cluster_id, ingest_status, skip_reason)
                       VALUES (?, NULL, ?, ?, ?, ?, NULL, 'ok', NULL)""",
                    (outlet_id, url, published_at, title, text),
                )
                count += 1
                counts["articles_loaded"] += 1
            except sqlite3.IntegrityError:
                # URL collision (should be rare with isot:// scheme)
                counts["articles_skipped"] += 1

    return counts


def _load_fake_csv(
    conn: sqlite3.Connection,
    csv_path: str,
    limit_per_outlet: Optional[int],
    counts: Dict[str, int],
) -> Dict[str, int]:
    """Load Fake.csv rows. Group by subject -> pseudo-outlet fake:<subject>."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Fake.csv not found: {csv_path}")

    # Track per-subject counts
    subject_counts: Dict[str, int] = {}

    with open(path) as f:
        reader = csv.DictReader(f)
        for idx, row in enumerate(reader):
            title = (row.get("title") or "").strip()
            text = (row.get("text") or "").strip()
            subject = (row.get("subject") or "").strip()
            date_str = (row.get("date") or "").strip()

            # Skip short/empty text
            if not text or len(text) < 200:
                counts["articles_skipped"] += 1
                continue

            # Normalize subject to outlet name: fake:<subject-lowercased-with-dashes>
            outlet_name = _normalize_subject(subject)
            outlet_id = _get_or_create_outlet(
                conn, outlet_name, feed_url=None, is_synthetic=0
            )

            # Track per-subject count
            if outlet_name not in subject_counts:
                subject_counts[outlet_name] = 0
                counts["outlets_created"] += 1

            if limit_per_outlet and subject_counts[outlet_name] >= limit_per_outlet:
                continue

            # Parse date
            published_at = _parse_date(date_str)

            # Create URL: isot://fake/<subject>/<row_idx>
            url = f"isot://fake/{subject}/{idx}"

            # Insert article
            try:
                insert_and_get_id(
                    conn,
                    """INSERT INTO article
                       (outlet_id, corpus_id, url, published_at, title, body,
                        dedup_cluster_id, ingest_status, skip_reason)
                       VALUES (?, NULL, ?, ?, ?, ?, NULL, 'ok', NULL)""",
                    (outlet_id, url, published_at, title, text),
                )
                subject_counts[outlet_name] += 1
                counts["articles_loaded"] += 1
            except sqlite3.IntegrityError:
                counts["articles_skipped"] += 1

    return counts


def _parse_date(date_str: str) -> Optional[str]:
    """Parse date string in various formats. Return ISO-8601 string or NULL."""
    if not date_str or not date_str.strip():
        return None

    # Try common formats
    formats = [
        "%B %d, %Y",  # "December 31, 2017"
        "%B %d %Y",  # "December 31 2017"
        "%b %d, %Y",  # "Dec 31, 2017"
        "%b %d %Y",  # "Dec 31 2017"
        "%Y-%m-%d",  # "2017-12-31"
        "%m/%d/%Y",  # "12/31/2017"
        "%d-%m-%Y",  # "31-12-2017"
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            return dt.isoformat()
        except ValueError:
            continue

    return None


def _strip_reuters_dateline(text: str) -> str:
    """Strip leading 'CITY[, STATE]* (Reuters) - ' from article text."""
    # Pattern: WORD[, WORD]* (Reuters) - rest
    pattern = r"^[A-Z][A-Z\s,]*\(Reuters\)\s*-\s*"
    return re.sub(pattern, "", text, count=1)


def _normalize_subject(subject: str) -> str:
    """Normalize subject to outlet name: 'fake:<subject-lowercased-with-dashes>'."""
    # Lowercase and replace spaces/underscores with dashes
    normalized = subject.lower().strip()
    normalized = re.sub(r"[\s_]+", "-", normalized)
    # Remove non-alphanumeric except dashes
    normalized = re.sub(r"[^a-z0-9\-]", "", normalized)
    return f"fake:{normalized}"
