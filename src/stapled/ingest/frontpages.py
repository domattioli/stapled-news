"""Load frontpage-archive-2026 German news corpus with outlet/section coverage."""

import re
import json
import hashlib
import sqlite3
import subprocess
from typing import Dict, Optional
from datetime import datetime
from fnmatch import fnmatch
from pathlib import Path

from stapled.ingest.csv_loader import _get_or_create_outlet
from stapled.db import insert_and_get_id


# Outlet → section glob patterns (political coverage only)
OUTLET_SECTIONS = {
    "bild.de": ["politik*", "ausland*"],
    "compact-online.de": ["aktuell", "index"],
    "faz.net": ["politik", "aktuell"],
    "fr.de": ["politik*"],
    "spiegel.de": ["politik", "ausland"],
    "sueddeutsche.de": ["politik"],
    "welt.de": ["politik"],
    "zeit.de": ["politik"],
    "gmx.net": ["news"],
    "volksstimme.de": ["deutschland-und-welt"],
}

# German negation regex (extended from UCI pattern)
GERMAN_NEGATION = re.compile(
    r"\b(nicht|kein|keine|keinen|dementiert|widerspricht|bestreitet|falsch|fake)\b",
    re.IGNORECASE,
)


def _normalize_url(url: str) -> str:
    """Strip query string and fragment from URL."""
    if not url:
        return ""
    # Remove fragment (#...)
    url = url.split("#")[0]
    # Remove query (?...)
    url = url.split("?")[0]
    return url.strip()


def _extract_actor(title: str) -> Optional[str]:
    """Extract first capitalized multi-char token span as actor."""
    words = title.split()
    for word in words:
        # First word with initial capital and len > 1
        if len(word) > 1 and word[0].isupper():
            return word.capitalize()
    return None


def _extract_action(title: str) -> str:
    """Action: 'not-occurred' if German negation matches, else 'occurred'."""
    if GERMAN_NEGATION.search(title):
        return "not-occurred"
    return "occurred"


def _extract_object(title: str) -> str:
    """Extract title remainder truncated to 120 chars."""
    words = title.split(maxsplit=1)
    remainder = words[1] if len(words) > 1 else title
    return remainder[:120]


