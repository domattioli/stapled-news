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

    # Git provenance: repo root resolved from this file, not a hardcoded path
    git_sha = "unknown"
    git_dirty = None
    try:
        git_root = (
            subprocess.check_output(
                ["git", "rev-parse", "--show-toplevel"],
                cwd=str(Path(__file__).resolve().parent),
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
        git_sha = (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=git_root, stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
        git_dirty = bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=git_root, stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except Exception:
        pass

    # Input DB provenance
    db_sha256 = None
    db_path = config.get("db_path")
    if db_path and Path(db_path).is_file():
        h = hashlib.sha256()
        with open(db_path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        db_sha256 = h.hexdigest()

    # Compute config hash
    config_json = json.dumps(config, sort_keys=True)
    config_hash = hashlib.sha256(config_json.encode()).hexdigest()

    # Build manifest entry
    entry = {
        "experiment": experiment_id,
        "git_sha": git_sha,
        "git_dirty": git_dirty,
        "db_sha256": db_sha256,
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
