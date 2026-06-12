"""Unit tests for frontpage-archive-2026 loader."""

import json
import subprocess

from stapled.db import connect
from stapled.ingest.frontpages import load_frontpages


def _create_test_repo(tmp_path):
    """Create a minimal git repo with two commits containing test snapshots."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    # Initialize git repo
    subprocess.run(
        ["git", "init"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    # First commit: spiegel.de and welt.de with initial articles
    commit1_timestamp = "2026-05-13T08:00:00Z"

    snapshots_dir = repo_path / "docs" / "snapshots"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    spiegel_dir = snapshots_dir / "spiegel.de"
    spiegel_dir.mkdir(parents=True, exist_ok=True)

    welt_dir = snapshots_dir / "welt.de"
    welt_dir.mkdir(parents=True, exist_ok=True)

    # Article A (spiegel, will be updated in commit 2)
    spiegel_artikel_a = {
        "timestamp": commit1_timestamp,
        "articles": [
            {
                "title": "Government announces new policy",
                "teaser": "The government announced a major policy shift today.",
                "url": "https://spiegel.de/artikel-a",
                "image_url": "https://spiegel.de/img-a.jpg",
                "image_title": "Policy announcement",
            }
        ],
    }

    # Article B (welt, will also appear in commit 2)
    welt_artikel_b = {
        "timestamp": commit1_timestamp,
        "articles": [
            {
                "title": "Economy reports growth",
                "teaser": "Economic indicators show positive trend.",
                "url": "https://welt.de/artikel-b",
                "image_url": "https://welt.de/img-b.jpg",
                "image_title": "Economy growth",
            }
        ],
    }

    (spiegel_dir / "politik.json").write_text(json.dumps(spiegel_artikel_a))
    (welt_dir / "politik.json").write_text(json.dumps(welt_artikel_b))

    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    # Commit with deterministic date
    env = {
        "GIT_AUTHOR_DATE": "2026-05-13T08:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-05-13T08:00:00+00:00",
    }
    subprocess.run(
        ["git", "commit", "-m", "First snapshot"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
        env={**subprocess.os.environ, **env},
    )

    # Second commit: update A's title, add new article C (spiegel), B unchanged
    commit2_timestamp = "2026-05-13T09:00:00Z"

    # Article A with new title (variant)
    spiegel_artikel_a_v2 = {
        "timestamp": commit2_timestamp,
        "articles": [
            {
                "title": "Government policy shift attracts criticism",
                "teaser": "The government announced a major policy shift today.",
                "url": "https://spiegel.de/artikel-a",
                "image_url": "https://spiegel.de/img-a.jpg",
                "image_title": "Policy announcement",
            },
            {
                "title": "Climate negotiations progress",
                "teaser": "International talks advance on climate action.",
                "url": "https://spiegel.de/artikel-c",
                "image_url": "https://spiegel.de/img-c.jpg",
                "image_title": "Climate talks",
            },
        ],
    }

    welt_artikel_b_unchanged = {
        "timestamp": commit2_timestamp,
        "articles": [
            {
                "title": "Economy reports growth",
                "teaser": "Economic indicators show positive trend.",
                "url": "https://welt.de/artikel-b",
                "image_url": "https://welt.de/img-b.jpg",
                "image_title": "Economy growth",
            }
        ],
    }

    (spiegel_dir / "politik.json").write_text(json.dumps(spiegel_artikel_a_v2))
    (welt_dir / "politik.json").write_text(json.dumps(welt_artikel_b_unchanged))

    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    env = {
        "GIT_AUTHOR_DATE": "2026-05-13T09:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-05-13T09:00:00+00:00",
    }
    subprocess.run(
        ["git", "commit", "-m", "Second snapshot"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
        env={**subprocess.os.environ, **env},
    )

    return repo_path


def test_load_two_commits(tmp_path):
    """Test loading two commits with variants and new articles."""
    # Create test repo
    repo_path = _create_test_repo(tmp_path)

    # Create database
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Load frontpages
    counts = load_frontpages(conn, repo_path=str(repo_path))

    # Verify counts
    assert counts["commits_processed"] == 2
    assert counts["articles_new"] == 3  # A, B, C
    assert counts["articles_updated"] == 2  # A (title variant) + B (same title, updated last_seen)
    assert counts["title_variant_updates"] == 1  # A (title changed)
    assert counts["outlets"] == 2  # spiegel.de, welt.de

    # Verify fp_article_meta rows
    cursor = conn.execute(
        "SELECT url, outlet, section, first_seen, last_seen, title_variants FROM fp_article_meta ORDER BY url"
    )
    rows = cursor.fetchall()

    # Should have 3 rows (A, B, C)
    assert len(rows) == 3

    # Article A
    a_row = [r for r in rows if "artikel-a" in r[0]][0]
    assert a_row[1] == "spiegel.de"
    assert a_row[2] == "politik"
    assert a_row[4] > a_row[3]  # last_seen > first_seen
    assert a_row[5] == 2  # title_variants == 2

    # Article B
    b_row = [r for r in rows if "artikel-b" in r[0]][0]
    assert b_row[1] == "welt.de"
    assert b_row[2] == "politik"
    assert b_row[4] > b_row[3]  # last_seen > first_seen (appeared in both commits)
    assert b_row[5] == 1  # title_variants == 1 (same title, not a variant)

    # Article C
    c_row = [r for r in rows if "artikel-c" in r[0]][0]
    assert c_row[1] == "spiegel.de"
    assert c_row[2] == "politik"
    assert c_row[3] == c_row[4]  # same timestamp
    assert c_row[5] == 1  # title_variants == 1

    # Verify latest titles stored in article table
    cursor = conn.execute("SELECT url, title FROM article ORDER BY url")
    article_rows = cursor.fetchall()
    titles = {url: title for url, title in article_rows}

    # A should have the new title
    assert "criticism" in titles["https://spiegel.de/artikel-a"]
    # B should still have original
    assert "growth" in titles["https://welt.de/artikel-b"]
    # C should be new
    assert "Climate" in titles["https://spiegel.de/artikel-c"]


def test_url_normalization(tmp_path):
    """Test that query strings and fragments are stripped."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "init"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    snapshots_dir = repo_path / "docs" / "snapshots" / "spiegel.de"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Commit 1: article with query string
    commit1_data = {
        "timestamp": "2026-05-13T08:00:00Z",
        "articles": [
            {
                "title": "Test article",
                "teaser": "Teaser text",
                "url": "https://spiegel.de/test?ref=xyz&utm=abc",
            }
        ],
    }
    (snapshots_dir / "politik.json").write_text(json.dumps(commit1_data))

    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    env = {
        "GIT_AUTHOR_DATE": "2026-05-13T08:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-05-13T08:00:00+00:00",
    }
    subprocess.run(
        ["git", "commit", "-m", "Commit 1"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
        env={**subprocess.os.environ, **env},
    )

    # Commit 2: same article but with fragment + query
    commit2_data = {
        "timestamp": "2026-05-13T09:00:00Z",
        "articles": [
            {
                "title": "Test article",
                "teaser": "Teaser text",
                "url": "https://spiegel.de/test?utm=xyz#section1",
            }
        ],
    }
    (snapshots_dir / "politik.json").write_text(json.dumps(commit2_data))

    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    env = {
        "GIT_AUTHOR_DATE": "2026-05-13T09:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-05-13T09:00:00+00:00",
    }
    subprocess.run(
        ["git", "commit", "-m", "Commit 2"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
        env={**subprocess.os.environ, **env},
    )

    # Load and verify
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    counts = load_frontpages(conn, repo_path=str(repo_path))

    # Should treat both as same article (both normalize to https://spiegel.de/test)
    assert counts["articles_new"] == 1
    assert counts["articles_updated"] == 1  # Same title, just last_seen updated

    # Verify only one row in fp_article_meta
    cursor = conn.execute("SELECT COUNT(*) FROM fp_article_meta")
    assert cursor.fetchone()[0] == 1


def test_section_globs(tmp_path):
    """Test that section glob matching works and non-political sections ignored."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "init"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    snapshots_dir = repo_path / "docs" / "snapshots" / "spiegel.de"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    # Create both matching and non-matching sections
    politik_data = {
        "timestamp": "2026-05-13T08:00:00Z",
        "articles": [
            {
                "title": "Political news",
                "teaser": "Politics content",
                "url": "https://spiegel.de/politik-article",
            }
        ],
    }
    ausland_data = {
        "timestamp": "2026-05-13T08:00:00Z",
        "articles": [
            {
                "title": "International news",
                "teaser": "Ausland content",
                "url": "https://spiegel.de/ausland-article",
            }
        ],
    }
    sport_data = {
        "timestamp": "2026-05-13T08:00:00Z",
        "articles": [
            {
                "title": "Sports news",
                "teaser": "Sports content",
                "url": "https://spiegel.de/sport-article",
            }
        ],
    }

    (snapshots_dir / "politik.json").write_text(json.dumps(politik_data))
    (snapshots_dir / "ausland.json").write_text(json.dumps(ausland_data))
    (snapshots_dir / "sport.json").write_text(json.dumps(sport_data))

    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    env = {
        "GIT_AUTHOR_DATE": "2026-05-13T08:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-05-13T08:00:00+00:00",
    }
    subprocess.run(
        ["git", "commit", "-m", "Commit with sections"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
        env={**subprocess.os.environ, **env},
    )

    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    counts = load_frontpages(conn, repo_path=str(repo_path))

    # Should load 2 articles (politik + ausland match OUTLET_SECTIONS glob)
    # sport should be ignored
    assert counts["articles_new"] == 2

    # Verify articles in DB
    cursor = conn.execute("SELECT COUNT(*) FROM article")
    assert cursor.fetchone()[0] == 2


def test_negation_claim_action(tmp_path):
    """Test that German negation correctly sets claim action to 'not-occurred'."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "init"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    snapshots_dir = repo_path / "docs" / "snapshots" / "spiegel.de"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": "2026-05-13T08:00:00Z",
        "articles": [
            {
                "title": "Official dementiert Gerüchte",
                "teaser": "Denies rumors",
                "url": "https://spiegel.de/denies",
            },
            {
                "title": "Event ist nicht bestätigt",
                "teaser": "Not confirmed",
                "url": "https://spiegel.de/not-confirmed",
            },
            {
                "title": "Real-world event occurred",
                "teaser": "Confirmed event",
                "url": "https://spiegel.de/occurred",
            },
        ],
    }

    (snapshots_dir / "politik.json").write_text(json.dumps(data))

    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    env = {
        "GIT_AUTHOR_DATE": "2026-05-13T08:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-05-13T08:00:00+00:00",
    }
    subprocess.run(
        ["git", "commit", "-m", "Negation test"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
        env={**subprocess.os.environ, **env},
    )

    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    counts = load_frontpages(conn, repo_path=str(repo_path))

    assert counts["articles_new"] == 3

    # Verify claim actions
    cursor = conn.execute("SELECT article_id, action FROM claim ORDER BY article_id")
    claims = cursor.fetchall()

    assert len(claims) == 3
    assert claims[0][1] == "not-occurred"  # dementiert
    assert claims[1][1] == "not-occurred"  # nicht
    assert claims[2][1] == "occurred"  # normal


def test_empty_repo_fields(tmp_path):
    """Test that articles with missing title/url are skipped."""
    repo_path = tmp_path / "test_repo"
    repo_path.mkdir(parents=True, exist_ok=True)

    subprocess.run(
        ["git", "init"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.email", "t@t"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "t"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "config", "commit.gpgsign", "false"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    snapshots_dir = repo_path / "docs" / "snapshots" / "welt.de"
    snapshots_dir.mkdir(parents=True, exist_ok=True)

    data = {
        "timestamp": "2026-05-13T08:00:00Z",
        "articles": [
            {
                "title": "Good article",
                "teaser": "OK",
                "url": "https://welt.de/good",
            },
            {
                "title": "",  # Missing title
                "teaser": "Bad",
                "url": "https://welt.de/no-title",
            },
            {
                "title": "No URL article",
                "teaser": "Bad",
                "url": "",  # Missing URL
            },
        ],
    }

    (snapshots_dir / "politik.json").write_text(json.dumps(data))

    subprocess.run(
        ["git", "add", "."],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
    )

    env = {
        "GIT_AUTHOR_DATE": "2026-05-13T08:00:00+00:00",
        "GIT_COMMITTER_DATE": "2026-05-13T08:00:00+00:00",
    }
    subprocess.run(
        ["git", "commit", "-m", "Empty fields test"],
        cwd=str(repo_path),
        capture_output=True,
        check=True,
        env={**subprocess.os.environ, **env},
    )

    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    counts = load_frontpages(conn, repo_path=str(repo_path))

    # Only 1 article should be loaded
    assert counts["articles_new"] == 1
    # 2 should be skipped
    assert counts["skipped"] >= 2
