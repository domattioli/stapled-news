"""E4: Outlet reliability vs external MBFC ratings.

Real corpus: fnn.db with joined outlet_external_label (MBFC fact/bias).
Task: Use OnlineEM to estimate outlet reliability; score against MBFC ordinal encodings.
Metrics: Spearman rho(reliability, fact_ordinal), Spearman rho(reliability, bias_distance), bootstrap 95% CI.
"""

import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy.stats import spearmanr

from stapled.db import connect
from stapled.infer.online_em import OnlineEM


def run(config: dict, seed: int, out_dir: str) -> dict:
    """
    Run E4 external label validation experiment.

    Config keys:
        db_path: Path to fnn.db (default "fnn.db")
        min_outlets: Minimum distinct outlets per event (default 2)
        batch_size: Batch size for EM (default 32)
        min_articles_per_outlet: Minimum articles per outlet (default 5)

    Returns:
        dict with outputs (CSV, PNG paths) and metrics
    """
    # Parse config
    db_path = config.get("db_path", "fnn.db")
    min_outlets = config.get("min_outlets", 2)
    batch_size = config.get("batch_size", 32)
    min_articles_per_outlet = config.get("min_articles_per_outlet", 5)

    # Copy DB to temp file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        temp_db_path = tmp.name

    try:
        shutil.copy(db_path, temp_db_path)
        conn = connect(temp_db_path)

        # Clean suffstats/state to start fresh
        conn.execute("DELETE FROM em_suffstats")
        conn.execute("DELETE FROM reliability_snapshot")
        conn.execute("DELETE FROM em_state")
        conn.commit()

        # Get outlet IDs
        cursor = conn.execute("SELECT id, name FROM outlet ORDER BY id")
        outlet_rows = cursor.fetchall()
        outlet_ids = [row[0] for row in outlet_rows]
        outlet_info = {row[0]: {"name": row[1]} for row in outlet_rows}

        # Select event IDs with >= min_outlets distinct outlets
        cursor = conn.execute(
            """
            SELECT c.event_id FROM claim c
            JOIN article a ON c.article_id = a.id
            WHERE c.event_id IS NOT NULL
            GROUP BY c.event_id
            HAVING COUNT(DISTINCT a.outlet_id) >= ?
            ORDER BY c.event_id
            """,
            (min_outlets,),
        )
        event_ids = [row[0] for row in cursor.fetchall()]

        # Run EM with dedup_voting=True (one pass)
        em = OnlineEM(outlet_ids, conn=conn, dedup_voting=True)

        for batch_idx in range(0, len(event_ids), batch_size):
            batch_ids = event_ids[batch_idx : batch_idx + batch_size]
            result = em.e_step_batch(batch_ids)
            em.accumulate(result["batch_stats"], batch_idx // batch_size)

        # Extract EM parameters
        params = em.params()

        # Build external label metrics per outlet
        outlet_scores = _compute_outlet_scores(conn, outlet_ids, outlet_info, params, em, min_articles_per_outlet)

        # Filter outlets with sufficient articles and valid external labels
        valid_outlets = [
            s for s in outlet_scores
            if s["n_articles"] >= min_articles_per_outlet and s["fact_ordinal"] is not None and s["bias_distance"] is not None
        ]

        # Compute global metrics with bootstrap CI
        metrics = _compute_metrics(valid_outlets, len(event_ids), seed)

        # Write CSV
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        csv_path = out_path / "e4_external.csv"

        # Sort by reliability descending
        valid_outlets.sort(key=lambda s: s["reliability"], reverse=True)

        with open(csv_path, "w") as f:
            f.write("outlet,n_articles,fact,bias,sens,spec,reliability,n_obs\n")
            for s in valid_outlets:
                fact_str = s["fact"] if s["fact"] else "unknown"
                bias_str = s["bias"] if s["bias"] else "unknown"
                f.write(
                    f"{s['outlet']},{int(s['n_articles'])},{fact_str},{bias_str},"
                    f"{s['sens']:.6f},{s['spec']:.6f},{s['reliability']:.6f},"
                    f"{int(s['n_obs'])}\n"
                )

        # Create two-panel scatter plot
        png_path = _create_plot(valid_outlets, out_path)

        conn.close()

        return {
            "outputs": [str(csv_path), str(png_path)],
            "metrics": metrics,
        }

    finally:
        # Clean up temp DB
        try:
            os.remove(temp_db_path)
        except OSError:
            pass


def _encode_fact_ordinal(fact_str):
    """Encode MBFC fact as ordinal: low=0, mixed=1, high=2."""
    if fact_str is None:
        return None
    fact_lower = fact_str.lower().strip()
    if fact_lower == "low":
        return 0
    elif fact_lower == "mixed":
        return 1
    elif fact_lower == "high":
        return 2
    else:
        return None


def _encode_bias_distance(bias_str):
    """
    Encode MBFC bias as distance from center.
    center=0, center-left/center-right=1, left/right=2, extreme-left/extreme-right=3
    """
    if bias_str is None:
        return None
    bias_lower = bias_str.lower().strip()
    if bias_lower == "center":
        return 0
    elif bias_lower in ["center-left", "center-right"]:
        return 1
    elif bias_lower in ["left", "right"]:
        return 2
    elif bias_lower in ["extreme-left", "extreme-right"]:
        return 3
    else:
        return None


def _compute_outlet_scores(conn, outlet_ids, outlet_info, params, em, min_articles_per_outlet):
    """
    Compute external label metrics for each outlet.

    Returns:
        list of dicts: [{outlet, n_articles, fact, bias, fact_ordinal, bias_distance, sens, spec, reliability, n_obs}, ...]
    """
    results = []

    for outlet_id in outlet_ids:
        outlet_name = outlet_info[outlet_id]["name"]
        param = params[outlet_id]
        n_obs = em.n_obs[outlet_id]

        # Count articles for this outlet
        cursor = conn.execute(
            "SELECT COUNT(*) FROM article WHERE outlet_id = ?",
            (outlet_id,),
        )
        n_articles = cursor.fetchone()[0]

        # Join to external label by domain (outlet.name = domain)
        cursor = conn.execute(
            "SELECT fact, bias FROM outlet_external_label WHERE domain = ?",
            (outlet_name,),
        )
        row = cursor.fetchone()
        fact = None
        bias = None
        fact_ordinal = None
        bias_distance = None

        if row:
            fact = row[0]
            bias = row[1]
            fact_ordinal = _encode_fact_ordinal(fact)
            bias_distance = _encode_bias_distance(bias)

        results.append({
            "outlet": outlet_name,
            "n_articles": n_articles,
            "fact": fact,
            "bias": bias,
            "fact_ordinal": fact_ordinal,
            "bias_distance": bias_distance,
            "sens": param["sens"],
            "spec": param["spec"],
            "reliability": param["reliability"],
            "n_obs": n_obs,
        })

    return results


def _compute_metrics(valid_outlets, n_events_used, seed):
    """Compute Spearman rho metrics with bootstrap 95% CI."""
    metrics = {
        "n_outlets_joined": len(valid_outlets),
        "n_events_used": n_events_used,
    }

    if len(valid_outlets) < 2:
        metrics["spearman_fact"] = None
        metrics["spearman_fact_ci_lower"] = None
        metrics["spearman_fact_ci_upper"] = None
        metrics["spearman_bias_abs"] = None
        metrics["spearman_bias_abs_ci_lower"] = None
        metrics["spearman_bias_abs_ci_upper"] = None
        return metrics

    # Spearman rho: reliability vs fact_ordinal
    reliabilities = np.array([s["reliability"] for s in valid_outlets])
    fact_ordinals = np.array([s["fact_ordinal"] for s in valid_outlets])
    bias_distances = np.array([s["bias_distance"] for s in valid_outlets])

    rho_fact, _ = spearmanr(reliabilities, fact_ordinals)
    metrics["spearman_fact"] = float(rho_fact) if not np.isnan(rho_fact) else None

    rho_bias, _ = spearmanr(reliabilities, bias_distances)
    metrics["spearman_bias_abs"] = float(rho_bias) if not np.isnan(rho_bias) else None

    # Bootstrap 95% CI for Spearman fact
    rng = np.random.default_rng(seed)
    n_outlets = len(valid_outlets)
    n_boot = 1000
    boot_rhos_fact = []
    boot_rhos_bias = []

    for _ in range(n_boot):
        indices = rng.integers(0, n_outlets, size=n_outlets)
        boot_rel = reliabilities[indices]
        boot_fact = fact_ordinals[indices]
        boot_bias = bias_distances[indices]

        rho_b_fact, _ = spearmanr(boot_rel, boot_fact)
        rho_b_bias, _ = spearmanr(boot_rel, boot_bias)

        if not np.isnan(rho_b_fact):
            boot_rhos_fact.append(rho_b_fact)
        if not np.isnan(rho_b_bias):
            boot_rhos_bias.append(rho_b_bias)

    if boot_rhos_fact:
        ci_lower_fact = np.percentile(boot_rhos_fact, 2.5)
        ci_upper_fact = np.percentile(boot_rhos_fact, 97.5)
        metrics["spearman_fact_ci_lower"] = float(ci_lower_fact)
        metrics["spearman_fact_ci_upper"] = float(ci_upper_fact)
    else:
        metrics["spearman_fact_ci_lower"] = None
        metrics["spearman_fact_ci_upper"] = None

    if boot_rhos_bias:
        ci_lower_bias = np.percentile(boot_rhos_bias, 2.5)
        ci_upper_bias = np.percentile(boot_rhos_bias, 97.5)
        metrics["spearman_bias_abs_ci_lower"] = float(ci_lower_bias)
        metrics["spearman_bias_abs_ci_upper"] = float(ci_upper_bias)
    else:
        metrics["spearman_bias_abs_ci_lower"] = None
        metrics["spearman_bias_abs_ci_upper"] = None

    return metrics


def _create_plot(valid_outlets, out_path):
    """Create fivethirtyeight two-panel scatter: reliability vs fact_ordinal and bias_distance."""
    import matplotlib as mpl

    mpl.rcParams.update({
        'figure.facecolor': '#f0f0f0',
        'axes.facecolor': '#f0f0f0',
        'font.family': 'DejaVu Sans',
        'axes.titlesize': 12,
        'axes.titleweight': 'bold',
        'axes.grid': True,
        'grid.color': '#cccccc',
        'grid.linestyle': '-',
        'grid.linewidth': 0.5,
    })

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(14, 5))

    reliabilities = np.array([s["reliability"] for s in valid_outlets])
    fact_ordinals = np.array([s["fact_ordinal"] for s in valid_outlets])
    bias_distances = np.array([s["bias_distance"] for s in valid_outlets])

    # Panel 1: reliability vs fact_ordinal
    # Add jitter to ordinals
    fact_jitter = fact_ordinals + np.random.normal(0, 0.05, len(fact_ordinals))
    ax1.scatter(fact_jitter, reliabilities, s=100, alpha=0.6, color="#1f77b4", edgecolors="black", linewidth=1)

    rho_fact, _ = spearmanr(reliabilities, fact_ordinals)
    rho_fact_text = f"{rho_fact:.3f}" if not np.isnan(rho_fact) else "N/A"

    ax1.set_xlabel("MBFC Fact-Check Rating (0=low, 1=mixed, 2=high)", fontsize=10)
    ax1.set_ylabel("Estimated Reliability", fontsize=10)
    ax1.set_title(f"Reliability vs Fact Rating (ρ = {rho_fact_text})", fontsize=12, fontweight="bold")
    ax1.set_xticks([0, 1, 2])

    # Panel 2: reliability vs bias_distance
    bias_jitter = bias_distances + np.random.normal(0, 0.05, len(bias_distances))
    ax2.scatter(bias_jitter, reliabilities, s=100, alpha=0.6, color="#ff7f0e", edgecolors="black", linewidth=1)

    rho_bias, _ = spearmanr(reliabilities, bias_distances)
    rho_bias_text = f"{rho_bias:.3f}" if not np.isnan(rho_bias) else "N/A"

    ax2.set_xlabel("MBFC Bias Distance from Center (0=center, 3=extreme)", fontsize=10)
    ax2.set_ylabel("Estimated Reliability", fontsize=10)
    ax2.set_title(f"Reliability vs Bias Distance (ρ = {rho_bias_text})", fontsize=12, fontweight="bold")
    ax2.set_xticks([0, 1, 2, 3])

    fig.suptitle("E4: Outlet Reliability vs MBFC External Labels", fontsize=14, fontweight="bold", y=1.02)

    plt.tight_layout()
    png_path = out_path / "e4_external.png"
    plt.savefig(png_path, dpi=100, bbox_inches="tight")
    plt.close()

    return str(png_path)
