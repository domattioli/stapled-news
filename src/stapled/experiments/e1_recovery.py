"""E1: Synthetic parameter recovery experiment."""

import os
import tempfile
from pathlib import Path

import numpy as np
import yaml
from scipy.stats import spearmanr

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from stapled.db import connect
from stapled.synth.generator import generate
from stapled.infer.online_em import OnlineEM
from stapled.baselines import run_baseline


def run(config: dict, seed: int, out_dir: str) -> dict:
    """
    Run E1 synthetic parameter recovery experiment.

    Config keys:
        n_seeds: Number of seeds to run (default 30)
        quick: If True, override n_seeds=2
        synth_config_path: Path to synth config YAML (default "configs/synth-baseline.yml")

    Returns:
        dict with outputs (CSV, PNG paths) and metrics
    """
    # Parse config
    n_seeds = config.get("n_seeds", 30)
    quick = config.get("quick", False)
    if quick:
        n_seeds = 2
    synth_config_path = config.get("synth_config_path", "configs/synth-baseline.yml")

    # Load synth config
    synth_config = _load_synth_config(synth_config_path)

    # Run experiment per seed
    results = []
    for s in range(n_seeds):
        seed_results = _run_seed(s, seed, synth_config)
        results.extend(seed_results)

    # Write CSV
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    csv_path = out_path / "e1_recovery.csv"

    # Sort deterministically
    results.sort(key=lambda r: (r["seed"], r["method"]))

    with open(csv_path, "w") as f:
        f.write("seed,method,rho\n")
        for r in results:
            f.write(f"{r['seed']},{r['method']},{r['rho']:.6f}\n")

    # Compute summary statistics
    metrics = _compute_metrics(results)

    # Create plot
    png_path = _create_plot(results, n_seeds, out_path)

    return {
        "outputs": [str(csv_path), str(png_path)],
        "metrics": metrics,
    }


def _load_synth_config(path: str) -> dict:
    """Load synth config from YAML file."""
    with open(path, "r") as f:
        return yaml.safe_load(f)


def _run_seed(seed_idx: int, base_seed: int, synth_config: dict) -> list:
    """
    Run experiment for one seed.
    Returns list of dicts: [{seed, method, rho}, ...]
    """
    actual_seed = base_seed + seed_idx

    # Create temp DB
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name

    try:
        conn = connect(db_path)

        # Generate synthetic corpus
        corpus_id = generate(conn, synth_config, seed=actual_seed)

        # Load planted reliability parameters from outlet_truth table
        cursor = conn.execute(
            "SELECT outlet_id, reliability FROM outlet_truth WHERE corpus_id = ?",
            (corpus_id,),
        )
        planted = {}
        for outlet_id, reliability in cursor.fetchall():
            planted[outlet_id] = reliability

        # Get all event IDs
        cursor = conn.execute(
            "SELECT id FROM event WHERE corpus_id = ? ORDER BY id",
            (corpus_id,),
        )
        event_ids = [row[0] for row in cursor.fetchall()]

        # Get all outlet IDs
        cursor = conn.execute("SELECT id FROM outlet WHERE is_synthetic = 1 ORDER BY id")
        outlet_ids = [row[0] for row in cursor.fetchall()]

        results = []

        # Run OnlineEM with dedup=True
        em_dedup = OnlineEM(outlet_ids, conn=conn, dedup_voting=True)
        _run_em(em_dedup, event_ids, 8)
        est_params = em_dedup.params()
        rho = _compute_rho(planted, est_params)
        results.append({"seed": seed_idx, "method": "online_em_dedup", "rho": rho})

        # Run OnlineEM with dedup=False
        conn.execute("DELETE FROM em_suffstats")
        conn.execute("DELETE FROM em_state")
        conn.execute("DELETE FROM reliability_snapshot")
        conn.commit()

        em_nodedup = OnlineEM(outlet_ids, conn=conn, dedup_voting=False)
        _run_em(em_nodedup, event_ids, 8)
        est_params = em_nodedup.params()
        rho = _compute_rho(planted, est_params)
        results.append({"seed": seed_idx, "method": "online_em_nodedup", "rho": rho})

        # Build events list for baselines
        events = _build_events_for_baselines(conn, event_ids)

        # Run baselines
        for baseline_name in ["majority", "weighted_majority", "batch_ds"]:
            baseline_result = run_baseline(baseline_name, events)
            outlet_params = baseline_result["outlet_params"]
            rho = _compute_rho(planted, outlet_params)
            results.append({"seed": seed_idx, "method": baseline_name, "rho": rho})

        conn.close()
        return results

    finally:
        # Clean up temp DB
        try:
            os.remove(db_path)
        except OSError:
            pass


