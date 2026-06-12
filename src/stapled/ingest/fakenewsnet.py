"""Stream FakeNewsNet dataset with held-out labels and outlet metadata."""

import sqlite3
import urllib.request
import urllib.parse
from typing import Dict, Optional, List

from stapled.ingest.stream import iter_remote_lines
from stapled.ingest.csv_loader import _get_or_create_outlet
from stapled.db import insert_and_get_id


# FakeNewsNet sources: (dataset, label, url)
FNN_SOURCES = [
    (
        "politifact_real",
        "real",
        "https://raw.githubusercontent.com/KaiDMML/FakeNewsNet/master/dataset/politifact_real.csv",
    ),
    (
        "politifact_fake",
        "fake",
        "https://raw.githubusercontent.com/KaiDMML/FakeNewsNet/master/dataset/politifact_fake.csv",
    ),
    (
        "gossipcop_real",
        "real",
        "https://raw.githubusercontent.com/KaiDMML/FakeNewsNet/master/dataset/gossipcop_real.csv",
    ),
    (
        "gossipcop_fake",
        "fake",
        "https://raw.githubusercontent.com/KaiDMML/FakeNewsNet/master/dataset/gossipcop_fake.csv",
    ),
]


def normalize_domain(url: str) -> Optional[str]:
    """
    Normalize a URL to a domain name.
    - Add scheme if missing
    - Extract netloc
    - Remove leading 'www.', 'm.', 'amp.' subdomains
    - Remove port
    - Return None if empty/invalid or no dot
    """
    if not url or not isinstance(url, str):
        return None

    url = url.strip().lower()

    # Add scheme if missing
    if not url.startswith(("http://", "https://")):
        url = "https://" + url

    try:
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc
    except Exception:
        return None

    if not domain:
        return None

    # Remove port
    if ":" in domain:
        domain = domain.split(":")[0]

    # Remove leading subdomains (www., m., amp.)
    for prefix in ["www.", "m.", "amp."]:
        if domain.startswith(prefix):
            domain = domain[len(prefix) :]

    # Ensure at least one dot (not a bare hostname)
    if "." not in domain:
        return None

    return domain if domain else None


def load_fakenewsnet(
    conn: sqlite3.Connection,
    batch_bytes: int = 262144,
    limit: Optional[int] = None,
    datasets: Optional[List[str]] = None,
) -> Dict[str, int]:
    """
    Stream FakeNewsNet sources via iter_remote_lines. Load articles + labels.

    Args:
        conn: Database connection
        batch_bytes: Batch size (bytes) for streaming
        limit: Max rows per source (None = no limit)
        datasets: Filter to specific datasets (None = all)

    Returns:
        Dict with counts: {articles_loaded, outlets_created, labels_written, per_dataset: {...}}
    """
    counts = {
        "articles_loaded": 0,
        "outlets_created": 0,
        "labels_written": 0,
        "per_dataset": {},
    }

    # Filter sources if datasets specified
    sources = FNN_SOURCES
    if datasets:
        datasets_set = set(datasets)
        sources = [(d, lbl, u) for d, lbl, u in FNN_SOURCES if d in datasets_set]

    for dataset, label, url in sources:
        rows_loaded = 0
        outlets_created_for_source = 0

        counts["per_dataset"][dataset] = {
            "articles": 0,
            "outlets": 0,
            "labels": 0,
        }

        for batch_rows in iter_remote_lines(url, batch_bytes, conn):
            if limit and rows_loaded >= limit:
                break

            for row in batch_rows:
                if limit and rows_loaded >= limit:
                    break

                # Extract fields
                title = (row.get("title") or "").strip()
                news_url = (row.get("news_url") or "").strip()

                # Skip if missing critical fields
                if not title or not news_url:
                    continue

                # Normalize domain
                domain = normalize_domain(news_url)
                if not domain:
                    continue

                # Get or create outlet
                outlet_id = _get_or_create_outlet(conn, domain, feed_url=None, is_synthetic=0)

                # Track newly created outlets
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM outlet WHERE name = ? AND id = ?",
                    (domain, outlet_id),
                )
                if cursor.fetchone()[0] > 0:
                    # Check if this is the first time we've seen this outlet in this batch
                    if domain not in [row.get("_outlet_domain") for row in batch_rows]:
                        outlets_created_for_source += 1
                        counts["per_dataset"][dataset]["outlets"] += 1

                # Insert article (body = title since FNN has no body text)
                try:
                    article_id = insert_and_get_id(
                        conn,
                        """INSERT INTO article
                           (outlet_id, corpus_id, url, title, body, ingest_status)
                           VALUES (?, NULL, ?, ?, ?, 'ok')""",
                        (outlet_id, news_url, title, title),
                    )

                    # Insert label
                    conn.execute(
                        """INSERT INTO article_label (article_id, dataset, label)
                           VALUES (?, ?, ?)""",
                        (article_id, dataset, label),
                    )

                    counts["articles_loaded"] += 1
                    counts["labels_written"] += 1
                    counts["per_dataset"][dataset]["articles"] += 1
                    counts["per_dataset"][dataset]["labels"] += 1

                except sqlite3.IntegrityError:
                    # URL collision or constraint violation - skip
                    continue

                rows_loaded += 1

            conn.commit()

        counts["outlets_created"] += outlets_created_for_source

    return counts


def load_external_labels(
    conn: sqlite3.Connection,
    url: str = "https://raw.githubusercontent.com/ramybaly/News-Media-Reliability/master/data/acl2020/corpus.tsv",
) -> int:
    """
    Fetch MBFC outlet labels (TSV) and upsert into outlet_external_label table.

    CSV columns: source_url, source_url_normalized, ref, fact, bias
    Upsert: (domain, fact, bias, source='mbfc_acl2020')

    Args:
        conn: Database connection
        url: Remote TSV URL

    Returns:
        Row count inserted/updated
    """
    import csv

    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as response:
            content = response.read().decode("utf-8", errors="replace")
    except Exception as e:
        raise RuntimeError(f"Failed to fetch {url}: {e}") from e

    # Parse TSV
    lines = content.strip().split("\n")
    if len(lines) < 2:
        return 0

    reader = csv.DictReader(lines, delimiter="\t")
    count = 0

    for row in reader:
        domain_raw = (row.get("source_url_normalized") or "").strip().lower()
        fact = (row.get("fact") or "").strip()
        bias = (row.get("bias") or "").strip()

        if not domain_raw:
            continue

        # Strip www. prefix
        if domain_raw.startswith("www."):
            domain_raw = domain_raw[4:]

        conn.execute(
            """INSERT OR REPLACE INTO outlet_external_label
               (domain, fact, bias, source)
               VALUES (?, ?, ?, 'mbfc_acl2020')""",
            (domain_raw, fact, bias),
        )
        count += 1

    conn.commit()
    return count
