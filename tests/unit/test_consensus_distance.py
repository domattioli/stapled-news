"""Unit tests for consensus distance analysis module."""

import json
from stapled.db import connect
from stapled.experiments import e7_consensus
from stapled.experiments.runner import run_experiment
from stapled.analyze.consensus_distance import (
    compute_distances,
    aggregate_outlets,
    validate_planted,
    build_event_vectors,
)


def test_distances_orientation(tmp_path):
    """Test that deviant outlets show higher mean distance than agreeing ones."""
    db_path = tmp_path / "test_consensus.db"
    conn = connect(str(db_path))

    # Create 3 outlets: A, B (similar), C (deviant)
    outlets = ["A", "B", "C"]
    outlet_ids = {}
    for name in outlets:
        cursor = conn.execute("INSERT INTO outlet (name) VALUES (?)", (name,))
        outlet_ids[name] = cursor.lastrowid

    # Create 1 event with 3 articles
    conn.execute("INSERT INTO event (id) VALUES (?)", (1,))

    # Event 1: A & B have similar titles, C has different title
    titles_by_outlet = {
        "A": "Climate change agreement reached in Paris",
        "B": "Paris climate deal finalized",
        "C": "Unrelated headline about sports",
    }

    article_id = 1
    for outlet_name in outlets:
        outlet_id = outlet_ids[outlet_name]
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{article_id}", titles_by_outlet[outlet_name], "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 1, "occurred", 0.9),
        )
        article_id += 1

    conn.commit()

    # Compute distances
    data = compute_distances(conn, min_outlets=1)
    article_rows = data["articles"]

    # Find distances by outlet
    distances_by_outlet = {}
    for row in article_rows:
        distances_by_outlet[row["outlet"]] = row["distance"]

    # C (deviant) should have higher distance than A or B
    assert distances_by_outlet["C"] > distances_by_outlet["A"]
    assert distances_by_outlet["C"] > distances_by_outlet["B"]

    conn.close()


def test_consensus_headline_membership(tmp_path):
    """Test that consensus headline is one of the member titles."""
    db_path = tmp_path / "test_consensus_headline.db"
    conn = connect(str(db_path))

    outlets = ["X", "Y", "Z"]
    outlet_ids = {}
    for name in outlets:
        cursor = conn.execute("INSERT INTO outlet (name) VALUES (?)", (name,))
        outlet_ids[name] = cursor.lastrowid

    # Event 1
    conn.execute("INSERT INTO event (id) VALUES (?)", (1,))

    titles = [
        "Breaking: Government announces new policy",
        "New policy announcement from government",
        "Different topic headline here",
    ]

    article_id = 1
    for outlet_name, title in zip(outlets, titles):
        outlet_id = outlet_ids[outlet_name]
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{article_id}", title, "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 1, "occurred", 0.9),
        )
        article_id += 1

    conn.commit()

    # Compute distances
    data = compute_distances(conn, min_outlets=1)
    event_rows = data["events"]

    assert len(event_rows) == 1
    consensus_headline = event_rows[0]["consensus_headline"]

    # Consensus must be one of the member titles
    assert consensus_headline in titles

    conn.close()


