"""E3: ISOT real-data experiment on outlet reliability.

Real corpus: stream.db with one real outlet (reuters) and six synthetic outlets (fake:*).
Task: Use OnlineEM to estimate outlet reliability on real dedup/claim data.
Scoring: Separate real vs synthetic via estimated reliability, compute AUC.
"""

import os
import shutil
import tempfile
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from stapled.db import connect
from stapled.infer.online_em import OnlineEM


def run(config: dict, seed: int, out_dir: str) -> dict:
    """
    Run E3 ISOT real-data experiment.

    Config keys:
        db_path: Path to stream.db (default "stream.db")
        min_outlets: Minimum distinct outlets per event (default 2)
        batch_size: Batch size for EM (default 32)

    Returns:
        dict with outputs (CSV, PNG paths) and metrics
    """
    # Parse config
    db_path = config.get("db_path", "stream.db")
    min_outlets = config.get("min_outlets", 2)
    batch_size = config.get("batch_size", 32)

    # Copy DB to temp file (avoid mutating stream.db)
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

        # Get outlet IDs and outlet metadata (name, is_synthetic)
        cursor = conn.execute("SELECT id, name, is_synthetic FROM outlet ORDER BY id")
        outlet_rows = cursor.fetchall()
        outlet_ids = [row[0] for row in outlet_rows]
        outlet_info = {row[0]: {"name": row[1], "is_synthetic": row[2]} for row in outlet_rows}

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

        # Run experiment with dedup=True and dedup=False
        results = []

        # Pass 1: dedup=True
        results.extend(
            _run_em_pass(conn, outlet_ids, outlet_info, event_ids, batch_size, dedup=True)
        )

        # Reset suffstats for second pass
        conn.execute("DELETE FROM em_suffstats")
        conn.execute("DELETE FROM reliability_snapshot")
        conn.execute("DELETE FROM em_state")
        conn.commit()

        # Pass 2: dedup=False
        results.extend(
            _run_em_pass(conn, outlet_ids, outlet_info, event_ids, batch_size, dedup=False)
        )

        # Write CSV
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        csv_path = out_path / "e3_isot.csv"

        # Sort deterministically: dedup, then reliability desc
        results.sort(
            key=lambda r: (not r["dedup"], -r["reliability"]),
            reverse=False
        )

        with open(csv_path, "w") as f:
            f.write("dedup,outlet,is_real,sens,spec,reliability,n_obs\n")
            for r in results:
                is_real = 1 if r["is_real"] else 0
                f.write(
                    f"{int(r['dedup'])},{r['outlet']},{is_real},"
                    f"{r['sens']:.6f},{r['spec']:.6f},{r['reliability']:.6f},"
                    f"{int(r['n_obs'])}\n"
                )

        # Compute metrics and create plot (dedup=True only)
        dedup_on_results = [r for r in results if r["dedup"]]
        dedup_off_results = [r for r in results if not r["dedup"]]

        metrics = _compute_metrics(dedup_on_results, dedup_off_results, len(event_ids))

        png_path = _create_plot(dedup_on_results, out_path)

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


