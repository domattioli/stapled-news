"""E7: Consensus distance — headline variance across outlets."""

import os
import shutil
import tempfile
import json
from pathlib import Path
from datetime import datetime

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from stapled.db import connect
from stapled.infer.online_em import OnlineEM
from stapled.analyze.consensus_distance import (
    compute_distances,
    aggregate_outlets,
    weekly_series,
    validate_planted,
    validate_split_half,
)


def run(config: dict, seed: int, out_dir: str) -> dict:
    """
    Run E7 consensus distance experiment.

    Config keys:
        db_path: Path to database (default "fp.db")
        min_outlets: Minimum distinct outlets per event (default 5)
        batch_size: Batch size for EM (default 64)
        quick: Quick mode (min_outlets=3, n_boot=100)

    Returns:
        dict with outputs (CSV, PNG, JSON paths) and metrics
    """
    # Parse config
    db_path = config.get("db_path", "fp.db")
    min_outlets = config.get("min_outlets", 5)
    batch_size = config.get("batch_size", 64)
    quick = config.get("quick", False)

    if quick:
        min_outlets = 3

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

        # Run OnlineEM with dedup_voting=True
        em = OnlineEM(outlet_ids, conn=conn, dedup_voting=True)

        for batch_idx in range(0, len(event_ids), batch_size):
            batch_ids = event_ids[batch_idx : batch_idx + batch_size]
            result = em.e_step_batch(batch_ids)
            em.accumulate(result["batch_stats"], batch_idx // batch_size)

        # Extract EM parameters for outlet agreement
        params = em.params()
        em_agreement = {outlet_id: params[outlet_id]["reliability"] for outlet_id in outlet_ids}

        # Compute consensus distances
        data_dict = compute_distances(conn, min_outlets=min_outlets)

        article_rows = data_dict["articles"]
        event_rows = data_dict["events"]

        # Aggregate by outlet
        outlet_metrics = aggregate_outlets(
            article_rows,
            seed=seed,
            n_boot=100 if quick else 1000,
        )

        # Compute weekly series
        weekly_data = weekly_series(conn, article_rows)

        # Validation gates
        v1_validation = validate_planted(data_dict)
        v2_validation = validate_split_half(conn, article_rows, seed=seed)

        # Write outputs
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)

        # CSV: article-level distances
        csv_articles_path = out_path / "e7_consensus_distance.csv"
        with open(csv_articles_path, "w") as f:
            f.write("article_id,outlet,event_id,distance\n")
            for row in article_rows:
                f.write(
                    f"{row['article_id']},{row['outlet']},{row['event_id']},{row['distance']:.6f}\n"
                )

        # CSV: outlet-level aggregates
        csv_outlets_path = out_path / "e7_outlet_distance.csv"
        with open(csv_outlets_path, "w") as f:
            f.write("outlet,n_articles,mean_distance,ci_low,ci_high,em_consensus_agreement\n")
            for metric in outlet_metrics:
                outlet = metric["outlet"]
                em_agree = em_agreement.get(outlet, "N/A")
                # Get outlet_id from conn for EM agreement lookup
                cursor = conn.execute("SELECT id FROM outlet WHERE name = ?", (outlet,))
                outlet_id_row = cursor.fetchone()
                if outlet_id_row:
                    outlet_id = outlet_id_row[0]
                    em_agree = em_agreement.get(outlet_id, 0.5)
                else:
                    em_agree = 0.5

                f.write(
                    f"{metric['outlet']},{metric['n_articles']},"
                    f"{metric['mean_distance']:.6f},{metric['ci_low']:.6f},"
                    f"{metric['ci_high']:.6f},{em_agree:.6f}\n"
                )

        # Create visualization
        png_path = _create_chart(outlet_metrics, out_path)

        # Build consensus.json
        # Top 30 events by n_outlets
        top_events = sorted(event_rows, key=lambda e: e["n_outlets"], reverse=True)[:30]

        # Corpus metadata for the site bundle (date range from fp_article_meta
        # when present; falls back to article.published_at).
        try:
            row = conn.execute(
                "SELECT MIN(first_seen), MAX(last_seen) FROM fp_article_meta"
            ).fetchone()
            since, until = (row[0] or "")[:10], (row[1] or "")[:10]
        except Exception:
            row = conn.execute(
                "SELECT MIN(published_at), MAX(published_at) FROM article"
            ).fetchone()
            since, until = (row[0] or "")[:10], (row[1] or "")[:10]
        n_corpus_articles = conn.execute("SELECT COUNT(*) FROM article").fetchone()[0]
        n_corpus_outlets = conn.execute("SELECT COUNT(*) FROM outlet").fetchone()[0]

        consensus_bundle = {
            "generated_at": datetime.utcnow().isoformat(),
            "corpus": {
                "repo": "defgsus/frontpage-archive-2026",
                "since": since,
                "until": until,
                "n_events": len(event_rows),
                "n_articles": len(article_rows),
                "n_corpus_articles": n_corpus_articles,
                "n_outlets": n_corpus_outlets,
            },
            "ranking": [
                {
                    "outlet": m["outlet"],
                    "n_articles": m["n_articles"],
                    "mean_distance": round(m["mean_distance"], 6),
                    "ci_low": round(m["ci_low"], 6),
                    "ci_high": round(m["ci_high"], 6),
                }
                for m in outlet_metrics
            ],
            "weekly": weekly_data,
            "events": [
                {
                    "event_id": e["event_id"],
                    "n_outlets": e["n_outlets"],
                    "consensus_headline": e["consensus_headline"],
                    "nearest_outlet": e["nearest_outlet"],
                    "farthest_outlet": e["farthest_outlet"],
                    "farthest_distance": round(e["farthest_distance"], 6),
                }
                for e in top_events
            ],
            "validation": {
                "v1_planted": {
                    "copier_mean": round(v1_validation["copier_mean"], 6),
                    "noise_mean": round(v1_validation["noise_mean"], 6),
                    "gate_pass": v1_validation["gate_pass"],
                },
                "v2_split_half": {
                    "rho": round(v2_validation["rho"], 6),
                    "n_outlets": v2_validation["n_outlets"],
                    "gate_pass": v2_validation["gate_pass"],
                },
            },
        }

        json_path = out_path / "consensus.json"
        with open(json_path, "w") as f:
            json.dump(consensus_bundle, f, indent=2)

        # Metrics for manifest
        metrics = {
            "n_events": len(event_rows),
            "n_articles": len(article_rows),
            "n_outlets_ranked": len(outlet_metrics),
            "v1_gate": v1_validation["gate_pass"],
            "v2_rho": round(v2_validation["rho"], 4),
            "v2_gate": v2_validation["gate_pass"],
            "top_outlet": outlet_metrics[0]["outlet"] if outlet_metrics else "N/A",
            "bottom_outlet": outlet_metrics[-1]["outlet"] if outlet_metrics else "N/A",
        }

        conn.close()

        return {
            "outputs": [str(csv_articles_path), str(csv_outlets_path), str(png_path), str(json_path)],
            "metrics": metrics,
        }

    finally:
        # Clean up temp DB
        try:
            os.remove(temp_db_path)
        except OSError:
            pass


