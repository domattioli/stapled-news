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
    token_impacts,
    lean_breakdown,
    panel_composition,
    panel_spectrum,
    consensus_lean_axis,
    regional_impact,
    _lean_bucket_weights,
    PANEL_LEAN,
    PANEL_LEAN5,
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

        ranking_list = [
            {
                "outlet": m["outlet"],
                "n_articles": m["n_articles"],
                "mean_distance": round(m["mean_distance"], 6),
                "ci_low": round(m["ci_low"], 6),
                "ci_high": round(m["ci_high"], 6),
                "lean": PANEL_LEAN.get(m["outlet"]),
                "lean5": PANEL_LEAN5.get(m["outlet"]),
            }
            for m in outlet_metrics
        ]

        consensus_bundle = {
            "generated_at": datetime.utcnow().isoformat(),
            "corpus": {
                "repo": "stapled-news corpus/us/headlines.csv.gz (GDELT+RSS+Google News)",
                "since": since,
                "until": until,
                "n_events": len(event_rows),
                "n_articles": len(article_rows),
                "n_corpus_articles": n_corpus_articles,
                "n_outlets": n_corpus_outlets,
            },
            "ranking": ranking_list,
            "ranking_display": _curate_ranking_for_display(ranking_list),
            "lean_breakdown": lean_breakdown(article_rows, seed=seed),
            "panel_composition": panel_composition(article_rows),
            "panel_spectrum": panel_spectrum(article_rows),
            "syndication": _syndication_stats(article_rows),
            "regional_impact": regional_impact(article_rows),
            "consensus_lean": consensus_lean_axis(conn, min_outlets=min_outlets, seed=seed),
            "weekly": weekly_data,
            "weekly_display": _curate_weekly_for_display(weekly_data),
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
            "events_detail": _build_events_detail(article_rows, top_events),
            "articles": [
                {
                    "outlet": r["outlet"],
                    "event_id": r["event_id"],
                    "distance": round(r["distance"], 4),
                    "event_outlets": r.get("event_outlets", 1),
                    "lean": PANEL_LEAN.get(r["outlet"]),
                }
                for r in article_rows
            ],
            "validation": {
                "v1_planted": {
                    "copier_mean": round(v1_validation["copier_mean"], 6),
                    "noise_mean": round(v1_validation["noise_mean"], 6),
                    "corpus_mean": round(v1_validation.get("corpus_mean", 0.0), 6),
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


FAMOUS_OUTLETS = {
    "nytimes.com", "washingtonpost.com", "cnn.com", "foxnews.com", "nbcnews.com",
    "abcnews.go.com", "cbsnews.com", "npr.org", "politico.com", "reuters.com",
    "apnews.com", "wsj.com", "usatoday.com", "thehill.com", "axios.com",
    "msnbc.com", "breitbart.com", "huffpost.com", "newsmax.com", "theguardian.com",
    "nypost.com", "bloomberg.com", "thedailybeast.com", "nationalreview.com",
}


def _curate_members(members):
    """Pick at most one outlet per AllSides lean category (left, lean-left,
    center, lean-right, right, unrated) per story, so a single dominant camp
    cannot fill the card and every example stays legible at a glance. Within
    a category, prefers a famous national outlet, then distance to consensus."""
    by_category = {}
    for m in members:
        category = PANEL_LEAN5.get(m["outlet"], "unrated")
        by_category.setdefault(category, []).append(m)
    picked = [
        sorted(group, key=lambda m: (m["outlet"] not in FAMOUS_OUTLETS, m["distance"]))[0]
        for group in by_category.values()
    ]
    return sorted(picked, key=lambda m: m["distance"])


def _curate_ranking_for_display(ranking, n_recognizable=20, n_tail=5):
    """For the outlet-ranking chart: recognizable (FAMOUS_OUTLETS) names plus
    the most extreme entries at both ends, so the chart stays legible on a
    corpus with hundreds of ranked outlets without losing the shape of the
    full distribution. `ranking` must already be sorted by mean_distance
    ascending; returns the full list unchanged if it is already small."""
    if len(ranking) <= n_recognizable + 2 * n_tail:
        return ranking
    tail = ranking[:n_tail] + ranking[-n_tail:]
    famous = [r for r in ranking if r["outlet"] in FAMOUS_OUTLETS]
    seen = set()
    curated = []
    for r in tail + famous:
        if r["outlet"] not in seen:
            seen.add(r["outlet"])
            curated.append(r)
    curated.sort(key=lambda r: r["mean_distance"])
    return curated


def _curate_weekly_for_display(weekly, target=8):
    """Pick up to `target` recognizable (FAMOUS_OUTLETS) outlets spread across
    the AllSides lean spectrum for the weekly-trajectory chart, round-robin
    across categories and preferring outlets with more weeks of coverage
    within each. Plotting every qualifying outlet (which can be 50+) makes
    the chart unreadable; this keeps it legible while still showing every
    part of the spectrum, not just whichever camp has the most outlets."""
    by_category = {}
    for outlet, weeks in weekly.items():
        if outlet not in FAMOUS_OUTLETS or not weeks:
            continue
        category = PANEL_LEAN5.get(outlet, "unrated")
        by_category.setdefault(category, []).append((outlet, weeks))
    for group in by_category.values():
        group.sort(key=lambda ow: -len(ow[1]))

    category_order = ["left", "lean-left", "center", "lean-right", "right", "unrated"]
    picked = {}
    round_idx = 0
    while len(picked) < target:
        added_this_round = False
        for category in category_order:
            group = by_category.get(category, [])
            if round_idx < len(group):
                outlet, weeks = group[round_idx]
                picked[outlet] = weeks
                added_this_round = True
                if len(picked) >= target:
                    break
        if not added_this_round:
            break
        round_idx += 1
    return picked


def _build_events_detail(article_rows, top_events, max_events=12):
    """Per-event member headlines with word-level distance attribution.

    For each of the top events: the member outlets' headlines, each word tagged
    with its weight (share of the headline's vector mass) and alignment (overlap
    with the event centroid). The site colors low-alignment, high-weight words as
    the ones pushing a headline away from the stapled consensus.
    """
    import re as _re

    by_event = {}
    for row in article_rows:
        by_event.setdefault(row["event_id"], []).append(row)

    detail = []
    for e in top_events[:max_events]:
        full_members = by_event.get(e["event_id"], [])
        if len(full_members) < 2:
            continue

        # Word-level attribution against the SAME weighted centroid the printed
        # distances came from (compute_distances: syndication-dedup + lean-bucket
        # weighted, over every article for the event) - not a fresh uniform
        # centroid refit on only the curated subset shown below, which could
        # color a word green while its printed distance says the opposite.
        full_titles = [m["title"] for m in full_members]
        outlet_names = [m["outlet"] for m in full_members]
        norm_titles = [_re.sub(r"\s+", " ", (t or "").strip().lower()) for t in full_titles]
        dup_counts = {}
        for nt in norm_titles:
            dup_counts[nt] = dup_counts.get(nt, 0) + 1
        synd_w = np.array([1.0 / dup_counts[nt] for nt in norm_titles])
        lean_w = _lean_bucket_weights(outlet_names)
        full_impacts = token_impacts(full_titles, weights=synd_w * lean_w)

        # One row per outlet: keep that outlet's closest-to-consensus headline.
        best = {}
        for m, imp in zip(full_members, full_impacts):
            cur = best.get(m["outlet"])
            if cur is None or m["distance"] < cur[0]["distance"]:
                best[m["outlet"]] = (m, imp)
        members = sorted((p[0] for p in best.values()), key=lambda m: m["distance"])
        members = _curate_members(members)
        impacts_by_outlet = {m["outlet"]: imp for m, imp in best.values()}
        impacts = [impacts_by_outlet[m["outlet"]] for m in members]
        detail.append({
            "event_id": e["event_id"],
            "consensus_headline": e["consensus_headline"],
            "n_outlets": e["n_outlets"],
            "members": [
                {
                    "outlet": m["outlet"],
                    "distance": round(m["distance"], 4),
                    "lean5": PANEL_LEAN5.get(m["outlet"]),
                    "tokens": toks,
                }
                for m, toks in zip(members, impacts)
            ],
        })
    return detail


def _syndication_stats(article_rows):
    """How much of the analyzed corpus is verbatim-syndicated wire copy that the
    consensus centroid now collapses to one effective vote."""
    import re as _re
    groups = {}
    for r in article_rows:
        key = (r["event_id"], _re.sub(r"\s+", " ", (r["title"] or "").strip().lower()))
        groups.setdefault(key, []).append(r["outlet"])
    total = len(article_rows)
    collapsed = sum(len(v) - 1 for v in groups.values() if len(v) > 1)
    top = sorted(
        ({"headline": k[1], "outlets": len(set(v))} for k, v in groups.items() if len(set(v)) > 1),
        key=lambda x: -x["outlets"],
    )[:6]
    return {
        "total_articles": total,
        "syndicated_copies_collapsed": collapsed,
        "pct_syndicated": round(100.0 * collapsed / total, 1) if total else 0.0,
        "top_syndicated": top,
    }
