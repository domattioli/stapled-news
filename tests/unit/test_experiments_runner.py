"""Unit tests for experiments package."""

import json

from stapled.experiments.runner import run_experiment
from stapled.experiments import e1_recovery


def test_manifest_append(tmp_path):
    """Test that manifest.json is created and appended correctly."""

    def dummy_fn(config, seed, out_dir):
        return {
            "outputs": [f"{out_dir}/output.txt"],
            "metrics": {"dummy_metric": 42},
        }

    # First run
    run_experiment("test_exp", dummy_fn, {"a": 1}, seed=42, out_dir=str(tmp_path))

    manifest_path = tmp_path / "manifest.json"
    assert manifest_path.exists()

    with open(manifest_path) as f:
        manifest = json.load(f)

    assert len(manifest) == 1
    assert manifest[0]["experiment"] == "test_exp"
    assert manifest[0]["seed"] == 42
    assert manifest[0]["metrics"] == {"dummy_metric": 42}
    assert "git_sha" in manifest[0]
    assert "config_hash" in manifest[0]
    assert "timestamp" in manifest[0]

    # Second run
    run_experiment("test_exp", dummy_fn, {"a": 2}, seed=43, out_dir=str(tmp_path))

    with open(manifest_path) as f:
        manifest = json.load(f)

    assert len(manifest) == 2
    assert manifest[1]["experiment"] == "test_exp"
    assert manifest[1]["seed"] == 43


def test_config_hash_stable(tmp_path):
    """Test that same config produces same hash, different config produces different hash."""

    def dummy_fn(config, seed, out_dir):
        return {"outputs": [], "metrics": {}}

    config_a = {"x": 1, "y": 2}
    config_b = {"y": 2, "x": 1}  # Same but different order
    config_c = {"x": 1, "y": 3}  # Different value

    entry_a = run_experiment("test", dummy_fn, config_a, 42, out_dir=str(tmp_path))
    entry_b = run_experiment("test", dummy_fn, config_b, 42, out_dir=str(tmp_path))
    entry_c = run_experiment("test", dummy_fn, config_c, 42, out_dir=str(tmp_path))

    # a and b should have same hash (same content, different order)
    assert entry_a["config_hash"] == entry_b["config_hash"]

    # a and c should have different hash
    assert entry_a["config_hash"] != entry_c["config_hash"]


def test_e1_quick_runs(tmp_path):
    """Test e1 experiment with quick mode (2 seeds)."""

    # Create minimal synth config in temp dir
    synth_config_path = tmp_path / "synth.yml"
    synth_config_path.write_text(
        """
outlets:
  - name: "outlet-1"
    reliability: 0.8
    bias: 0.0
    calibration: 1.0
  - name: "outlet-2"
    reliability: 0.7
    bias: 0.1
    calibration: 0.9
  - name: "outlet-3"
    reliability: 0.6
    bias: -0.1
    calibration: 1.1

n_events: 10
articles_per_event_per_outlet: 1
"""
    )

    config = {
        "quick": True,
        "synth_config_path": str(synth_config_path),
    }

    out_dir = tmp_path / "e1_output"
    entry = run_experiment("e1", e1_recovery.run, config, seed=42, out_dir=str(out_dir))

    # Check CSV exists
    csv_path = out_dir / "e1_recovery.csv"
    assert csv_path.exists()

    # Parse CSV
    with open(csv_path) as f:
        lines = f.readlines()

    assert lines[0].strip() == "seed,method,rho"
    # 2 seeds × 5 methods = 10 rows + header
    assert len(lines) == 11

    # Check each row is valid
    for line in lines[1:]:
        parts = line.strip().split(",")
        assert len(parts) == 3
        seed_idx = int(parts[0])
        method = parts[1]
        rho = float(parts[2])

        assert 0 <= seed_idx < 2
        assert method in ["online_em_dedup", "online_em_nodedup", "majority", "weighted_majority", "batch_ds"]
        assert -1 <= rho <= 1

    # Check PNG exists
    png_path = out_dir / "e1_recovery.png"
    assert png_path.exists()
    assert png_path.stat().st_size > 0

    # Check manifest
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()

    with open(manifest_path) as f:
        manifest = json.load(f)

    assert len(manifest) == 1
    assert manifest[0]["experiment"] == "e1"

    # Check metrics
    metrics = entry["metrics"]
    assert "mean_rho" in metrics
    assert "ci95" in metrics
    assert "gate_rho_ge_0.8" in metrics

    assert "online_em_dedup" in metrics["mean_rho"]
    online_em_dedup_mean = metrics["mean_rho"]["online_em_dedup"]
    assert isinstance(online_em_dedup_mean, float)
    assert -1 <= online_em_dedup_mean <= 1