def load_frontpages(
    conn: sqlite3.Connection,
    repo_path: str = "/tmp/fp2026",
    since: Optional[str] = None,
    until: Optional[str] = None,
    limit_commits: Optional[int] = None,
) -> Dict[str, int]:
    """
    Load frontpage-archive-2026 from local git clone.

    Args:
        conn: Database connection
        repo_path: Path to git clone (default /tmp/fp2026)
        since: ISO-8601 date filter (earliest commit date)
        until: ISO-8601 date filter (latest commit date)
        limit_commits: Max commits to process

    Returns:
        Dict with counts: {commits_processed, articles_new, articles_updated,
                          title_variant_updates, outlets, skipped}
    """
    counts = {
        "commits_processed": 0,
        "articles_new": 0,
        "articles_updated": 0,
        "title_variant_updates": 0,
        "outlets": 0,
        "skipped": 0,
    }

    repo_path = Path(repo_path)
    if not repo_path.exists():
        raise FileNotFoundError(f"Repo path not found: {repo_path}")

    # Get list of commits (OLDEST first)
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "log", "--format=%H|%cI", "origin/master"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            # Fallback to HEAD if origin/master missing
            result = subprocess.run(
                ["git", "-C", str(repo_path), "log", "--format=%H|%cI", "HEAD"],
                capture_output=True,
                text=True,
                check=True,
            )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"Failed to list commits: {e}")

    commits = result.stdout.strip().split("\n") if result.stdout.strip() else []
    commits = [c for c in commits if "|" in c]
    commits.reverse()  # Oldest first

    # Filter by since/until
    if since or until:
        since_dt = datetime.fromisoformat(since) if since else None
        until_dt = datetime.fromisoformat(until) if until else None
        filtered = []
        for sha, commit_date_str in [c.split("|", 1) for c in commits]:
            try:
                commit_dt = datetime.fromisoformat(commit_date_str.replace("Z", "+00:00"))
            except ValueError:
                continue
            if since_dt and commit_dt < since_dt:
                continue
            if until_dt and commit_dt > until_dt:
                continue
            filtered.append((sha, commit_date_str))
        commits = [f"{sha}|{date}" for sha, date in filtered]

    if limit_commits:
        commits = commits[:limit_commits]

    # Pre-load article URL → (article_id, title) cache
    url_cache = {}
    cursor = conn.execute(
        "SELECT url, id, title FROM article WHERE ingest_status = 'ok'"
    )
    for url, article_id, title in cursor.fetchall():
        url_cache[url] = (article_id, title)

    # Track created outlets in this run
    seen_outlets = set()

    # Process each commit
    for commit_line in commits:
        if not commit_line.strip():
            continue

        parts = commit_line.split("|", 1)
        if len(parts) < 2:
            continue

        sha, commit_date_str = parts
        try:
            commit_date = datetime.fromisoformat(
                commit_date_str.replace("Z", "+00:00")
            )
            commit_date_iso = commit_date.isoformat()
        except ValueError:
            counts["skipped"] += 1
            continue

        # Process each outlet
        for outlet_name, section_globs in OUTLET_SECTIONS.items():
            # Get files in this outlet dir (list from git)
            try:
                result = subprocess.run(
                    [
                        "git",
                        "-C",
                        str(repo_path),
                        "ls-tree",
                        "-r",
                        "--name-only",
                        sha,
                        f"docs/snapshots/{outlet_name}",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                # Keep (stem, real filename) pairs — some outlets use
                # multi-dot names like politik.html.json.
                files = [
                    (Path(f).name.split(".")[0], Path(f).name)
                    for f in result.stdout.strip().split("\n")
                    if f and f.endswith(".json")
                ]
            except Exception:
                continue

            # Filter by section globs
            matching_files = []
            for file_stem, file_name in files:
                for glob_pattern in section_globs:
                    if fnmatch(file_stem, glob_pattern):
                        matching_files.append(file_name)
                        break

            # Process matching files
            for file_name in matching_files:
                file_path = f"docs/snapshots/{outlet_name}/{file_name}"

                # Read file from git
                try:
                    result = subprocess.run(
                        ["git", "-C", str(repo_path), "show", f"{sha}:{file_path}"],
                        capture_output=True,
                        text=True,
                        check=False,
                        errors="replace",
                    )
                    if result.returncode != 0:
                        continue

                    content = json.loads(result.stdout)
                except (json.JSONDecodeError, ValueError):
                    counts["skipped"] += 1
                    continue

                articles = content.get("articles", [])
                if not isinstance(articles, list):
                    counts["skipped"] += 1
                    continue

                # Process each article
                for article in articles:
                    title = (article.get("title") or "").strip()
                    url = (article.get("url") or "").strip()
                    teaser = (article.get("teaser") or "").strip()

                    if not title:
                        counts["skipped"] += 1
                        continue
                    if not url:
                        # Some outlets (compact-online.de) publish teaser blocks
                        # without links; key them by a stable title hash so they
                        # still enter the corpus.
                        url = "frontpage://{}/{}".format(
                            outlet_name,
                            hashlib.sha1(title.encode("utf-8")).hexdigest()[:16],
                        )

                    # Normalize URL
                    norm_url = _normalize_url(url)
                    if not norm_url:
                        counts["skipped"] += 1
                        continue

                    # Get or create outlet (once per run)
                    if outlet_name not in seen_outlets:
                        _get_or_create_outlet(conn, outlet_name, feed_url=None, is_synthetic=0)
                        seen_outlets.add(outlet_name)
                        counts["outlets"] += 1

                    # Upsert fp_article_meta
                    cursor = conn.execute(
                        "SELECT title_variants FROM fp_article_meta WHERE url = ?",
                        (norm_url,),
                    )
                    meta_row = cursor.fetchone()

                    if not meta_row:
                        # New article
                        try:
                            conn.execute(
                                """INSERT INTO fp_article_meta
                                   (url, outlet, section, first_seen, last_seen, title_variants)
                                   VALUES (?, ?, ?, ?, ?, 1)""",
                                (norm_url, outlet_name, file_stem, commit_date_iso, commit_date_iso),
                            )

                            # Create outlet lookup
                            outlet_cursor = conn.execute(
                                "SELECT id FROM outlet WHERE name = ?",
                                (outlet_name,),
                            )
                            outlet_row = outlet_cursor.fetchone()
                            if not outlet_row:
                                counts["skipped"] += 1
                                continue

                            outlet_id = outlet_row[0]

                            # Create article
                            body = title + ". " + teaser if teaser else title
                            article_id = insert_and_get_id(
                                conn,
                                """INSERT INTO article
                                   (outlet_id, corpus_id, url, title, body, published_at, ingest_status)
                                   VALUES (?, NULL, ?, ?, ?, ?, 'ok')""",
                                (outlet_id, norm_url, title, body, commit_date_iso),
                            )

                            url_cache[norm_url] = (article_id, title)

                            # Create claim
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

                    else:
                        # Existing article: check for title variant
                        article_id, stored_title = url_cache[norm_url]

                        if title != stored_title:
                            # Title variant: update article and increment counter
                            try:
                                body = title + ". " + teaser if teaser else title
                                conn.execute(
                                    """UPDATE article SET title = ?, body = ? WHERE id = ?""",
                                    (title, body, article_id),
                                )
                                conn.execute(
                                    """UPDATE fp_article_meta SET title_variants = title_variants + 1,
                                       last_seen = ? WHERE url = ?""",
                                    (commit_date_iso, norm_url),
                                )
                                url_cache[norm_url] = (article_id, title)
                                counts["title_variant_updates"] += 1
                            except sqlite3.Error:
                                counts["skipped"] += 1
                                continue
                        else:
                            # Same title: just update last_seen
                            try:
                                conn.execute(
                                    """UPDATE fp_article_meta SET last_seen = ? WHERE url = ?""",
                                    (commit_date_iso, norm_url),
                                )
                            except sqlite3.Error:
                                counts["skipped"] += 1
                                continue

                        counts["articles_updated"] += 1

        conn.commit()
        counts["commits_processed"] += 1

    return counts
