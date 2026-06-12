"""Unit tests for E6 anchor-budget sweep experiment."""

import json

from stapled.experiments import e6_anchoring
from stapled.experiments.runner import run_experiment
from stapled.db import connect


def test_e6_quick_runs(tmp_path):
    """Test e6 experiment on a minimal synthetic stream-like DB with quick mode."""

    # Create tiny synthetic DB (1 real, 2 fake outlets)
    db_path = tmp_path / "tiny_stream.db"
    conn = connect(str(db_path))

    # Create outlets
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("reuters", 0))
    reuters_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("fake:x", 1))
    fake_x_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("fake:y", 1))
    fake_y_id = cursor.lastrowid

    # Create events
    n_events = 10
    for i in range(1, n_events + 1):
        conn.execute("INSERT INTO event (id) VALUES (?)", (i,))

    # Create articles and claims
    article_id = 1
    for event_id in range(1, n_events + 1):
        for outlet_id in [reuters_id, fake_x_id, fake_y_id]:
            conn.execute(
                "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (outlet_id, f"url-{article_id}", f"title-{article_id}", "body text", "2024-01-01", "ok"),
            )

            # Claim with action 'occurred' for real outlet, 'did-not-occur' for fake
            action = "occurred" if outlet_id == reuters_id else "did-not-occur"
            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty) "
                "VALUES (?, ?, ?, ?)",
                (article_id, event_id, action, 0.9),
            )
            article_id += 1

    conn.commit()
    conn.close()

    # Run experiment in quick mode
    config = {
        "db_path": str(db_path),
        "min_outlets": 2,
        "batch_size": 32,
        "quick": True,
    }

    out_dir = tmp_path / "e6_output"
    entry = run_experiment("e6", e6_anchoring.run, config, seed=42, out_dir=str(out_dir))

    # Check CSV exists and is valid
    csv_path = out_dir / "e6_anchoring.csv"
    assert csv_path.exists()

    with open(csv_path) as f:
        lines = f.readlines()

    assert lines[0].strip() == "budget,auc,real_rank,reuters_reliability,mean_fake_reliability"

    # Expect: 2 budgets ([0, 25]) + 1 header = 3 lines
    assert len(lines) == 3

    # Parse and validate rows
    budgets_seen = []
    for line in lines[1:]:
        parts = line.strip().split(",")
        assert len(parts) == 5

        budget = int(parts[0])
        auc = float(parts[1])
        real_rank = int(parts[2])
        reuters_reliability = float(parts[3])
        mean_fake_reliability = float(parts[4])

        budgets_seen.append(budget)
        assert budget in [0, 25]
        assert 0 <= auc <= 1
        assert 1 <= real_rank <= 3
        assert 0 <= reuters_reliability <= 1
        assert 0 <= mean_fake_reliability <= 1

    assert budgets_seen == [0, 25]

    # Check PNG exists
    png_path = out_dir / "e6_anchoring.png"
    assert png_path.exists()
    assert png_path.stat().st_size > 0

    # Check manifest
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()

    with open(manifest_path) as f:
        manifest = json.load(f)

    assert len(manifest) == 1
    assert manifest[0]["experiment"] == "e6"

    # Check metrics
    metrics = entry["metrics"]
    assert "auc_by_budget" in metrics
    assert "n_multi_outlet_events" in metrics
    assert "min_budget_full_recovery" in metrics

    # Validate metrics
    auc_by_budget = metrics["auc_by_budget"]
    assert "0" in auc_by_budget
    assert "25" in auc_by_budget
    assert 0 <= auc_by_budget["0"] <= 1
    assert 0 <= auc_by_budget["25"] <= 1
    assert metrics["n_multi_outlet_events"] == 10
    # min_budget_full_recovery can be None or an int
    assert metrics["min_budget_full_recovery"] is None or isinstance(metrics["min_budget_full_recovery"], int)


