"""Matplotlib visualization charts for inference runs."""

import sqlite3
import json
from pathlib import Path
from typing import List

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt


def render_all(conn: sqlite3.Connection, run_id: int, out_dir: str) -> List[str]:
    """
    Render all charts for a run.
    Returns list of created filenames (relative to out_dir).
    """
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    assets_dir = out_path / "assets"
    assets_dir.mkdir(exist_ok=True)

    filenames = []

    # Load run data
    cursor = conn.execute(
        "SELECT status, corpus_id, config_json FROM inference_run WHERE id = ?",
        (run_id,),
    )
    run_row = cursor.fetchone()
    if not run_row:
        return filenames

    status, corpus_id, config_json = run_row

    # Reliability vs Bias scatter
    filename = _render_reliability_bias_scatter(
        conn, run_id, assets_dir
    )
    if filename:
        filenames.append(filename)

    # Reliability ranking bar
    filename = _render_reliability_ranking(
        conn, run_id, corpus_id, assets_dir
    )
    if filename:
        filenames.append(filename)

    # Confidence histogram
    filename = _render_confidence_hist(conn, run_id, assets_dir)
    if filename:
        filenames.append(filename)

    # Convergence curve
    if config_json:
        filename = _render_convergence_curve(
            conn, run_id, config_json, assets_dir
        )
        if filename:
            filenames.append(filename)

    # Corroboration pie
    filename = _render_corroboration_pie(conn, run_id, assets_dir)
    if filename:
        filenames.append(filename)

    return filenames


def _render_reliability_bias_scatter(
    conn: sqlite3.Connection, run_id: int, assets_dir: Path
) -> str:
    """Scatter: reliability vs bias, point size = #claims."""
    cursor = conn.execute(
        """
        SELECT ror.outlet_id, o.name, ror.est_reliability, ror.est_bias,
               COUNT(DISTINCT c.id) as claim_count
        FROM run_outlet_result ror
        JOIN outlet o ON ror.outlet_id = o.id
        LEFT JOIN claim c ON c.id IN (
            SELECT c2.id FROM claim c2
            JOIN article a ON c2.article_id = a.id
            WHERE a.outlet_id = o.id
        )
        WHERE ror.run_id = ?
        GROUP BY ror.outlet_id
        """,
        (run_id,),
    )

    rows = cursor.fetchall()
    if not rows:
        return ""

    outlet_names = [row[1] for row in rows]
    reliabilities = [row[2] for row in rows]
    biases = [row[3] for row in rows]
    claim_counts = [max(row[4] or 1, 1) for row in rows]

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.scatter(
        reliabilities, biases, s=[c * 10 for c in claim_counts],
        alpha=0.6, edgecolors='black'
    )

    # Annotate
    for i, name in enumerate(outlet_names):
        ax.annotate(name, (reliabilities[i], biases[i]),
                   fontsize=8, ha='center')

    ax.set_xlabel("Estimated Reliability")
    ax.set_ylabel("Estimated Bias")
    ax.set_title("Outlet Reliability vs Bias")
    ax.grid(alpha=0.3)
    ax.axhline(y=0, color='k', linestyle='--', alpha=0.3)
    ax.axvline(x=0.5, color='k', linestyle='--', alpha=0.3)

    filename = f"run_{run_id}_reliability_bias_scatter.png"
    filepath = assets_dir / filename
    fig.savefig(filepath, dpi=100, bbox_inches='tight')
    plt.close(fig)

    return f"assets/{filename}"


