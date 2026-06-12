"""Stream UCI News Aggregator dataset with story-based event clustering."""

import re
import sqlite3
from typing import Dict, Optional, Set
from datetime import datetime

from stapled.ingest.stream import iter_remote_lines
from stapled.ingest.fakenewsnet import normalize_domain, PLATFORM_DOMAINS
from stapled.ingest.csv_loader import _get_or_create_outlet
from stapled.db import insert_and_get_id


# UCI dataset URL
UCI_URL = "https://media.githubusercontent.com/media/PacktPublishing/Apache-Spark-2-Data-Processing-and-Real-Time-Analytics/master/newsCorpora.csv"

# UCI field names (TAB-delimited, no header)
UCI_FIELDNAMES = ["ID", "TITLE", "URL", "PUBLISHER", "CATEGORY", "STORY", "HOSTNAME", "TIMESTAMP"]


def load_uci(
    conn: sqlite3.Connection,
    batch_bytes: int = 524288,
    limit: Optional[int] = None,
    categories: Optional[Set[str]] = None,
) -> Dict[str, int]:
    """
    Stream UCI News Aggregator dataset via iter_remote_lines.
    Load articles, map stories to events, extract claims with negation detection.

    Args:
        conn: Database connection
        batch_bytes: Batch size (bytes) for streaming
        limit: Max rows (None = no limit)
        categories: Filter to specific categories (None = all)

    Returns:
        Dict with counts: {articles_loaded, outlets_created, events_created, labels_written, skipped}
    """
    counts = {
        "articles_loaded": 0,
        "outlets_created": 0,
        "events_created": 0,
        "labels_written": 0,
        "skipped": 0,
    }

    # Track story_id → event_id mapping in memory during batch
    story_to_event: Dict[str, int] = {}
    rows_processed = 0

    # Check existing story mappings
    cursor = conn.execute("SELECT story_id, event_id FROM uci_story")
    for story_id, event_id in cursor.fetchall():
        story_to_event[story_id] = event_id

    seen_domains = set(
        r[0] for r in conn.execute("SELECT name FROM outlet").fetchall()
    )
    for batch_rows in iter_remote_lines(
        UCI_URL,
        batch_bytes,
        conn,
        delimiter="\t",
        fieldnames=UCI_FIELDNAMES,
        quoting=False,
    ):
        if limit and rows_processed >= limit:
            break

        for row in batch_rows:
            if limit and rows_processed >= limit:
                break

            # Extract fields
            title = (row.get("TITLE") or "").strip()
            url = (row.get("URL") or "").strip()
            hostname = (row.get("HOSTNAME") or "").strip()
            story_id = (row.get("STORY") or "").strip()
            category = (row.get("CATEGORY") or "").strip()
            timestamp_ms = (row.get("TIMESTAMP") or "").strip()

            # Skip if missing critical fields
            if not title or not hostname or not story_id:
                counts["skipped"] += 1
                continue

            # Normalize domain
            domain = normalize_domain(hostname)
            if not domain or domain in PLATFORM_DOMAINS:
                counts["skipped"] += 1
                continue

            # Filter by categories if specified
            if categories and category not in categories:
                counts["skipped"] += 1
                continue

            # Get or create outlet
            outlet_id = _get_or_create_outlet(conn, domain, feed_url=None, is_synthetic=0)
            if domain not in seen_domains:
                seen_domains.add(domain)
                counts["outlets_created"] += 1

            # Event handling: get or create event for story_id
            if story_id not in story_to_event:
                # Truncate title to 80 chars for event label
                event_label = title[:80]
                try:
                    event_id = insert_and_get_id(
                        conn,
                        "INSERT INTO event (corpus_id, label) VALUES (NULL, ?)",
                        (event_label,),
                    )
                    conn.execute(
                        "INSERT INTO uci_story (story_id, event_id) VALUES (?, ?)",
                        (story_id, event_id),
                    )
                    story_to_event[story_id] = event_id
                    counts["events_created"] += 1
                except sqlite3.IntegrityError:
                    # Fallback: retrieve by story_id
                    cursor = conn.execute(
                        "SELECT event_id FROM uci_story WHERE story_id = ?",
                        (story_id,),
                    )
                    res = cursor.fetchone()
                    if res:
                        event_id = res[0]
                        story_to_event[story_id] = event_id
                    else:
                        counts["skipped"] += 1
                        continue
            else:
                event_id = story_to_event[story_id]

            # Parse timestamp (milliseconds epoch → ISO-8601)
            published_at = None
            if timestamp_ms:
                try:
                    ts_sec = int(timestamp_ms) / 1000.0
                    published_at = datetime.utcfromtimestamp(ts_sec).isoformat()
                except (ValueError, OSError):
                    pass

            # Insert article
            try:
                article_id = insert_and_get_id(
                    conn,
                    """INSERT INTO article
                       (outlet_id, corpus_id, url, title, body, published_at, ingest_status)
                       VALUES (?, NULL, ?, ?, ?, ?, 'ok')""",
                    (outlet_id, url, title, title, published_at),
                )

                # Extract claim: actor + action + object
                actor = _extract_actor(title)
                action = _extract_action(title)
                obj = _extract_object(title)

                # Insert claim
                try:
                    conn.execute(
                        """INSERT INTO claim
                           (article_id, event_id, actor, action, object, certainty, extraction_score)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (article_id, event_id, actor, action, obj, 0.7, 0.5),
                    )
                except sqlite3.IntegrityError:
                    pass

                # Insert label
                conn.execute(
                    """INSERT INTO article_label (article_id, dataset, label)
                       VALUES (?, ?, ?)""",
                    (article_id, f"uci_{category}", category),
                )

                counts["articles_loaded"] += 1
                counts["labels_written"] += 1

            except sqlite3.IntegrityError:
                # URL collision - skip
                counts["skipped"] += 1
                continue

            rows_processed += 1

        conn.commit()

    return counts


def _extract_actor(title: str) -> Optional[str]:
    """Extract first capitalized word span as actor."""
    words = title.split()
    for word in words:
        # First word with initial capital is the actor
        if word and word[0].isupper():
            return word.capitalize()
    return None


def _extract_action(title: str) -> str:
    """
    Determine action: if title matches negation pattern → 'not-occurred' else 'occurred'.
    Negation pattern: \b(not|no|denies|denied|refutes|debunk|false|fake|hoax)\b (case-insensitive).
    """
    negation_pattern = r"\b(not|no|denies|denied|refutes|debunk|false|fake|hoax)\b"
    if re.search(negation_pattern, title, re.IGNORECASE):
        return "not-occurred"
    return "occurred"


def _extract_object(title: str) -> str:
    """Extract title remainder truncated to 120 chars as object."""
    # Skip first word (actor), return the rest truncated
    words = title.split(maxsplit=1)
    remainder = words[1] if len(words) > 1 else title
    return remainder[:120]
