"""Unit tests for E2 syndication experiment."""

import json
import tempfile

from stapled.experiments import e2_syndication
from stapled.experiments.runner import run_experiment
from stapled.db import connect
from stapled.synth.generator import generate
from stapled.ingest.dedup import dedup_articles


def test_e2_quick_runs(tmp_path):
    """Test e2 experiment with quick mode (2 multiplicities, 3 seeds)."""

    # Create minimal synth config in temp dir
    synth_config_path = tmp_path / "synth.yml"
    synth_config_path.write_text(
        """
outlets:
  - name: "reliable"
    reliability: 0.9
    bias: 0.0
    calibration: 1.0
  - name: "moderate"
    reliability: 0.7
    bias: 0.0
    calibration: 1.0
  - name: "unreliable"
    reliability: 0.2
    bias: 0.0
    calibration: 1.0

n_events: 8
articles_per_event_per_outlet: 1
"""
    )

    config = {
        "quick": True,
        "synth_config_path": str(synth_config_path),
        "perturb": False,  # Just exact mode for speed
    }

    out_dir = tmp_path / "e2_output"
    entry = run_experiment("e2", e2_syndication.run, config, seed=42, out_dir=str(out_dir))

    # Check CSV exists
    csv_path = out_dir / "e2_syndication.csv"
    assert csv_path.exists()

    # Parse CSV
    with open(csv_path) as f:
        lines = f.readlines()

    assert lines[0].strip() == "mode,multiplicity,seed,dedup,rho,wire_reliability_est"
    # 1 mode × 2 multiplicities × 3 seeds × 2 dedup settings = 12 rows + header
    assert len(lines) == 13

    # Check each row is valid
    for line in lines[1:]:
        parts = line.strip().split(",")
        assert len(parts) == 6
        mode = parts[0]
        multiplicity = int(parts[1])
        seed_idx = int(parts[2])
        dedup = parts[3] == "True"
        rho = float(parts[4])
        wire_est = float(parts[5])

        assert mode == "exact"
        assert multiplicity in [1, 5]
        assert 0 <= seed_idx < 3
        assert isinstance(dedup, bool)
        assert -1 <= rho <= 1
        assert 0 <= wire_est <= 1

    # Check PNG exists
    png_path = out_dir / "e2_syndication.png"
    assert png_path.exists()
    assert png_path.stat().st_size > 0

    # Check manifest
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()

    with open(manifest_path) as f:
        manifest = json.load(f)

    assert len(manifest) == 1
    assert manifest[0]["experiment"] == "e2"

    # Check metrics
    metrics = entry["metrics"]
    assert "mean_rho_by_m" in metrics
    assert "distortion_at_max_m" in metrics
    assert "dedup_on" in metrics["mean_rho_by_m"]
    assert "dedup_off" in metrics["mean_rho_by_m"]


def test_injection_creates_duplicates(tmp_path):
    """Test that syndication injection creates correct number of duplicates."""

    # Create small synthetic corpus
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        conn = connect(db_path)

        # Generate small synthetic corpus
        synth_config = {
            "outlets": [
                {"name": "outlet-a", "reliability": 0.9, "bias": 0.0, "calibration": 1.0},
                {"name": "outlet-b", "reliability": 0.7, "bias": 0.0, "calibration": 1.0},
                {"name": "outlet-c", "reliability": 0.2, "bias": 0.0, "calibration": 1.0},
            ],
            "n_events": 4,
            "articles_per_event_per_outlet": 1,
        }

        _ = generate(conn, synth_config, seed=42)

        # Get outlet IDs
        cursor = conn.execute(
            "SELECT id, name FROM outlet WHERE is_synthetic = 1 ORDER BY name"
        )
        outlets = {name: oid for oid, name in cursor.fetchall()}

        # Count initial articles from unreliable outlet (wire)
        wire_id = outlets["outlet-c"]
        cursor = conn.execute(
            "SELECT COUNT(*) FROM article WHERE outlet_id = ?", (wire_id,)
        )
        initial_count = cursor.fetchone()[0]
        assert initial_count == 4  # 4 events, 1 article per outlet per event

        # Count total articles before injection
        cursor = conn.execute("SELECT COUNT(*) FROM article")
        total_before = cursor.fetchone()[0]
        assert total_before == 12  # 3 outlets × 4 events

        # Inject syndication with multiplicity=5
        other_outlet_ids = [outlets["outlet-a"], outlets["outlet-b"]]
        rng = __import__("numpy").random.default_rng(42)
        count_inserted = e2_syndication._inject_syndication(
            conn, wire_id, other_outlet_ids, 5, "exact", rng
        )

        # Verify count: m-1 = 4 duplicates per wire article, 4 wire articles
        assert count_inserted == 16

        # Verify total articles grew
        cursor = conn.execute("SELECT COUNT(*) FROM article")
        total_after = cursor.fetchone()[0]
        assert total_after == 28  # 12 + 16

        # Run dedup
        clusters = dedup_articles(conn)

        # Check that exact duplicates are clustered
        # Each of 4 wire articles created 4 exact clones, so 4 clusters of 5
        # (1 original + 4 clones each)
        assert clusters >= 4

        # Verify dedup_cluster_id is set for clustered articles
        cursor = conn.execute(
            "SELECT COUNT(*) FROM article WHERE dedup_cluster_id IS NOT NULL"
        )
        clustered_count = cursor.fetchone()[0]
        assert clustered_count > 0

        conn.close()

    finally:
        import os
        try:
            os.remove(db_path)
        except OSError:
            pass


def test_perturb_text():
    """Test that text perturbation works as expected."""
    import numpy as np

    text = "This is a test document with some words to perturb in place."
    rng = np.random.default_rng(42)

    perturbed = e2_syndication._perturb_text(text, rng)

    # Should not be identical (usually)
    # Note: with small text, there's a small chance of no change
    # but for this test, we just check it's still valid text
    assert isinstance(perturbed, str)
    assert len(perturbed) > 0
    words_orig = text.split()
    words_pert = perturbed.split()
    # Perturbed should have same or more words (due to appends)
    assert len(words_pert) >= len(words_orig)


def test_compute_rho_empty_planted():
    """Test rho computation with edge cases."""
    # Empty planted
    rho = e2_syndication._compute_rho({}, {})
    assert rho == 0.0

    # Single outlet
    planted = {1: 0.8}
    est = {1: {"reliability": 0.75}}
    rho = e2_syndication._compute_rho(planted, est)
    assert rho == 0.0  # Need at least 2 for spearmanr

    # Two outlets
    planted = {1: 0.8, 2: 0.6}
    est = {1: {"reliability": 0.75}, 2: {"reliability": 0.65}}
    rho = e2_syndication._compute_rho(planted, est)
    assert -1 <= rho <= 1
    # In this case, the ordering is preserved, so rho should be high
    assert rho > 0.5