def _create_chart(outlet_metrics: list, out_path: Path) -> Path:
    """
    Create horizontal bar chart of outlet mean distances with CI error bars.

    Uses matplotlib fivethirtyeight style.
    """
    plt.style.use('fivethirtyeight')
    fig, ax = plt.subplots(figsize=(12, 8))

    outlets = [m["outlet"] for m in outlet_metrics]
    means = [m["mean_distance"] for m in outlet_metrics]
    ci_lows = [m["ci_low"] for m in outlet_metrics]
    ci_highs = [m["ci_high"] for m in outlet_metrics]

    # Error bars: ci_low to ci_high
    errors = [
        [m - ci_low for m, ci_low in zip(means, ci_lows)],
        [h - m for h, m in zip(ci_highs, means)],
    ]

    y_pos = np.arange(len(outlets))
    ax.barh(y_pos, means, xerr=errors, capsize=5, alpha=0.8)

    ax.set_yticks(y_pos)
    ax.set_yticklabels(outlets)
    ax.set_xlabel("Mean Consensus Distance (with 95% CI)")
    ax.set_title("Outlet Headline Consensus Distance\n(closer to 0 = closer to consensus)")
    ax.invert_yaxis()

    plt.tight_layout()
    png_path = out_path / "e7_consensus.png"
    fig.savefig(png_path, dpi=100, bbox_inches='tight')
    plt.close(fig)

    return png_path
