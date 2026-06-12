"""Load US headlines CSV corpus with domain normalization and claim synthesis."""

import re
import csv
import gzip
import sqlite3
from typing import Dict, Optional
from datetime import datetime

from stapled.ingest.fakenewsnet import normalize_domain
from stapled.ingest.csv_loader import _get_or_create_outlet
from stapled.db import insert_and_get_id


# English negation regex for action classification
ENGLISH_NEGATION = re.compile(
    r"\b(not|no|denies|denied|refutes|rejects|debunk(?:s|ed)?|false|fake|hoax|won't|cancels|cancelled)\b",
    re.I,
)


def _normalize_seendate(seendate_str: str) -> Optional[str]:
    """
    Parse seendate in various formats.
    - "20260612T140000Z" (ISO8601 basic format) → ISO8601 extended
    - ISO8601 already → return as-is
    - Unparseable → return raw string
    """
    if not seendate_str or not isinstance(seendate_str, str):
        return None

    seendate_str = seendate_str.strip()
    if not seendate_str:
        return None

    # Try ISO8601 basic format: 20260612T140000Z
    if len(seendate_str) >= 15 and seendate_str[8] == "T" and seendate_str.endswith("Z"):
        try:
            dt = datetime.strptime(seendate_str, "%Y%m%dT%H%M%SZ")
            return dt.isoformat() + "Z"
        except ValueError:
            pass

    # Try ISO8601 extended format (already in correct format)
    if "T" in seendate_str:
        try:
            dt = datetime.fromisoformat(seendate_str.replace("Z", "+00:00"))
            return dt.isoformat()
        except ValueError:
            pass

    # Unparseable: return raw string
    return seendate_str


def _extract_actor(title: str) -> Optional[str]:
    """Extract first capitalized multi-char token span as actor."""
    words = title.split()
    for word in words:
        # First word with initial capital and len > 1
        if len(word) > 1 and word[0].isupper():
            return word.capitalize()
    return None


def _extract_action(title: str) -> str:
    """Action: 'not-occurred' if English negation matches, else 'occurred'."""
    if ENGLISH_NEGATION.search(title):
        return "not-occurred"
    return "occurred"


def _extract_object(title: str) -> str:
    """Extract title remainder truncated to 120 chars."""
    words = title.split(maxsplit=1)
    remainder = words[1] if len(words) > 1 else title
    return remainder[:120]


def load_us_headlines(
    conn: sqlite3.Connection,
    path: str = "corpus/us/headlines.csv.gz",
    min_outlet_articles: int = 20,
) -> Dict[str, int]:
    """
    Load US headlines CSV corpus with domain normalization and claim synthesis.

    Args:
        conn: Database connection
        path: Path to CSV or CSV.gz file (default corpus/us/headlines.csv.gz)
        min_outlet_articles: Minimum articles per domain to keep (default 20)

    Returns:
        Dict with counts: {rows_read, articles_new, articles_existing, outlets_kept,
                          outlets_dropped, skipped}
    """
    counts = {
        "rows_read": 0,
        "articles_new": 0,
        "articles_existing": 0,
        "outlets_kept": 0,
        "outlets_dropped": 0,
        "skipped": 0,
    }

    # Determine if gzip or plain
    if path.endswith(".gz"):
        file_obj = gzip.open(path, "rt", encoding="utf-8", errors="replace")
    else:
        file_obj = open(path, "r", encoding="utf-8", errors="replace")

    try:
        reader = csv.DictReader(file_obj)

        # Pass 1: collect rows and count per-domain
        rows = []
        domain_counts: Dict[str, int] = {}

        for row in reader:
            counts["rows_read"] += 1

            domain_raw = (row.get("domain") or "").strip()
            url = (row.get("url") or "").strip()
            title = (row.get("title") or "").strip()
            seendate = (row.get("seendate") or "").strip()

            # Skip if no title
            if not title:
                counts["skipped"] += 1
                continue

            # Normalize domain via normalize_domain (works on URLs too)
            domain = normalize_domain(domain_raw or url)

            # Skip if domain is None (platform or invalid)
            if not domain:
                counts["skipped"] += 1
                continue

            # Count per domain
            if domain not in domain_counts:
                domain_counts[domain] = 0
            domain_counts[domain] += 1

            rows.append({
                "domain": domain,
                "title": title,
                "url": url or f"us-headlines://{domain}/{title[:50].replace(' ', '_')}",
                "seendate": seendate,
            })

        # Filter: keep only domains with >= min_outlet_articles
        domains_to_keep = {
            d for d, c in domain_counts.items() if c >= min_outlet_articles
        }
        counts["outlets_kept"] = len(domains_to_keep)
        counts["outlets_dropped"] = len(domain_counts) - len(domains_to_keep)

        # Pass 2: insert articles and claims for kept domains
        for row in rows:
            domain = row["domain"]
            if domain not in domains_to_keep:
                counts["skipped"] += 1
                continue

            title = row["title"]
            url = row["url"]
            seendate = row["seendate"]

            # Parse seendate
            published_at = _normalize_seendate(seendate)

            # Get or create outlet
            outlet_id = _get_or_create_outlet(conn, domain, feed_url=None, is_synthetic=0)

            # Check if article exists (by URL)
            cursor = conn.execute(
                "SELECT id FROM article WHERE url = ?", (url,)
            )
            existing = cursor.fetchone()

            if existing:
                # Existing article: update last_seen in fp_article_meta
                article_id = existing[0]
                try:
                    conn.execute(
                        "UPDATE fp_article_meta SET last_seen = ? WHERE url = ?",
                        (published_at, url),
                    )
                except sqlite3.Error:
                    pass
                counts["articles_existing"] += 1
            else:
                # New article: insert into article + fp_article_meta + claim
                try:
                    # Insert into fp_article_meta
                    conn.execute(
                        """INSERT INTO fp_article_meta
                           (url, outlet, section, first_seen, last_seen, title_variants)
                           VALUES (?, ?, ?, ?, ?, 1)""",
                        (url, domain, "us", published_at, published_at),
                    )

                    # Insert into article
                    article_id = insert_and_get_id(
                        conn,
                        """INSERT INTO article
                           (outlet_id, corpus_id, url, title, body, published_at, ingest_status)
                           VALUES (?, NULL, ?, ?, ?, ?, 'ok')""",
                        (outlet_id, url, title, title, published_at),
                    )

                    # Create claim via title synthesis
                    actor = _extract_actor(title)
                    action = _extract_action(title)
                    obj = _extract_object(title)

                    try:
                        conn.execute(
                            """INSERT INTO claim
                               (article_id, event_id, actor, action, object, certainty, extraction_score)
                               VALUES (?, NULL, ?, ?, ?, 0.7, 0.5)""",
                            (article_id, actor, action, obj),
                        )
                    except sqlite3.IntegrityError:
                        pass

                    counts["articles_new"] += 1

                except sqlite3.IntegrityError:
                    counts["skipped"] += 1
                    continue

        # Single commit at end
        conn.commit()

    finally:
        file_obj.close()

    return counts
