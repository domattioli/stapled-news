"""E3b: Multi-outlet reliability validation using held-out labels.

Real corpus: fnn.db with labeled articles and multi-outlet events.
Task: Use OnlineEM to estimate outlet reliability; score using label_fake_share.
Metrics: Spearman rho(reliability, 1-label_fake_share), AUC separating mostly-real vs mostly-fake.
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
    Run E3b multi-outlet reliability experiment with held-out labels.

    Config keys:
        db_path: Path to fnn.db (default "fnn.db")
        min_outlets: Minimum distinct outlets per event (default 2)
        batch_size: Batch size for EM (default 32)
        min_articles_per_outlet: Minimum labeled articles per outlet (default 5)

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

        # Build label-based metrics per outlet
        outlet_scores = _compute_outlet_scores(conn, outlet_ids, outlet_info, params, em, min_articles_per_outlet)

        # Filter outlets with sufficient labeled articles
        valid_outlets = [s for s in outlet_scores if s["n_labeled_articles"] >= min_articles_per_outlet]

        # Compute global metrics
        metrics = _compute_metrics(valid_outlets, len(event_ids))

        # Write CSV
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        csv_path = out_path / "e3b_fnn.csv"

        # Sort by reliability descending
        valid_outlets.sort(key=lambda s: s["reliability"], reverse=True)

        with open(csv_path, "w") as f:
            f.write("outlet,n_articles,fake_share,sens,spec,reliability,n_obs\n")
            for s in valid_outlets:
                f.write(
                    f"{s['outlet']},{int(s['n_labeled_articles'])},{s['fake_share']:.6f},"
                    f"{s['sens']:.6f},{s['spec']:.6f},{s['reliability']:.6f},"
                    f"{int(s['n_obs'])}\n"
                )

        # Create scatter plot
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


def _compute_outlet_scores(conn, outlet_ids, outlet_info, params, em, min_articles_per_outlet):
    """
    Compute label_fake_share and reliability for each outlet.

    Returns:
        list of dicts: [{outlet, n_labeled_articles, fake_share, sens, spec, reliability, n_obs}, ...]
    """
    results = []

    for outlet_id in outlet_ids:
        outlet_name = outlet_info[outlet_id]["name"]
        param = params[outlet_id]
        n_obs = em.n_obs[outlet_id]

        # Count labeled articles by label for this outlet
        cursor = conn.execute(
            """
            SELECT COUNT(*) FILTER (WHERE al.label = 'fake') as fake_count,
                   COUNT(*) as total_count
            FROM article a
            LEFT JOIN article_label al ON a.id = al.article_id
            WHERE a.outlet_id = ? AND al.label IS NOT NULL
            """,
            (outlet_id,),
        )
        row = cursor.fetchone()
        fake_count = row[0] if row[0] is not None else 0
        total_count = row[1] if row[1] is not None else 0

        if total_count > 0:
            fake_share = float(fake_count) / float(total_count)
        else:
            fake_share = 0.0

        results.append({
            "outlet": outlet_name,
            "n_labeled_articles": total_count,
            "fake_share": fake_share,
            "sens": param["sens"],
            "spec": param["spec"],
            "reliability": param["reliability"],
            "n_obs": n_obs,
        })

    return results


def _compute_metrics(valid_outlets, n_events_used):
    """Compute Spearman rho and AUC metrics."""
    metrics = {
        "n_outlets_scored": len(valid_outlets),
        "n_events_used": n_events_used,
    }

    if len(valid_outlets) < 2:
        # Not enough outlets for Spearman
        metrics["spearman_rho"] = None
        metrics["spearman_pval"] = None
        metrics["auc_mostly_fake"] = 0.5
        return metrics

    # Compute Spearman rho: reliability vs (1 - fake_share)
    reliabilities = np.array([s["reliability"] for s in valid_outlets])
    real_shares = np.array([1.0 - s["fake_share"] for s in valid_outlets])

    rho, pval = spearmanr(reliabilities, real_shares)
    metrics["spearman_rho"] = float(rho) if not np.isnan(rho) else None
    metrics["spearman_pval"] = float(pval) if not np.isnan(pval) else None

    # Compute AUC: mostly-real (fake_share < 0.5) vs mostly-fake (>= 0.5)
    mostly_real = [s["reliability"] for s in valid_outlets if s["fake_share"] < 0.5]
    mostly_fake = [s["reliability"] for s in valid_outlets if s["fake_share"] >= 0.5]

    if mostly_real and mostly_fake:
        auc = _compute_auc(mostly_real, mostly_fake)
        metrics["auc_mostly_fake"] = auc
    else:
        metrics["auc_mostly_fake"] = 0.5

    return metrics


def _compute_auc(mostly_real, mostly_fake):
    """
    Compute AUC separating mostly-real vs mostly-fake by reliability.

    Args:
        mostly_real: list of reliability scores for mostly-real outlets
        mostly_fake: list of reliability scores for mostly-fake outlets

    Returns:
        float in [0, 1]
    """
    # Fraction of (real, fake) pairs where real > fake
    n_pairs = len(mostly_real) * len(mostly_fake)
    if n_pairs == 0:
        return 0.5

    n_correct = 0
    for r_rel in mostly_real:
        for f_rel in mostly_fake:
            if r_rel > f_rel:
                n_correct += 1

    return float(n_correct) / n_pairs


def _create_plot(valid_outlets, out_path):
    """Create fivethirtyeight scatter plot: x=fake_share, y=reliability."""
    import matplotlib as mpl

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

    # Scatter: fake_share vs reliability
    fake_shares = [s["fake_share"] for s in valid_outlets]
    reliabilities = [s["reliability"] for s in valid_outlets]

    ax.scatter(fake_shares, reliabilities, s=100, alpha=0.6, color="#1f77b4", edgecolors="black", linewidth=1)

    # Compute Spearman for title
    if len(valid_outlets) >= 2:
        rho, _ = spearmanr(reliabilities, fake_shares)
        rho_text = f"{rho:.3f}" if not np.isnan(rho) else "N/A"
    else:
        rho_text = "N/A"

    ax.set_xlabel("Fraction of Articles Labeled 'Fake'", fontsize=11)
    ax.set_ylabel("Estimated Reliability", fontsize=11)
    ax.set_title(f"E3b: Outlet Reliability vs Label Fake Share (ρ = {rho_text})", fontsize=14, fontweight="bold")

    # Annotate outlets
    for s in valid_outlets:
        ax.annotate(s["outlet"], (s["fake_share"], s["reliability"]), fontsize=8, alpha=0.7)

    plt.tight_layout()
    png_path = out_path / "e3b_fnn.png"
    plt.savefig(png_path, dpi=100, bbox_inches="tight")
    plt.close()

    return str(png_path)