def test_aggregate_bootstrap_shape(tmp_path):
    """Test aggregate_outlets returns correct shape and bounds."""
    db_path = tmp_path / "test_aggregate.db"
    conn = connect(str(db_path))

    outlets = ["OutletA", "OutletB"]
    outlet_ids = {}
    for name in outlets:
        cursor = conn.execute("INSERT INTO outlet (name) VALUES (?)", (name,))
        outlet_ids[name] = cursor.lastrowid

    # Create 2 events, each with 2 outlets
    for event_id in [1, 2]:
        conn.execute("INSERT INTO event (id) VALUES (?)", (event_id,))

    article_id = 1
    for event_id in [1, 2]:
        for outlet_name in outlets:
            outlet_id = outlet_ids[outlet_name]
            conn.execute(
                "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (outlet_id, f"url-{article_id}", f"Title for event {event_id}", "body", "2024-01-01", "ok"),
            )
            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
                (article_id, event_id, "occurred", 0.9),
            )
            article_id += 1

    conn.commit()

    # Compute distances and aggregate
    data = compute_distances(conn, min_outlets=1)
    article_rows = data["articles"]

    metrics = aggregate_outlets(article_rows, seed=42, n_boot=100)

    # Check shape
    assert len(metrics) == 2  # 2 outlets
    for m in metrics:
        assert "outlet" in m
        assert "n_articles" in m
        assert "mean_distance" in m
        assert "ci_low" in m
        assert "ci_high" in m
        assert "deciles" in m

        # CI should bracket mean
        assert m["ci_low"] <= m["mean_distance"] <= m["ci_high"]

        # Deciles should have 11 values
        assert len(m["deciles"]) == 11

        # Deciles should be monotonic increasing
        for i in range(len(m["deciles"]) - 1):
            assert m["deciles"][i] <= m["deciles"][i + 1]

    conn.close()


def test_validate_planted_gate(tmp_path):
    """Test planted validation gate logic."""
    db_path = tmp_path / "test_planted.db"
    conn = connect(str(db_path))

    # Create multiple outlets to ensure noise diversity
    outlets = ["Outlet1", "Outlet2", "Outlet3", "Outlet4"]
    outlet_ids = {}
    for name in outlets:
        cursor = conn.execute("INSERT INTO outlet (name) VALUES (?)", (name,))
        outlet_ids[name] = cursor.lastrowid

    # Create 2 events to make noise shuffling more interesting
    for event_id in [1, 2]:
        conn.execute("INSERT INTO event (id) VALUES (?)", (event_id,))

    article_id = 1
    titles = [
        "Government announces new climate policy",
        "Climate agreement signed by leaders",
        "Healthcare reform bill passed",
        "Major economic changes ahead",
    ]

    for event_id in [1, 2]:
        for outlet_name, title in zip(outlets, titles):
            outlet_id = outlet_ids[outlet_name]
            conn.execute(
                "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (outlet_id, f"url-{article_id}", title, "body", "2024-01-01", "ok"),
            )
            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
                (article_id, event_id, "occurred", 0.9),
            )
            article_id += 1

    conn.commit()

    # Compute distances
    data = compute_distances(conn, min_outlets=1)

    # Validate planted
    validation = validate_planted(data)

    # Check structure
    assert "copier_mean" in validation
    assert "noise_mean" in validation
    assert "gate_pass" in validation
    assert isinstance(validation["copier_mean"], float)
    assert isinstance(validation["noise_mean"], float)
    assert isinstance(validation["gate_pass"], bool)

    # Copier (own consensus headline vs real centroid) must sit strictly closer
    # than noise (a different event's headline). Absolute values depend on event
    # size; the ordering is the invariant.
    assert validation["copier_mean"] < validation["noise_mean"]
    assert validation["copier_mean"] < 0.6

    conn.close()


