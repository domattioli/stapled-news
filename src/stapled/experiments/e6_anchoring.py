"""E6: Anchor budget sweep on ISOT real-data experiment.

Quantifies the paper's central claim: sparse anchoring breaks truth/anti-truth
labeling symmetry. On ISOT (1 real outlet 'reuters' vs 6 'fake:*' synthetic),
sweeps the number of anchored events k and measures AUC recovery from the
inverted regime (E3 measured AUC=0.0).
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
    Run E6 anchor-budget sweep experiment on ISOT.

    Config keys:
        db_path: Path to stream.db (default "stream.db")
        min_outlets: Minimum distinct outlets per event (default 2)
        batch_size: Batch size for EM (default 32)
        budgets: List of anchor budget k values (default [0, 5, 10, 25, 50, 100, 200])
        quick: If True, use budgets [0, 25]

    Returns:
        dict with outputs (CSV, PNG paths) and metrics
    """
    # Parse config
    db_path = config.get("db_path", "stream.db")
    min_outlets = config.get("min_outlets", 2)
    batch_size = config.get("batch_size", 32)
    quick = config.get("quick", False)

    if quick:
        budgets = [0, 25]
    else:
        budgets = config.get("budgets", [0, 5, 10, 25, 50, 100, 200])

    # Copy DB to temp file (avoid mutating stream.db)
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        temp_db_path = tmp.name

    try:
        shutil.copy(db_path, temp_db_path)
        conn = connect(temp_db_path)

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

        # Find reuters outlet ID (not used directly, but document for clarity)
        # reuters_id is found per-budget from budget_conn instead

        # Select multi-outlet events and their outlet counts
        cursor = conn.execute(
            """
            SELECT c.event_id, COUNT(DISTINCT a.outlet_id) as outlet_count
            FROM claim c
            JOIN article a ON c.article_id = a.id
            WHERE c.event_id IS NOT NULL
            GROUP BY c.event_id
            HAVING COUNT(DISTINCT a.outlet_id) >= ?
            ORDER BY outlet_count DESC, c.event_id
            """,
            (min_outlets,),
        )
        event_with_counts = cursor.fetchall()
        multi_outlet_events = [row[0] for row in event_with_counts]
        n_multi_outlet_events = len(multi_outlet_events)

        # Average each budget over n_seeds independent anchor draws so the curve
        # reflects the budget, not a single lucky/unlucky draw (single draws are
        # non-monotonic: which events land in the anchor set matters as much as how many).
        n_seeds = config.get("n_seeds", 1)
        results = []

        for budget_k in budgets:
            trial_aucs = []
            trial_ranks = []
            trial_reuters = []
            trial_fake = []
            for s in range(n_seeds):
                rng = np.random.default_rng([seed, budget_k, s])
                with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp2:
                    budget_db_path = tmp2.name
                try:
                    shutil.copy(db_path, budget_db_path)
                    budget_conn = connect(budget_db_path)

                    budget_conn.execute("DELETE FROM em_suffstats")
                    budget_conn.execute("DELETE FROM reliability_snapshot")
                    budget_conn.execute("DELETE FROM em_state")
                    budget_conn.execute("DELETE FROM anchor")
                    budget_conn.commit()

                    cursor = budget_conn.execute("SELECT id FROM outlet WHERE name = 'reuters'")
                    budget_reuters_id = cursor.fetchone()
                    budget_reuters_id = budget_reuters_id[0] if budget_reuters_id else None

                    cursor = budget_conn.execute(
                        """
                        SELECT c.event_id, COUNT(DISTINCT a.outlet_id) as outlet_count
                        FROM claim c
                        JOIN article a ON c.article_id = a.id
                        WHERE c.event_id IS NOT NULL
                        GROUP BY c.event_id
                        HAVING COUNT(DISTINCT a.outlet_id) >= ?
                        ORDER BY outlet_count DESC, c.event_id
                        """,
                        (min_outlets,),
                    )
                    budget_multi_outlet_events = [int(row[0]) for row in cursor.fetchall()]

                    if budget_k > 0 and len(budget_multi_outlet_events) > 0:
                        # Prefer well-corroborated events: top 3k by outlet count, sample k
                        top_k_indices = min(3 * budget_k, len(budget_multi_outlet_events))
                        candidate_events = budget_multi_outlet_events[:top_k_indices]
                        n_to_anchor = min(budget_k, len(candidate_events))

                        if n_to_anchor > 0:
                            anchored_event_ids = [
                                int(x) for x in rng.choice(candidate_events, size=n_to_anchor, replace=False)
                            ]
                            # Batch the truth lookup: one query for all events the real
                            # outlet (reuters) touches, then anchor truth is a set test.
                            reuters_events = set()
                            if budget_reuters_id:
                                reuters_events = {
                                    int(r[0]) for r in budget_conn.execute(
                                        "SELECT DISTINCT c.event_id FROM claim c "
                                        "JOIN article a ON c.article_id = a.id "
                                        "WHERE a.outlet_id = ?",
                                        (budget_reuters_id,),
                                    )
                                }
                            budget_conn.executemany(
                                "INSERT INTO anchor (event_id, true_state, source) VALUES (?, ?, ?)",
                                [
                                    (e, 1 if e in reuters_events else 0, "e6_sweep")
                                    for e in anchored_event_ids
                                ],
                            )
                            budget_conn.commit()

                    auc, real_rank, reuters_reliability, mean_fake_reliability = _run_em_and_score(
                        budget_conn, outlet_ids, outlet_info, event_ids, batch_size
                    )
                    trial_aucs.append(auc)
                    trial_ranks.append(real_rank)
                    trial_reuters.append(reuters_reliability)
                    trial_fake.append(mean_fake_reliability)
                finally:
                    try:
                        budget_conn.close()
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        os.remove(budget_db_path)
                    except OSError:
                        pass

            results.append({
                "budget": budget_k,
                "auc": float(np.mean(trial_aucs)),
                "auc_std": float(np.std(trial_aucs)),
                "real_rank": float(np.mean(trial_ranks)),
                "reuters_reliability": float(np.mean(trial_reuters)),
                "mean_fake_reliability": float(np.mean(trial_fake)),
            })

        # Write CSV
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        csv_path = out_path / "e6_anchoring.csv"

        # Sort by budget
        results.sort(key=lambda r: r["budget"])

        with open(csv_path, "w") as f:
            f.write("budget,auc,real_rank,reuters_reliability,mean_fake_reliability\n")
            for r in results:
                f.write(
                    f"{int(r['budget'])},{r['auc']:.6f},{int(r['real_rank'])},"
                    f"{r['reuters_reliability']:.6f},{r['mean_fake_reliability']:.6f}\n"
                )

        # Compute metrics
        metrics = _compute_metrics(results, n_multi_outlet_events)

        # Create plot
        png_path = _create_plot(results, out_path, n_multi_outlet_events)

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


