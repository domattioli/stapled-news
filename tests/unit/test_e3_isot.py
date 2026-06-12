"""Unit tests for E3 ISOT real-data experiment."""

import json

from stapled.experiments import e3_isot
from stapled.experiments.runner import run_experiment
from stapled.db import connect


def test_e3_runs_on_synthetic_db(tmp_path):
    """Test e3 experiment on a minimal synthetic stream-like DB."""

    # Create tiny synthetic DB
    db_path = tmp_path / "tiny_stream.db"
    conn = connect(str(db_path))

    # Create outlets: one "reuters" (real), two "fake:x" and "fake:y" (synthetic)
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("reuters", 0))
    reuters_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("fake:x", 1))
    fake_x_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("fake:y", 1))
    fake_y_id = cursor.lastrowid

    # Create a few events
    for i in range(3):
        conn.execute("INSERT INTO event (id) VALUES (?)", (i + 1,))

    event_ids = [1, 2, 3]

    # Create articles (one per outlet per event)
    article_id = 1
    for event_id in event_ids:
        for outlet_id in [reuters_id, fake_x_id, fake_y_id]:
            conn.execute(
                "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (outlet_id, f"url-{article_id}", f"title-{article_id}", "body text", "2024-01-01", "ok"),
            )
            article_id += 1

    # Create claims: for each event-article pair, add a claim with action 'occurred'
    article_id = 1
    for event_id in event_ids:
        for outlet_id in [reuters_id, fake_x_id, fake_y_id]:
            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty) "
                "VALUES (?, ?, ?, ?)",
                (article_id, event_id, "occurred", 0.9),
            )
            article_id += 1

    conn.commit()
    conn.close()

    # Run experiment on this tiny DB
    config = {
        "db_path": str(db_path),
        "min_outlets": 2,
        "batch_size": 32,
    }

    out_dir = tmp_path / "e3_output"
    entry = run_experiment("e3", e3_isot.run, config, seed=42, out_dir=str(out_dir))

    # Check CSV exists and is valid
    csv_path = out_dir / "e3_isot.csv"
    assert csv_path.exists()

    with open(csv_path) as f:
        lines = f.readlines()

    assert lines[0].strip() == "dedup,outlet,is_real,sens,spec,reliability,n_obs"

    # Expect: 2 dedup settings × 3 outlets = 6 rows + 1 header
    assert len(lines) == 7

    # Parse and validate rows
    for line in lines[1:]:
        parts = line.strip().split(",")
        assert len(parts) == 7

        dedup = int(parts[0])
        outlet = parts[1]
        is_real = int(parts[2])
        sens = float(parts[3])
        spec = float(parts[4])
        reliability = float(parts[5])
        n_obs = int(parts[6])

        assert dedup in [0, 1]
        assert outlet in ["reuters", "fake:x", "fake:y"]
        assert is_real in [0, 1]
        assert 0.01 <= sens <= 0.99
        assert 0.01 <= spec <= 0.99
        assert 0.01 <= reliability <= 0.99
        assert n_obs >= 0

    # Check PNG exists
    png_path = out_dir / "e3_isot.png"
    assert png_path.exists()
    assert png_path.stat().st_size > 0

    # Check manifest
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()

    with open(manifest_path) as f:
        manifest = json.load(f)

    assert len(manifest) == 1
    assert manifest[0]["experiment"] == "e3"

    # Check metrics
    metrics = entry["metrics"]
    assert "auc_dedup_on" in metrics
    assert "auc_dedup_off" in metrics
    assert "real_rank_dedup_on" in metrics
    assert "mean_reliability_dedup_on" in metrics
    assert "inversion_flag" in metrics
    assert "n_outlets" in metrics

    # Validate metric ranges
    assert 0 <= metrics["auc_dedup_on"] <= 1
    assert 0 <= metrics["auc_dedup_off"] <= 1
    assert metrics["real_rank_dedup_on"] >= 1
    assert 0.01 <= metrics["mean_reliability_dedup_on"] <= 0.99
    assert isinstance(metrics["inversion_flag"], bool)
    assert metrics["n_outlets"] == 3


def test_manual_auc():
    """Test rank-based AUC computation with hand-crafted fixtures."""

    # Case 1: real clearly > all fake
    # real=[0.8], fake=[0.3, 0.6]
    # AUC = 2 pairs correct / 2 = 1.0
    results1 = [
        {"is_real": True, "reliability": 0.8},
        {"is_real": False, "reliability": 0.3},
        {"is_real": False, "reliability": 0.6},
    ]
    auc1 = e3_isot._compute_auc(results1)
    assert auc1 == 1.0

    # Case 2: real is in the middle
    # real=[0.4], fake=[0.3, 0.6]
    # real > 0.3 but < 0.6 → 1/2 = 0.5
    results2 = [
        {"is_real": True, "reliability": 0.4},
        {"is_real": False, "reliability": 0.3},
        {"is_real": False, "reliability": 0.6},
    ]
    auc2 = e3_isot._compute_auc(results2)
    assert auc2 == 0.5

    # Case 3: real clearly < all fake
    # real=[0.2], fake=[0.5, 0.8]
    # AUC = 0/2 = 0.0
    results3 = [
        {"is_real": True, "reliability": 0.2},
        {"is_real": False, "reliability": 0.5},
        {"is_real": False, "reliability": 0.8},
    ]
    auc3 = e3_isot._compute_auc(results3)
    assert auc3 == 0.0


def test_real_rank_computation():
    """Test rank computation for real outlet."""

    # Real is highest
    results1 = [
        {"is_real": True, "reliability": 0.9},
        {"is_real": False, "reliability": 0.7},
        {"is_real": False, "reliability": 0.5},
    ]
    rank1 = e3_isot._compute_real_rank(results1)
    assert rank1 == 1

    # Real is in middle
    results2 = [
        {"is_real": False, "reliability": 0.9},
        {"is_real": True, "reliability": 0.7},
        {"is_real": False, "reliability": 0.5},
    ]
    rank2 = e3_isot._compute_real_rank(results2)
    assert rank2 == 2

    # Real is lowest
    results3 = [
        {"is_real": False, "reliability": 0.9},
        {"is_real": False, "reliability": 0.7},
        {"is_real": True, "reliability": 0.5},
    ]
    rank3 = e3_isot._compute_real_rank(results3)
    assert rank3 == 3
