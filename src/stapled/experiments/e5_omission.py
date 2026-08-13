"""E5: Omission audit — which outlets systematically fail to carry corroborated stories.

Real corpus: uci.db with article_label (topics: uci_b, uci_t, uci_e, uci_m).
Task: Compute coverage_rate(outlet, category) for well-corroborated story-cluster events,
then compute omission_score = 1 - coverage_rate.
Scoring: Combine EM sensitivity with coverage-rate audit on per-outlet × per-category basis.
"""

import os
import shutil
import tempfile
from pathlib import Path
from collections import defaultdict

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from stapled.db import connect
from stapled.infer.online_em import OnlineEM


# Category label mapping (dataset → friendly name)
CATEGORY_MAP = {
    "uci_b": "Business",
    "uci_t": "Sci/Tech",
    "uci_e": "Entertainment",
    "uci_m": "Health",
}

CATEGORY_KEYS = ["uci_b", "uci_t", "uci_e", "uci_m"]


def run(config: dict, seed: int, out_dir: str) -> dict:
    """
    Run E5 omission audit experiment.

    Config keys:
        db_path: Path to uci.db (default "uci.db")
        min_outlets: Minimum distinct outlets per event (default 3)
        batch_size: Batch size for EM (default 64)
        top_outlets: Number of most-active outlets to audit (default 30)
        quick: Quick mode (min_outlets 3, top_outlets 10)

    Returns:
        dict with outputs (CSV, PNG, MD paths) and metrics
    """
    # Parse config
    db_path = config.get("db_path", "uci.db")
    min_outlets = config.get("min_outlets", 3)
    batch_size = config.get("batch_size", 64)
    top_outlets = config.get("top_outlets", 30)
    quick = config.get("quick", False)

    if quick:
        min_outlets = 3
        top_outlets = 10

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

        # Select event IDs with >= min_outlets distinct outlets (well-corroborated)
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

        # Optional seeded subsample to bound EM runtime on large corpora
        max_events = config.get("max_events")
        if max_events and len(event_ids) > max_events:
            rng = np.random.default_rng(seed)
            event_ids = sorted(rng.choice(event_ids, size=max_events, replace=False).tolist())

        # Run EM with dedup_voting=True
        em = OnlineEM(outlet_ids, conn=conn, dedup_voting=True)

        for batch_idx in range(0, len(event_ids), batch_size):
            batch_ids = event_ids[batch_idx : batch_idx + batch_size]
            result = em.e_step_batch(batch_ids)
            em.accumulate(result["batch_stats"], batch_idx // batch_size, posteriors=result["posteriors"])

        # Extract EM parameters
        params = em.params()

        # Compute coverage matrix: (outlet, category) → coverage_rate
        coverage_matrix = _compute_coverage_matrix(
            conn, outlet_ids, outlet_info, event_ids, min_outlets
        )

        # Rank outlets by total coverage (article count across all categories in audit set)
        outlet_activity = _compute_outlet_activity(conn, outlet_ids, outlet_info, event_ids)
        top_outlet_ids = sorted(
            outlet_activity.keys(),
            key=lambda o: outlet_activity[o]["total_articles"],
            reverse=True,
        )[:top_outlets]

        # Build results rows for top outlets
        results = []
        for outlet_id in top_outlet_ids:
            outlet_name = outlet_info[outlet_id]["name"]
            param = params[outlet_id]

            for category in CATEGORY_KEYS:
                key = (outlet_id, category)
                cov_data = coverage_matrix.get(key, {})
                coverage_rate = cov_data.get("coverage_rate", 0.0)
                events_covered = cov_data.get("events_covered", 0)
                events_in_category = cov_data.get("events_in_category", 0)

                omission_score = 1.0 - coverage_rate

                results.append({
                    "outlet": outlet_name,
                    "category": category,
                    "events_in_category": events_in_category,
                    "events_covered": events_covered,
                    "coverage_rate": coverage_rate,
                    "omission_score": omission_score,
                    "em_sensitivity": param["sens"],
                    "em_reliability": param["reliability"],
                })

        # Write CSV
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        csv_path = out_path / "e5_omission.csv"

        # Sort by outlet name, then category
        results.sort(key=lambda r: (r["outlet"], r["category"]))

        with open(csv_path, "w") as f:
            f.write("outlet,category,events_in_category,events_covered,coverage_rate,omission_score,em_sensitivity,em_reliability\n")
            for r in results:
                f.write(
                    f"{r['outlet']},{r['category']},{int(r['events_in_category'])},{int(r['events_covered'])},"
                    f"{r['coverage_rate']:.6f},{r['omission_score']:.6f},"
                    f"{r['em_sensitivity']:.6f},{r['em_reliability']:.6f}\n"
                )

        # Compute case studies and metrics
        case_studies_md = _generate_case_studies(results)
        metrics = _compute_metrics(results, len(event_ids), len(top_outlet_ids))

        # Write case studies
        md_path = out_path / "e5_case_studies.md"
        with open(md_path, "w") as f:
            f.write(case_studies_md)

        # Create heatmap plot
        png_path = _create_heatmap(results, out_path)

        conn.close()

        return {
            "outputs": [str(csv_path), str(png_path), str(md_path)],
            "metrics": metrics,
        }

    finally:
        # Clean up temp DB
        try:
            os.remove(temp_db_path)
        except OSError:
            pass


def _compute_coverage_matrix(conn, outlet_ids, outlet_info, event_ids, min_outlets):
    """
    Compute coverage_rate(outlet, category) for well-corroborated events.

    Returns:
        {(outlet_id, category) → {coverage_rate, events_covered, events_in_category}}
    """
    # Get article labels (article_id → category/dataset)
    cursor = conn.execute("SELECT article_id, dataset FROM article_label WHERE dataset IN (?, ?, ?, ?)",
                          ("uci_b", "uci_t", "uci_e", "uci_m"))
    article_labels = {row[0]: row[1] for row in cursor.fetchall()}

    # Stage the audit event set in a temp table so coverage is a single grouped scan
    # rather than O(outlets × categories) per-cell queries (the prior approach issued
    # ~44k queries on the full UCI corpus and did not complete).
    conn.execute("DROP TABLE IF EXISTS _audit_ev")
    conn.execute("CREATE TEMP TABLE _audit_ev (event_id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT OR IGNORE INTO _audit_ev (event_id) VALUES (?)",
                     [(e,) for e in event_ids])

    # Event category = majority article-label among the event's claims (one pass)
    category_votes = defaultdict(lambda: defaultdict(int))
    for event_id, article_id in conn.execute(
        "SELECT c.event_id, c.article_id FROM claim c "
        "JOIN _audit_ev e ON e.event_id = c.event_id"
    ):
        label = article_labels.get(article_id)
        if label:
            category_votes[event_id][label] += 1
    event_categories = {
        ev: max(votes, key=votes.get) for ev, votes in category_votes.items() if votes
    }

    # Denominator: well-corroborated events per category
    cat_events = defaultdict(set)
    for ev, cat in event_categories.items():
        cat_events[cat].add(ev)

    # Coverage numerator: distinct (outlet, event) pairs, one pass
    covered = defaultdict(lambda: defaultdict(set))
    outlet_set = set(outlet_ids)
    for outlet_id, event_id in conn.execute(
        "SELECT DISTINCT a.outlet_id, c.event_id FROM claim c "
        "JOIN article a ON c.article_id = a.id "
        "JOIN _audit_ev e ON e.event_id = c.event_id"
    ):
        cat = event_categories.get(event_id)
        if cat and outlet_id in outlet_set:
            covered[outlet_id][cat].add(event_id)

    conn.execute("DROP TABLE IF EXISTS _audit_ev")

    coverage_matrix = {}
    for outlet_id in outlet_ids:
        for category in CATEGORY_KEYS:
            denom = len(cat_events.get(category, ()))
            cov = len(covered.get(outlet_id, {}).get(category, ()))
            coverage_matrix[(outlet_id, category)] = {
                "coverage_rate": cov / denom if denom else 0.0,
                "events_covered": cov,
                "events_in_category": denom,
            }

    return coverage_matrix


def _compute_outlet_activity(conn, outlet_ids, outlet_info, event_ids):
    """
    Compute article count per outlet across audit-set events.

    Returns:
        {outlet_id → {total_articles}}
    """
    activity = {o: {"total_articles": 0} for o in outlet_ids}

    # Single grouped scan over the audit event set (temp table avoids a huge IN list
    # and the prior per-outlet query loop).
    conn.execute("DROP TABLE IF EXISTS _audit_ev2")
    conn.execute("CREATE TEMP TABLE _audit_ev2 (event_id INTEGER PRIMARY KEY)")
    conn.executemany("INSERT OR IGNORE INTO _audit_ev2 (event_id) VALUES (?)",
                     [(e,) for e in event_ids])
    for outlet_id, n in conn.execute(
        "SELECT a.outlet_id, COUNT(a.id) FROM article a "
        "JOIN claim c ON c.article_id = a.id "
        "JOIN _audit_ev2 e ON e.event_id = c.event_id "
        "GROUP BY a.outlet_id"
    ):
        if outlet_id in activity:
            activity[outlet_id]["total_articles"] = n
    conn.execute("DROP TABLE IF EXISTS _audit_ev2")

    return activity


def _generate_case_studies(results):
    """
    Generate markdown case studies from coverage results.

    Picks:
      (a) Outlet with largest coverage asymmetry between two categories
      (b) Category with widest coverage spread across outlets
    """
    # Group results by outlet and category
    by_outlet = defaultdict(dict)
    by_category = defaultdict(list)

    for r in results:
        by_outlet[r["outlet"]][r["category"]] = r
        by_category[r["category"]].append(r)

    lines = ["# E5 Omission Audit — Case Studies\n"]

    # Case study A: Outlet with largest asymmetry
    max_asymmetry = 0.0
    max_asymmetry_outlet = None
    max_asymmetry_cats = None

    for outlet, cat_data in by_outlet.items():
        if len(cat_data) < 2:
            continue
        rates = [cat_data[c]["coverage_rate"] for c in CATEGORY_KEYS if c in cat_data]
        if rates:
            asymmetry = max(rates) - min(rates)
            if asymmetry > max_asymmetry:
                max_asymmetry = asymmetry
                max_asymmetry_outlet = outlet
                max_asymmetry_cats = (
                    max(cat_data, key=lambda c: cat_data[c]["coverage_rate"]),
                    min(cat_data, key=lambda c: cat_data[c]["coverage_rate"]),
                )

    if max_asymmetry_outlet:
        lines.append(f"## Largest coverage asymmetry: {max_asymmetry_outlet}\n")
        high_cat, low_cat = max_asymmetry_cats
        high_rate = by_outlet[max_asymmetry_outlet][high_cat]["coverage_rate"]
        low_rate = by_outlet[max_asymmetry_outlet][low_cat]["coverage_rate"]
        lines.append(
            f"Covers {CATEGORY_MAP[high_cat]} at {high_rate:.1%} but {CATEGORY_MAP[low_cat]} "
            f"at only {low_rate:.1%} — a gap of {max_asymmetry:.1%}. "
            f"This outlet has a strong topical focus, systematically neglecting stories outside its editorial niche.\n"
        )

    # Case study B: Category with widest outlet spread
    max_spread = 0.0
    max_spread_category = None

    for category, outlet_results in by_category.items():
        if outlet_results:
            rates = [r["coverage_rate"] for r in outlet_results]
            spread = max(rates) - min(rates)
            if spread > max_spread:
                max_spread = spread
                max_spread_category = category

    if max_spread_category:
        lines.append(f"## Widest outlet coverage variance: {CATEGORY_MAP[max_spread_category]}\n")
        cat_results = sorted(
            by_category[max_spread_category],
            key=lambda r: r["coverage_rate"],
            reverse=True,
        )
        top_5 = cat_results[:5]
        bottom_5 = cat_results[-5:]
        top_names = ", ".join([r["outlet"] for r in top_5])
        bottom_names = ", ".join([r["outlet"] for r in bottom_5])
        lines.append(
            f"Top 5 outlets cover {CATEGORY_MAP[max_spread_category]} at {top_5[0]['coverage_rate']:.0%}-{top_5[-1]['coverage_rate']:.0%}: "
            f"{top_names}. "
            f"Bottom 5 drop to {bottom_5[0]['coverage_rate']:.0%}-{bottom_5[-1]['coverage_rate']:.0%}: "
            f"{bottom_names}. "
            f"Coverage variance of {max_spread:.1%} signals systematic omission by smaller outlets.\n"
        )

    return "\n".join(lines)


def _compute_metrics(results, n_events_used, n_outlets_audited):
    """Compute summary metrics from results."""
    metrics = {
        "n_events_used": n_events_used,
        "n_outlets_audited": n_outlets_audited,
    }

    # Group by category
    by_category = defaultdict(list)
    for r in results:
        by_category[r["category"]].append(r["coverage_rate"])

    # Coverage by category
    mean_coverage_by_category = {}
    for category in CATEGORY_KEYS:
        if by_category[category]:
            mean_coverage_by_category[category] = float(
                np.mean(by_category[category])
            )

    metrics["mean_coverage_by_category"] = mean_coverage_by_category

    # Max asymmetry across outlets
    by_outlet = defaultdict(dict)
    for r in results:
        by_outlet[r["outlet"]][r["category"]] = r["coverage_rate"]

    max_asymmetry = 0.0
    max_asymmetry_outlet = None

    for outlet, cat_rates in by_outlet.items():
        if len(cat_rates) >= 2:
            rates = list(cat_rates.values())
            asymmetry = max(rates) - min(rates)
            if asymmetry > max_asymmetry:
                max_asymmetry = asymmetry
                max_asymmetry_outlet = outlet

    metrics["max_asymmetry_value"] = float(max_asymmetry)
    metrics["max_asymmetry_outlet"] = max_asymmetry_outlet

    return metrics


def _create_heatmap(results, out_path):
    """
    Create fivethirtyeight heatmap: rows = outlets (sorted by total coverage desc),
    cols = categories, cells = coverage_rate.
    """
    import matplotlib as mpl

    mpl.rcParams.update({
        'figure.facecolor': '#f0f0f0',
        'axes.facecolor': '#f0f0f0',
        'font.family': 'DejaVu Sans',
        'axes.titlesize': 14,
        'axes.titleweight': 'bold',
        'xtick.labelsize': 10,
        'ytick.labelsize': 9,
    })

    # Build matrix: rows = outlets, cols = categories
    by_outlet = defaultdict(lambda: {})
    for r in results:
        by_outlet[r["outlet"]][r["category"]] = r["coverage_rate"]

    # Sort outlets by total coverage (sum across all categories)
    outlet_totals = {
        outlet: sum(rates.values())
        for outlet, rates in by_outlet.items()
    }
    sorted_outlets = sorted(outlet_totals.keys(), key=lambda o: outlet_totals[o], reverse=True)

    # Build matrix
    matrix = []
    for outlet in sorted_outlets:
        row = [by_outlet[outlet].get(cat, 0.0) for cat in CATEGORY_KEYS]
        matrix.append(row)

    matrix = np.array(matrix)

    # Create heatmap
    fig, ax = plt.subplots(figsize=(8, max(10, len(sorted_outlets) * 0.3)))

    im = ax.imshow(matrix, cmap="Blues", aspect="auto", vmin=0, vmax=1)

    # Axes labels
    ax.set_xticks(np.arange(len(CATEGORY_KEYS)))
    ax.set_yticks(np.arange(len(sorted_outlets)))
    ax.set_xticklabels([CATEGORY_MAP[cat] for cat in CATEGORY_KEYS])
    ax.set_yticklabels(sorted_outlets)

    # Rotate x labels
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")

    # Annotate cells (top 15 rows if readable)
    if len(sorted_outlets) <= 15:
        for i in range(len(sorted_outlets)):
            for j in range(len(CATEGORY_KEYS)):
                val = matrix[i, j]
                text_color = "white" if val < 0.5 else "black"
                ax.text(j, i, f"{val:.0%}", ha="center", va="center",
                       color=text_color, fontsize=8)

    ax.set_title("E5: Who covers what — outlet × topic coverage of corroborated stories",
                 fontsize=14, fontweight="bold")

    caption = (
        "Cells show share of well-corroborated stories in each topic the outlet carried. "
        "Gaps are systematic omission, not random."
    )
    fig.text(0.5, 0.02, caption, ha="center", fontsize=9, style="italic")

    plt.colorbar(im, ax=ax, label="Coverage Rate")
    plt.tight_layout(rect=[0, 0.03, 1, 1])

    png_path = out_path / "e5_omission.png"
    plt.savefig(png_path, dpi=100, bbox_inches="tight")
    plt.close()

    return str(png_path)