def _get_event_anchor_truth(conn, event_id: int, reuters_id) -> int:
    """
    Determine anchor true_state for event.

    Returns 1 if ANY reuters article contributes a claim, else 0.
    """
    if not reuters_id:
        return 0

    cursor = conn.execute(
        """
        SELECT COUNT(*) FROM claim c
        JOIN article a ON c.article_id = a.id
        WHERE c.event_id = ? AND a.outlet_id = ?
        """,
        (event_id, reuters_id),
    )
    count = cursor.fetchone()[0]
    return 1 if count > 0 else 0


def _run_em_and_score(conn, outlet_ids, outlet_info, event_ids, batch_size):
    """
    Run OnlineEM and compute AUC + rank metrics.

    Returns: (auc, real_rank, reuters_reliability, mean_fake_reliability)
    """
    em = OnlineEM(outlet_ids, conn=conn, dedup_voting=True)

    # Run EM in batches
    for batch_idx in range(0, len(event_ids), batch_size):
        batch_ids = event_ids[batch_idx : batch_idx + batch_size]
        result = em.e_step_batch(batch_ids)
        em.accumulate(result["batch_stats"], batch_idx // batch_size, posteriors=result["posteriors"])

    # Extract parameters and compute metrics
    params = em.params()
    results = []

    for outlet_id in outlet_ids:
        outlet_name = outlet_info[outlet_id]["name"]
        is_real = (outlet_name == "reuters")
        param = params[outlet_id]

        results.append({
            "outlet": outlet_name,
            "is_real": is_real,
            "reliability": param["reliability"],
        })

    # Compute AUC
    auc = _compute_auc(results)

    # Compute real outlet rank
    real_rank = _compute_real_rank(results)

    # Get reuters and mean fake reliability
    reuters_reliability = None
    fake_reliabilities = []
    for r in results:
        if r["is_real"]:
            reuters_reliability = r["reliability"]
        else:
            fake_reliabilities.append(r["reliability"])

    mean_fake_reliability = np.mean(fake_reliabilities) if fake_reliabilities else 0.5

    return auc, real_rank, reuters_reliability or 0.5, float(mean_fake_reliability)


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
    sorted_results = sorted(results, key=lambda r: r["reliability"], reverse=True)

    for idx, r in enumerate(sorted_results):
        if r["is_real"]:
            return idx + 1

    return len(results)


def _compute_metrics(results, n_multi_outlet_events):
    """Compute summary metrics across budgets."""
    metrics = {
        "auc_by_budget": {str(int(r["budget"])): r["auc"] for r in results},
        "n_multi_outlet_events": n_multi_outlet_events,
        "min_budget_full_recovery": None,
    }

    # Find minimum budget with AUC == 1.0
    for r in results:
        if r["auc"] == 1.0:
            metrics["min_budget_full_recovery"] = int(r["budget"])
            break

    return metrics


def _create_plot(results, out_path, n_multi_outlet_events=None):
    """Create fivethirtyeight line chart of AUC vs anchor budget."""
    import matplotlib as mpl

    budgets = [r["budget"] for r in results]
    aucs = [r["auc"] for r in results]

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

    # Plot line
    ax.plot(budgets, aucs, marker='o', markersize=8, linewidth=2, color='#008fd5', label='AUC')

    # Horizontal reference lines
    ax.axhline(y=0.5, color='#cccccc', linestyle='--', linewidth=1.5, label='Chance (0.5)')
    ax.axhline(y=1.0, color='#fc4f30', linestyle='--', linewidth=1.5, label='Perfect (1.0)')

    # Annotate smallest k with AUC == 1.0
    for r in results:
        if r["auc"] == 1.0:
            ax.annotate(
                f'Full recovery at k={int(r["budget"])}',
                xy=(r["budget"], r["auc"]),
                xytext=(r["budget"], 0.85),
                arrowprops=dict(arrowstyle='->', color='#fc4f30', lw=1.5),
                fontsize=10,
                ha='center',
                color='#fc4f30',
                weight='bold',
            )
            break

    ax.set_xlabel("Anchor Budget k", fontsize=11)
    ax.set_ylabel("AUC (Reuters vs Fake:*)", fontsize=11)
    ax.set_title("E6: Anchor Budget vs Reliability Recovery on ISOT", fontsize=14, fontweight="bold")
    ax.set_ylim(0, 1.05)
    ax.legend(loc='lower right', fontsize=10)

    caption = (
        f"Anchoring k of {n_multi_outlet_events if n_multi_outlet_events is not None else 'N'} multi-outlet events "
        "breaks the labeling symmetry. Real outlet (reuters) vs synthetic (fake:*) classification."
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
    png_path = out_path / "e6_anchoring.png"
    plt.savefig(png_path, dpi=100, bbox_inches="tight")
    plt.close()

    return str(png_path)
