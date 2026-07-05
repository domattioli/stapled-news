"""Unit tests for consensus distance analysis module."""

import json
import numpy as np
from stapled.db import connect
from stapled.experiments import e7_consensus
from stapled.experiments.runner import run_experiment
from stapled.analyze.consensus_distance import (
    compute_distances,
    aggregate_outlets,
    validate_planted,
    build_event_vectors,
    _lean_bucket_weights,
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
    # Distinct topics per event so the noise derangement (event 1 gets event 2's
    # consensus headline) is a genuinely different text, not the same string.
    titles_by_event = {
        1: [
            "Government announces new climate policy",
            "Climate agreement signed by leaders",
            "New climate policy announced by government",
            "Leaders sign sweeping climate agreement",
        ],
        2: [
            "Star quarterback traded after playoff defeat",
            "Quarterback trade follows playoff loss",
            "Team trades star quarterback in shakeup",
            "Playoff defeat triggers quarterback trade",
        ],
    }

    for event_id in [1, 2]:
        for outlet_name, title in zip(outlets, titles_by_event[event_id]):
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


def test_lean_bucket_weights_equalizes_bucket_totals():
    """Each present PANEL_LEAN bucket should receive equal total weight,
    regardless of how many outlets/articles are in it."""
    # 6 left-rated outlets, 1 right-rated, 1 unrated.
    outlets = [
        "nytimes.com", "cnn.com", "washingtonpost.com",
        "npr.org", "msnbc.com", "vox.com",
        "foxnews.com",
        "some-unrated-blog.example",
    ]
    w = _lean_bucket_weights(outlets)
    totals = {}
    from stapled.analyze.consensus_distance import PANEL_LEAN
    for outlet, weight in zip(outlets, w):
        bucket = PANEL_LEAN.get(outlet, "unrated")
        totals[bucket] = totals.get(bucket, 0.0) + weight

    assert len(totals) == 3  # left, right, unrated all present
    shares = list(totals.values())
    assert all(abs(s - shares[0]) < 1e-9 for s in shares), (
        f"bucket totals should be equal, got {totals}"
    )
    assert abs(sum(shares) - 1.0) < 1e-9


def test_lean_bucket_weights_single_bucket_is_uniform():
    """With no PANEL_LEAN outlets present, balancing degenerates to uniform
    per-article weight (preserves pre-existing behavior for unrated-only
    events, and for tests using synthetic outlet names)."""
    outlets = ["A", "B", "C"]
    w = _lean_bucket_weights(outlets)
    assert np.allclose(w, [1.0 / 3, 1.0 / 3, 1.0 / 3])


def test_compute_distances_lean_balanced_controls_for_panel_skew(tmp_path):
    """A story covered by 6 left-rated outlets writing near-identical wording
    and 1 right-rated outlet writing distinctly different wording: under raw
    per-article weighting the centroid is dominated by the left bloc's exact
    phrasing (left distance ~0, right distance high). Under lean-balanced
    weighting, left and right each get equal say in the centroid, which must
    pull the centroid toward the right outlet's wording — shrinking its
    distance relative to the unbalanced case."""
    db_path = tmp_path / "test_lean_balance.db"
    conn = connect(str(db_path))

    left_outlets = [
        "nytimes.com", "cnn.com", "washingtonpost.com",
        "npr.org", "msnbc.com", "vox.com",
    ]
    right_outlets = ["foxnews.com"]
    all_outlets = left_outlets + right_outlets

    outlet_ids = {}
    for name in all_outlets:
        cursor = conn.execute("INSERT INTO outlet (name) VALUES (?)", (name,))
        outlet_ids[name] = cursor.lastrowid

    conn.execute("INSERT INTO event (id) VALUES (?)", (1,))

    article_id = 1
    for name in left_outlets:
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_ids[name], f"url-{article_id}",
             "Senate passes the infrastructure funding bill", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 1, "occurred", 0.9),
        )
        article_id += 1
    for name in right_outlets:
        conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_ids[name], f"url-{article_id}",
             "Lawmakers clash over pork-laden spending package", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 1, "occurred", 0.9),
        )
        article_id += 1
    conn.commit()

    unbalanced = compute_distances(conn, min_outlets=1, lean_balanced=False)
    balanced = compute_distances(conn, min_outlets=1, lean_balanced=True)

    def right_distance(data):
        return next(r["distance"] for r in data["articles"] if r["outlet"] == "foxnews.com")

    def mean_left_distance(data):
        left_rows = [r["distance"] for r in data["articles"] if r["outlet"] in left_outlets]
        return sum(left_rows) / len(left_rows)

    assert right_distance(balanced) < right_distance(unbalanced), (
        "balancing should pull the centroid toward the outnumbered bucket, "
        "shrinking its distance from consensus"
    )
    assert mean_left_distance(balanced) > mean_left_distance(unbalanced), (
        "balancing should move the centroid away from the numerically-dominant "
        "bucket's exact wording, growing its distance from consensus"
    )

    conn.close()
