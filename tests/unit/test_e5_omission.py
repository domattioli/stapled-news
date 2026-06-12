"""Unit tests for E5 omission audit experiment."""

import json

from stapled.experiments import e5_omission
from stapled.experiments.runner import run_experiment
from stapled.db import connect


def test_e5_quick_runs(tmp_path):
    """Test E5 experiment on a minimal synthetic UCI-like DB."""

    # Create tiny synthetic DB with controlled coverage for testing
    db_path = tmp_path / "tiny_uci.db"
    conn = connect(str(db_path))

    # Create 3 outlets
    outlets = ["outlet_a", "outlet_b", "outlet_c"]
    outlet_ids = {}
    for name in outlets:
        cursor = conn.execute("INSERT INTO outlet (name) VALUES (?)", (name,))
        outlet_ids[name] = cursor.lastrowid

    # Create events (2 per category, min 3 outlets each for "well-corroborated")
    events_by_category = {"uci_b": [], "uci_t": []}
    event_id = 1

    for category in ["uci_b", "uci_t"]:
        for _ in range(2):
            conn.execute("INSERT INTO event (id) VALUES (?)", (event_id,))
            events_by_category[category].append(event_id)
            event_id += 1

    # Create articles and claims
    # Event 1 (uci_b): all 3 outlets cover
    # Event 2 (uci_b): outlets a, b only cover
    # Event 3 (uci_t): all 3 outlets cover
    # Event 4 (uci_t): outlet a only covers
    article_id = 1

    # Event 1: all 3 outlets
    for outlet_name in outlets:
        outlet_id = outlet_ids[outlet_name]
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{article_id}", f"title-{article_id}", "body", "2024-01-01", "ok"),
        )  # noqa: E501
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 1, "occurred", 0.9),
        )
        conn.execute(
            "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
            (article_id, "uci_b", "B"),
        )
        article_id += 1

    # Event 2: outlets a, b only
    for outlet_name in ["outlet_a", "outlet_b"]:
        outlet_id = outlet_ids[outlet_name]
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{article_id}", f"title-{article_id}", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 2, "occurred", 0.9),
        )
        conn.execute(
            "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
            (article_id, "uci_b", "B"),
        )
        article_id += 1

    # Add third outlet to event 2 to make it "well-corroborated"
    outlet_id = outlet_ids["outlet_c"]
    conn.execute(
        "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (outlet_id, f"url-{article_id}", f"title-{article_id}", "body", "2024-01-01", "ok"),
    )
    conn.execute(
        "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
        (article_id, 2, "did-not-occur", 0.9),
    )
    conn.execute(
        "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
        (article_id, "uci_b", "B"),
    )
    article_id += 1

    # Event 3: all 3 outlets cover (uci_t)
    for outlet_name in outlets:
        outlet_id = outlet_ids[outlet_name]
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{article_id}", f"title-{article_id}", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 3, "occurred", 0.9),
        )
        conn.execute(
            "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
            (article_id, "uci_t", "T"),
        )
        article_id += 1

    # Event 4: outlet a only (uci_t)
    outlet_id = outlet_ids["outlet_a"]
    for i in range(3):  # Add 3 articles from a to reach min_outlets=3
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{article_id}", f"title-{article_id}", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 4, "occurred", 0.9),
        )
        conn.execute(
            "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
            (article_id, "uci_t", "T"),
        )
        article_id += 1

    # Add two more outlets to event 4 to reach min_outlets=3
    for outlet_name in ["outlet_b", "outlet_c"]:
        outlet_id = outlet_ids[outlet_name]
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{article_id}", f"title-{article_id}", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 4, "did-not-occur", 0.9),
        )
        conn.execute(
            "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
            (article_id, "uci_t", "T"),
        )
        article_id += 1

    conn.commit()
    conn.close()

    # Run experiment with quick=True
    config = {
        "db_path": str(db_path),
        "quick": True,
    }

    out_dir = tmp_path / "e5_output"
    entry = run_experiment("e5", e5_omission.run, config, seed=42, out_dir=str(out_dir))

    # Check CSV exists and is valid
    csv_path = out_dir / "e5_omission.csv"
    assert csv_path.exists()

    with open(csv_path) as f:
        lines = f.readlines()

    header = lines[0].strip()
    assert "outlet" in header and "category" in header and "coverage_rate" in header

    # Expect 3 outlets × 2 categories (only uci_b and uci_t have events) = 6 rows + header
    assert len(lines) >= 7, f"Expected at least 7 lines, got {len(lines)}"

    # Parse rows
    for line in lines[1:]:
        parts = line.strip().split(",")
        assert len(parts) == 8  # outlet, category, events_in_cat, events_covered, coverage, omission, sens, rel

        outlet = parts[0]
        category = parts[1]
        coverage_rate = float(parts[4])
        omission_score = float(parts[5])
        em_sens = float(parts[6])
        em_rel = float(parts[7])

        assert outlet in outlets
        assert category in ["uci_b", "uci_t", "uci_e", "uci_m"]
        assert 0 <= coverage_rate <= 1
        assert 0 <= omission_score <= 1
        assert coverage_rate + omission_score == 1.0 or abs(coverage_rate + omission_score - 1.0) < 1e-5
        assert 0.01 <= em_sens <= 0.99
        assert 0.01 <= em_rel <= 0.99

    # Check PNG exists
    png_path = out_dir / "e5_omission.png"
    assert png_path.exists()
    assert png_path.stat().st_size > 0

    # Check markdown case studies exist
    md_path = out_dir / "e5_case_studies.md"
    assert md_path.exists()

    with open(md_path) as f:
        md_content = f.read()
    assert "Case Studies" in md_content or "asymmetry" in md_content.lower()

    # Check manifest
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()

    with open(manifest_path) as f:
        manifest = json.load(f)

    assert len(manifest) == 1
    assert manifest[0]["experiment"] == "e5"

    # Check metrics
    metrics = entry["metrics"]
    assert "n_events_used" in metrics
    assert "n_outlets_audited" in metrics
    assert "mean_coverage_by_category" in metrics
    assert "max_asymmetry_value" in metrics

    # Validate metric ranges
    assert metrics["n_events_used"] >= 1
    assert metrics["n_outlets_audited"] >= 1
    assert isinstance(metrics["mean_coverage_by_category"], dict)
    assert metrics["max_asymmetry_value"] >= 0