def _run_em(em, event_ids: list, batch_size: int):
    """Run EM over event IDs in batches."""
    for batch_idx in range(0, len(event_ids), batch_size):
        batch_ids = event_ids[batch_idx : batch_idx + batch_size]
        result = em.e_step_batch(batch_ids)
        em.accumulate(result["batch_stats"], batch_idx // batch_size)


def _build_events_for_baselines(conn, event_ids: list) -> list:
    """Build events list for baseline methods."""
    events = []
    for event_id in event_ids:
        cursor = conn.execute(
            """
            SELECT a.outlet_id,
                   CASE WHEN c.action NOT LIKE 'not-%' THEN 1 ELSE 0 END as observation,
                   COALESCE(c.certainty, 0.5) as certainty
            FROM claim c
            JOIN article a ON c.article_id = a.id
            WHERE c.event_id = ?
            """,
            (event_id,),
        )
        claims = []
        for outlet_id, observation, certainty in cursor.fetchall():
            claims.append({
                "outlet_id": outlet_id,
                "observation": observation,
                "certainty": certainty,
            })

        if claims:
            events.append({
                "event_id": event_id,
                "claims": claims,
            })

    return events


def _compute_rho(planted: dict, est_params: dict) -> float:
    """
    Compute Spearman rho between planted and estimated reliability.

    planted: {outlet_id: reliability}
    est_params: {outlet_id: {"sens", "spec", "reliability", "bias"}}
    """
    planted_list = []
    est_list = []

    for outlet_id in planted:
        if outlet_id in est_params:
            planted_list.append(planted[outlet_id])
            reliability = est_params[outlet_id].get(
                "reliability",
                (est_params[outlet_id]["sens"] + est_params[outlet_id]["spec"]) / 2,
            )
            est_list.append(reliability)

    if len(planted_list) < 2:
        return 0.0

    rho, _ = spearmanr(planted_list, est_list)
    # Handle NaN (e.g., when all values are the same)
    return float(rho) if not np.isnan(rho) else 0.0


def _compute_metrics(results: list) -> dict:
    """Compute summary metrics from all results."""
    by_method = {}
    for r in results:
        method = r["method"]
        if method not in by_method:
            by_method[method] = []
        by_method[method].append(r["rho"])

    metrics = {}
    mean_rho = {}
    ci95 = {}

    for method, rhos in by_method.items():
        rhos_arr = np.array(rhos)
        mean_rho[method] = float(np.mean(rhos_arr))
        # 95% CI using percentiles
        ci_low = float(np.percentile(rhos_arr, 2.5))
        ci_high = float(np.percentile(rhos_arr, 97.5))
        ci95[method] = (ci_low, ci_high)

    metrics["mean_rho"] = mean_rho
    metrics["ci95"] = {k: {"low": v[0], "high": v[1]} for k, v in ci95.items()}

    # Gate check
    online_em_dedup_rhos = np.array(by_method.get("online_em_dedup", [0.0]))
    gate_pass = float(np.mean(online_em_dedup_rhos)) >= 0.8
    metrics["gate_rho_ge_0.8"] = gate_pass

    return metrics


def _create_plot(results: list, n_seeds: int, out_path: Path) -> str:
    """Create box plot of rho by method."""
    import matplotlib as mpl

    by_method = {}
    for r in results:
        method = r["method"]
        if method not in by_method:
            by_method[method] = []
        by_method[method].append(r["rho"])

    # Ensure consistent method order
    methods = ["online_em_dedup", "online_em_nodedup", "majority", "weighted_majority", "batch_ds"]
    methods = [m for m in methods if m in by_method]

    # Fivethirtyeight style
    mpl.rcParams.update({
        'figure.facecolor': '#f0f0f0',
        'axes.facecolor': '#f0f0f0',
        'font.family': 'DejaVu Sans',
        'axes.titlesize': 14,
        'axes.titleweight': 'bold',
        'axes.grid': True,
        'grid.color': '#cccccc',
        'grid.linestyle': '-',
        'grid.linewidth': 0.5,
    })

    fig, ax = plt.subplots(figsize=(10, 6))

    # Create box plot
    data = [by_method[m] for m in methods]
    bp = ax.boxplot(data, labels=methods, patch_artist=True)

    # Styling
    for patch in bp["boxes"]:
        patch.set_facecolor("#5b9bd5")
        patch.set_alpha(0.7)
    for whisker in bp["whiskers"]:
        whisker.set(color="#555555", linewidth=1.5)
    for cap in bp["caps"]:
        cap.set(color="#555555", linewidth=1.5)
    for median in bp["medians"]:
        median.set(color="#ff7f0e", linewidth=2)

    ax.set_ylabel("Spearman ρ (Planted vs. Estimated Reliability)", fontsize=11)
    ax.set_xlabel("Method", fontsize=11)
    ax.set_title("E1: Synthetic Parameter Recovery", fontsize=14, fontweight="bold")
    ax.text(
        0.5,
        -0.15,
        f"n={n_seeds} seeds",
        transform=ax.transAxes,
        ha="center",
        fontsize=10,
        style="italic",
    )

    plt.tight_layout()
    png_path = out_path / "e1_recovery.png"
    plt.savefig(png_path, dpi=100, bbox_inches="tight")
    plt.close()

    return str(png_path)