def _render_reliability_ranking(
    conn: sqlite3.Connection, run_id: int,
    corpus_id: int, assets_dir: Path
) -> str:
    """Horizontal bar: reliability ranking."""
    cursor = conn.execute(
        """
        SELECT o.name, ror.est_reliability
        FROM run_outlet_result ror
        JOIN outlet o ON ror.outlet_id = o.id
        WHERE ror.run_id = ?
        ORDER BY ror.est_reliability DESC
        """,
        (run_id,),
    )

    rows = cursor.fetchall()
    if not rows:
        return ""

    outlet_names = [row[0] for row in rows]
    reliabilities = [row[1] for row in rows]

    fig, ax = plt.subplots(figsize=(10, max(4, len(outlet_names) * 0.3)))
    ax.barh(outlet_names, reliabilities, color='steelblue')

    # If synthetic, overlay seeded reliability
    if corpus_id:
        cursor = conn.execute(
            """
            SELECT o.name, ot.reliability
            FROM outlet_truth ot
            JOIN outlet o ON ot.outlet_id = o.id
            WHERE ot.corpus_id = ?
            ORDER BY ot.reliability DESC
            """,
            (corpus_id,),
        )
        seeded_rows = cursor.fetchall()
        if seeded_rows:
            seeded_names = [row[0] for row in seeded_rows]
            seeded_vals = [row[1] for row in seeded_rows]
            # Mark seeded on existing bars
            for name, val in zip(seeded_names, seeded_vals):
                if name in outlet_names:
                    idx = outlet_names.index(name)
                    ax.plot([val, val], [idx - 0.4, idx + 0.4],
                           'r-', linewidth=2, label='Seeded' if idx == 0 else '')

    ax.set_xlabel("Reliability")
    ax.set_title("Outlet Reliability Ranking")
    ax.set_xlim(0, 1.1)
    ax.grid(alpha=0.3, axis='x')

    filename = f"run_{run_id}_reliability_ranking.png"
    filepath = assets_dir / filename
    fig.savefig(filepath, dpi=100, bbox_inches='tight')
    plt.close(fig)

    return f"assets/{filename}"


def _render_confidence_hist(
    conn: sqlite3.Connection, run_id: int, assets_dir: Path
) -> str:
    """Histogram: event posterior confidence."""
    cursor = conn.execute(
        """
        SELECT confidence
        FROM run_event_result
        WHERE run_id = ?
        """,
        (run_id,),
    )

    confidences = [row[0] for row in cursor.fetchall()]
    if not confidences:
        return ""

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.hist(confidences, bins=20, color='steelblue', edgecolor='black')

    ax.set_xlabel("Confidence")
    ax.set_ylabel("Count")
    ax.set_title("Event Confidence Distribution")
    ax.grid(alpha=0.3, axis='y')

    filename = f"run_{run_id}_confidence_hist.png"
    filepath = assets_dir / filename
    fig.savefig(filepath, dpi=100, bbox_inches='tight')
    plt.close(fig)

    return f"assets/{filename}"


def _render_convergence_curve(
    conn: sqlite3.Connection, run_id: int,
    config_json: str, assets_dir: Path
) -> str:
    """Line: log-likelihood per iteration."""
    try:
        config = json.loads(config_json)
        ll_trace = config.get("ll_trace", [])
    except (json.JSONDecodeError, TypeError):
        ll_trace = []

    if not ll_trace:
        return ""

    fig, ax = plt.subplots(figsize=(10, 6))
    ax.plot(ll_trace, marker='o', linestyle='-', color='steelblue')

    ax.set_xlabel("Iteration")
    ax.set_ylabel("Log-Likelihood")
    ax.set_title("EM Convergence Curve")
    ax.grid(alpha=0.3)

    filename = f"run_{run_id}_convergence_curve.png"
    filepath = assets_dir / filename
    fig.savefig(filepath, dpi=100, bbox_inches='tight')
    plt.close(fig)

    return f"assets/{filename}"


def _render_corroboration_pie(
    conn: sqlite3.Connection, run_id: int, assets_dir: Path
) -> str:
    """Pie: triangulated vs uncorroborated event counts."""
    cursor = conn.execute(
        """
        SELECT corroboration, COUNT(*)
        FROM run_event_result
        WHERE run_id = ?
        GROUP BY corroboration
        """,
        (run_id,),
    )

    rows = cursor.fetchall()
    if not rows:
        return ""

    labels = [row[0] for row in rows]
    sizes = [row[1] for row in rows]

    fig, ax = plt.subplots(figsize=(8, 6))
    ax.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=90)
    ax.set_title("Event Corroboration")

    filename = f"run_{run_id}_corroboration_pie.png"
    filepath = assets_dir / filename
    fig.savefig(filepath, dpi=100, bbox_inches='tight')
    plt.close(fig)

    return f"assets/{filename}"