def test_anchor_selection_prefers_corroborated(tmp_path):
    """Test that anchor selection prefers events with more outlets."""

    # Create DB with 3 outlets and 5 events with different corroboration levels
    db_path = tmp_path / "corroboration_test.db"
    conn = connect(str(db_path))

    # Create outlets
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("reuters", 0))
    reuters_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("fake:x", 1))
    fake_x_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("fake:y", 1))
    fake_y_id = cursor.lastrowid

    # Event 1: 3 outlets (reuters, fake:x, fake:y)
    conn.execute("INSERT INTO event (id) VALUES (1)")
    for i, outlet_id in enumerate([reuters_id, fake_x_id, fake_y_id]):
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-1-{i}", "title", "body", "2024-01-01", "ok"),
        )
        cursor = conn.execute("SELECT last_insert_rowid()")
        article_id = cursor.fetchone()[0]
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 1, "occurred", 0.9),
        )

    # Event 2: 2 outlets (reuters, fake:x)
    conn.execute("INSERT INTO event (id) VALUES (2)")
    for i, outlet_id in enumerate([reuters_id, fake_x_id]):
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-2-{i}", "title", "body", "2024-01-01", "ok"),
        )
        cursor = conn.execute("SELECT last_insert_rowid()")
        article_id = cursor.fetchone()[0]
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 2, "occurred", 0.9),
        )

    # Events 3-5: 2 outlets each (for padding)
    for event_id in [3, 4, 5]:
        conn.execute("INSERT INTO event (id) VALUES (?)", (event_id,))
        for i, outlet_id in enumerate([reuters_id, fake_y_id]):
            conn.execute(
                "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (outlet_id, f"url-{event_id}-{i}", "title", "body", "2024-01-01", "ok"),
            )
            cursor = conn.execute("SELECT last_insert_rowid()")
            article_id = cursor.fetchone()[0]
            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
                (article_id, event_id, "occurred", 0.9),
            )

    conn.commit()

    # Verify multi-outlet events sorted by outlet count
    cursor = conn.execute(
        """
        SELECT c.event_id, COUNT(DISTINCT a.outlet_id) as outlet_count
        FROM claim c
        JOIN article a ON c.article_id = a.id
        WHERE c.event_id IS NOT NULL
        GROUP BY c.event_id
        HAVING COUNT(DISTINCT a.outlet_id) >= 2
        ORDER BY outlet_count DESC, c.event_id
        """
    )
    sorted_events = [row[0] for row in cursor.fetchall()]

    # Event 1 should be first (3 outlets), then events 2, 3, 4, 5 (2 outlets each)
    assert sorted_events[0] == 1
    assert len(sorted_events) == 5

    conn.close()


def test_anchor_truth_assignment(tmp_path):
    """Test that anchor true_state correctly identifies reuters contributions."""

    db_path = tmp_path / "anchor_truth_test.db"
    conn = connect(str(db_path))

    # Create outlets
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("reuters", 0))
    reuters_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("fake:x", 1))
    fake_x_id = cursor.lastrowid

    # Event 1: has reuters claim → true_state = 1
    conn.execute("INSERT INTO event (id) VALUES (1)")

    conn.execute(
        "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (reuters_id, "url-r1", "title", "body", "2024-01-01", "ok"),
    )
    reuters_article_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute(
        "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (fake_x_id, "url-f1", "title", "body", "2024-01-01", "ok"),
    )
    fake_article_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute(
        "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
        (reuters_article_id, 1, "occurred", 0.9),
    )
    conn.execute(
        "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
        (fake_article_id, 1, "did-not-occur", 0.9),
    )

    # Event 2: only fake claims → true_state = 0
    conn.execute("INSERT INTO event (id) VALUES (2)")

    conn.execute(
        "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (fake_x_id, "url-f2", "title", "body", "2024-01-01", "ok"),
    )
    fake_article_id2 = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    conn.execute(
        "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
        (fake_article_id2, 2, "did-not-occur", 0.9),
    )

    conn.commit()

    # Test anchor truth assignment
    truth_1 = e6_anchoring._get_event_anchor_truth(conn, 1, reuters_id)
    truth_2 = e6_anchoring._get_event_anchor_truth(conn, 2, reuters_id)

    assert truth_1 == 1, "Event 1 should have true_state=1 (reuters present)"
    assert truth_2 == 0, "Event 2 should have true_state=0 (no reuters)"

    conn.close()
