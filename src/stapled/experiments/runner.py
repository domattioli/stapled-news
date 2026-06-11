"""Experiment runner with manifest tracking."""

import json
import subprocess
import hashlib
from datetime import datetime, timezone
from pathlib import Path


def run_experiment(
    experiment_id: str, fn, config: dict, seed: int, out_dir: str = "results"
) -> dict:
    """
    Run an experiment and track results in manifest.

    Args:
        experiment_id: Unique experiment identifier
        fn: Callable that takes (config, seed, out_dir) and returns
            {"outputs": [paths], "metrics": {...}}
        config: Configuration dict passed to fn
        seed: Random seed
        out_dir: Output directory for results

    Returns:
        Manifest entry dict with experiment metadata
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Run the experiment function
    result = fn(config, seed, out_dir)

    # Get git SHA
    try:
        git_sha = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd="/home/user/stapled-news")
            .decode()
            .strip()
        )
    except Exception:
        git_sha = "unknown"

    # Compute config hash
    config_json = json.dumps(config, sort_keys=True)
    config_hash = hashlib.sha256(config_json.encode()).hexdigest()

    # Build manifest entry
    entry = {
        "experiment": experiment_id,
        "git_sha": git_sha,
        "seed": seed,
        "config_hash": config_hash,
        "outputs": result.get("outputs", []),
        "metrics": result.get("metrics", {}),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }

    # Load/create manifest
    manifest_path = out_path / "manifest.json"
    if manifest_path.exists():
        with open(manifest_path, "r") as f:
            manifest = json.load(f)
    else:
        manifest = []

    # Append entry
    manifest.append(entry)

    # Write manifest
    with open(manifest_path, "w") as f:
        json.dump(manifest, f, indent=2)

    return entry