def test_coverage_rate_hand_computed(tmp_path):
    """Test coverage_rate computation with hand-crafted scenario."""

    db_path = tmp_path / "coverage_test.db"
    conn = connect(str(db_path))

    # 4 outlets
    outlet_ids = {}
    for i in range(4):
        cursor = conn.execute("INSERT INTO outlet (name) VALUES (?)", (f"outlet_{i}",))
        outlet_ids[f"o{i}"] = cursor.lastrowid

    # 4 events, all category "uci_b", all have min 3 outlets
    for event_id in range(1, 5):
        conn.execute("INSERT INTO event (id) VALUES (?)", (event_id,))

    # Build controlled coverage: o0 covers events 1,2 only (2 of 4 → 0.5)
    # o1, o2, o3 cover all 4 events
    article_id = 1

    # o1, o2, o3 cover all 4 events
    for event_id in range(1, 5):
        for outlet_name in ["o1", "o2", "o3"]:
            outlet_id = outlet_ids[outlet_name]
            conn.execute(
                "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (outlet_id, f"url-{article_id}", "title", "body", "2024-01-01", "ok"),
            )
            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
                (article_id, event_id, "occurred", 0.9),
            )
            conn.execute(
                "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
                (article_id, "uci_b", "B"),
            )
            article_id += 1

    # o0 covers events 1, 2 only
    for event_id in [1, 2]:
        outlet_id = outlet_ids["o0"]
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{article_id}", "title", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, event_id, "occurred", 0.9),
        )
        conn.execute(
            "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
            (article_id, "uci_b", "B"),
        )
        article_id += 1

    conn.commit()

    # Now compute coverage for o0
    coverage_matrix = e5_omission._compute_coverage_matrix(
        conn, list(outlet_ids.values()), {oid: {"name": f"outlet_{i}"} for i, oid in enumerate(outlet_ids.values())},
        [1, 2, 3, 4], min_outlets=3
    )

    o0_id = outlet_ids["o0"]
    coverage_rate = coverage_matrix[(o0_id, "uci_b")]["coverage_rate"]

    # o0 covers 2 of 4 events → 0.5
    assert abs(coverage_rate - 0.5) < 1e-5, f"Expected 0.5, got {coverage_rate}"

    conn.close()


def test_category_majority_assignment(tmp_path):
    """Test event category assignment via majority article label voting."""

    db_path = tmp_path / "majority_test.db"
    conn = connect(str(db_path))

    # 1 outlet
    cursor = conn.execute("INSERT INTO outlet (name) VALUES (?)", ("outlet_x",))
    outlet_id = cursor.lastrowid

    # 1 event
    conn.execute("INSERT INTO event (id) VALUES (?)", (1,))

    # Create 3 articles for event 1: 2 labeled uci_b, 1 labeled uci_t
    article_ids = []
    for i in range(3):
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{i}", "title", "body", "2024-01-01", "ok"),
        )
        article_ids.append(cursor.lastrowid)

    # Add claims for all articles to event 1
    for article_id in article_ids:
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 1, "occurred", 0.9),
        )

    # Label: 2 uci_b, 1 uci_t
    conn.execute("INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
                 (article_ids[0], "uci_b", "B"))
    conn.execute("INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
                 (article_ids[1], "uci_b", "B"))
    conn.execute("INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
                 (article_ids[2], "uci_t", "T"))

    conn.commit()

    # Test coverage matrix computation
    coverage_matrix = e5_omission._compute_coverage_matrix(
        conn, [outlet_id], {outlet_id: {"name": "outlet_x"}},
        [1], min_outlets=1
    )

    # Event 1 has majority label uci_b (2 votes vs 1 for uci_t)
    # Outlet covers event 1, so coverage_rate("outlet_x", "uci_b") should be 1.0
    cov_b = coverage_matrix[(outlet_id, "uci_b")]["coverage_rate"]
    cov_t = coverage_matrix[(outlet_id, "uci_t")]["coverage_rate"]

    assert abs(cov_b - 1.0) < 1e-5, f"Expected coverage=1.0 for uci_b, got {cov_b}"
    assert abs(cov_t - 0.0) < 1e-5, f"Expected coverage=0.0 for uci_t, got {cov_t}"

    conn.close()