def test_e7_quick_runs(tmp_path):
    """Test E7 experiment on synthetic DB."""
    db_path = tmp_path / "test_e7.db"
    conn = connect(str(db_path))

    # Create 3 outlets
    outlets = ["OutletX", "OutletY", "OutletZ"]
    outlet_ids = {}
    for name in outlets:
        cursor = conn.execute("INSERT INTO outlet (name) VALUES (?)", (name,))
        outlet_ids[name] = cursor.lastrowid

    # Create 2 events, both with all 3 outlets
    for event_id in [1, 2]:
        conn.execute("INSERT INTO event (id) VALUES (?)", (event_id,))

    article_id = 1
    for event_id in [1, 2]:
        for outlet_name in outlets:
            outlet_id = outlet_ids[outlet_name]
            conn.execute(
                "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (outlet_id, f"url-{article_id}", f"Headline {event_id} from {outlet_name}", "body", "2024-01-01", "ok"),
            )
            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
                (article_id, event_id, "occurred", 0.9),
            )
            article_id += 1

    conn.commit()
    conn.close()

    # Run experiment with quick=True
    config = {
        "db_path": str(db_path),
        "quick": True,
        "min_outlets": 3,
    }

    out_dir = tmp_path / "e7_output"
    entry = run_experiment("e7", e7_consensus.run, config, seed=42, out_dir=str(out_dir))

    # Check CSV exists
    csv_articles_path = out_dir / "e7_consensus_distance.csv"
    assert csv_articles_path.exists()

    with open(csv_articles_path) as f:
        lines = f.readlines()

    header = lines[0].strip()
    assert "article_id" in header and "outlet" in header and "distance" in header

    # Should have 6 articles (2 events × 3 outlets) + header
    assert len(lines) == 7, f"Expected 7 lines, got {len(lines)}"

    # Parse CSV
    for line in lines[1:]:
        parts = line.strip().split(",")
        assert len(parts) == 4
        article_id = int(parts[0])
        outlet = parts[1]
        event_id = int(parts[2])
        distance = float(parts[3])

        assert outlet in outlets
        assert event_id in [1, 2]
        assert 0 <= distance <= 1

    # Check outlet CSV
    csv_outlets_path = out_dir / "e7_outlet_distance.csv"
    assert csv_outlets_path.exists()

    with open(csv_outlets_path) as f:
        lines = f.readlines()

    header = lines[0].strip()
    assert "outlet" in header and "mean_distance" in header

    # Should have 3 outlets + header
    assert len(lines) == 4

    # Check PNG
    png_path = out_dir / "e7_consensus.png"
    assert png_path.exists()
    assert png_path.stat().st_size > 0

    # Check consensus.json
    json_path = out_dir / "consensus.json"
    assert json_path.exists()

    with open(json_path) as f:
        consensus_data = json.load(f)

    assert "generated_at" in consensus_data
    assert "corpus" in consensus_data
    assert "ranking" in consensus_data
    assert "weekly" in consensus_data
    assert "events" in consensus_data
    assert "validation" in consensus_data

    # Check validation structure
    assert "v1_planted" in consensus_data["validation"]
    assert "v2_split_half" in consensus_data["validation"]
    assert "copier_mean" in consensus_data["validation"]["v1_planted"]
    assert "noise_mean" in consensus_data["validation"]["v1_planted"]
    assert "rho" in consensus_data["validation"]["v2_split_half"]

    # Check manifest
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()

    with open(manifest_path) as f:
        manifest = json.load(f)

    assert len(manifest) == 1
    assert manifest[0]["experiment"] == "e7"

    # Check metrics
    metrics = entry["metrics"]
    assert "n_events" in metrics
    assert "n_articles" in metrics
    assert "n_outlets_ranked" in metrics
    assert "v1_gate" in metrics
    assert "v2_rho" in metrics
    assert "v2_gate" in metrics
    assert "top_outlet" in metrics
    assert "bottom_outlet" in metrics

    # Validate metric ranges
    assert metrics["n_events"] >= 1
    assert metrics["n_articles"] >= 1
    assert metrics["n_outlets_ranked"] >= 1


def test_build_event_vectors(tmp_path):
    """Test TF-IDF vectorizer creation."""
    titles = [
        "Breaking news about climate change",
        "Climate deal announced",
        "Sports news headline",
    ]

    vectorizer_dict, vectors = build_event_vectors(titles)

    # Check dimensions
    assert vectors.shape[0] == 3  # 3 titles
    assert vectors.shape[1] > 0  # Some features

    # Check L2 norm is 1 for each row (normalized)
    import numpy as np
    for i in range(vectors.shape[0]):
        row_norm = np.linalg.norm(vectors[i].toarray())
        assert abs(row_norm - 1.0) < 1e-5, f"Row {i} not L2 normalized"

    # Check vectorizer_dict
    assert "word" in vectorizer_dict
    assert "char" in vectorizer_dict