def _run_em_pass(conn, outlet_ids, outlet_info, event_ids, batch_size, dedup):
    """
    Run one EM pass (dedup=True or False).

    Returns:
        list of dicts: [{outlet, is_real, sens, spec, reliability, n_obs, dedup}, ...]
    """
    em = OnlineEM(outlet_ids, conn=conn, dedup_voting=dedup)

    # Run EM in batches
    for batch_idx in range(0, len(event_ids), batch_size):
        batch_ids = event_ids[batch_idx : batch_idx + batch_size]
        result = em.e_step_batch(batch_ids)
        em.accumulate(result["batch_stats"], batch_idx // batch_size, posteriors=result["posteriors"])

    # Extract parameters
    params = em.params()
    results = []

    for outlet_id in outlet_ids:
        outlet_name = outlet_info[outlet_id]["name"]
        is_real = (outlet_name == "reuters")
        param = params[outlet_id]

        results.append({
            "dedup": dedup,
            "outlet": outlet_name,
            "is_real": is_real,
            "sens": param["sens"],
            "spec": param["spec"],
            "reliability": param["reliability"],
            "n_obs": em.n_obs[outlet_id],
        })

    return results


def _compute_metrics(dedup_on_results, dedup_off_results, n_events_used=0):
    """Compute AUC, rank, and inversion metrics."""
    metrics = {}

    # Dedup=True metrics
    if dedup_on_results:
        auc_dedup_on = _compute_auc(dedup_on_results)
        metrics["auc_dedup_on"] = auc_dedup_on

        # Real outlet rank
        real_rank = _compute_real_rank(dedup_on_results)
        metrics["real_rank_dedup_on"] = real_rank

        # Mean reliability
        mean_rel = np.mean([r["reliability"] for r in dedup_on_results])
        metrics["mean_reliability_dedup_on"] = float(mean_rel)

        # Inversion flag: majority capture (synthetic > real)
        inversion_flag = float(mean_rel) < 0.5
        metrics["inversion_flag"] = bool(inversion_flag)

        # Event count
        metrics["n_events_used"] = n_events_used
        metrics["n_outlets"] = len(dedup_on_results)

    # Dedup=False metrics
    if dedup_off_results:
        auc_dedup_off = _compute_auc(dedup_off_results)
        metrics["auc_dedup_off"] = auc_dedup_off

    return metrics


def _compute_auc(results):
    """
    Compute AUC separating real vs fake by reliability.

    results: list of dicts with "is_real" and "reliability" keys
    Returns: float in [0, 1]
    """
    real = [r["reliability"] for r in results if r["is_real"]]
    fake = [r["reliability"] for r in results if not r["is_real"]]

    if not real or not fake:
        return 0.5

    # Try sklearn first
    try:
        from sklearn.metrics import roc_auc_score

        labels = [1] * len(real) + [0] * len(fake)
        scores = real + fake
        return float(roc_auc_score(labels, scores))
    except ImportError:
        pass

    # Manual rank-based AUC
    # Fraction of (real, fake) pairs where real > fake
    n_pairs = len(real) * len(fake)
    if n_pairs == 0:
        return 0.5

    n_correct = 0
    for r_rel in real:
        for f_rel in fake:
            if r_rel > f_rel:
                n_correct += 1

    return float(n_correct) / n_pairs


def _compute_real_rank(results):
    """
    Compute rank of real outlet by reliability (1 = highest).

    results: list of dicts with "is_real" and "reliability" keys
    Returns: int >= 1
    """
    # Sort by reliability descending
    sorted_results = sorted(results, key=lambda r: r["reliability"], reverse=True)

    for idx, r in enumerate(sorted_results):
        if r["is_real"]:
            return idx + 1

    return len(results)


def _create_plot(results, out_path):
    """Create fivethirtyeight horizontal bar chart of reliability by outlet."""
    import matplotlib as mpl

    # Sort by reliability descending
    results = sorted(results, key=lambda r: r["reliability"], reverse=True)

    outlets = [r["outlet"] for r in results]
    reliabilities = [r["reliability"] for r in results]
    colors = ["#008fd5" if r["is_real"] else "#fc4f30" for r in results]

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

    # Horizontal bars
    y_pos = np.arange(len(outlets))
    ax.barh(y_pos, reliabilities, color=colors, alpha=0.8)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(outlets, fontsize=11)
    ax.set_xlabel("Estimated Reliability", fontsize=11)
    ax.set_title("E3: Outlet Reliability on Real ISOT Corpus", fontsize=14, fontweight="bold")

    caption = (
        "Blue: reuters (real). Red: fake:* (synthetic). "
        "Real vs 6 synthetic outlets; majority-capture regime."
    )
    ax.text(
        0.5,
        -0.1,
        caption,
        transform=ax.transAxes,
        ha="center",
        fontsize=9,
        style="italic",
    )

    plt.tight_layout()
    png_path = out_path / "e3_isot.png"
    plt.savefig(png_path, dpi=100, bbox_inches="tight")
    plt.close()

    return str(png_path)
