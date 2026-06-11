"""Static site export for inference runs."""

import sqlite3
import json
from pathlib import Path
from jinja2 import Environment, PackageLoader

from stapled.gates import GateError
from stapled.viz.charts import render_all as render_charts


def export_run(conn: sqlite3.Connection, run_id: int, out_dir: str) -> None:
    """Export run to static HTML and JSON. Refuse if run failed gates."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Load run
    cursor = conn.execute(
        "SELECT id, created_at, corpus_id, status FROM inference_run WHERE id = ?",
        (run_id,),
    )
    run_row = cursor.fetchone()
    if not run_row:
        raise ValueError(f"Run {run_id} not found")

    run_id_val, created_at, corpus_id, status = run_row

    # Gate: must be converged
    if status != "converged":
        raise GateError(
            f"Run {run_id} has status '{status}', not 'converged'. "
            "Cannot export non-converged runs."
        )

    # Gate: synthetic run must have PASS recovery verdict
    if corpus_id is not None:
        cursor = conn.execute(
            "SELECT verdict FROM recovery_report WHERE run_id = ?", (run_id,)
        )
        recovery_row = cursor.fetchone()
        if not recovery_row or recovery_row[0] != "PASS":
            raise GateError(
                f"Synthetic run {run_id} lacks PASS recovery verdict. "
                "Run 'stapled score --run {run_id}' first."
            )

    # Load events
    cursor = conn.execute(
        """
        SELECT rer.event_id, e.label, rer.inferred_state, rer.inferred_magnitude_bucket,
               rer.confidence, rer.corroboration, rer.weighting_json
        FROM run_event_result rer
        JOIN event e ON rer.event_id = e.id
        WHERE rer.run_id = ?
        ORDER BY rer.event_id
    """,
        (run_id,),
    )

    events = []
    for event_id, label, state, magnitude, confidence, corroboration, weighting_json in cursor.fetchall():
        weights = json.loads(weighting_json) if weighting_json else []
        # Resolve outlet names
        weight_details = []
        for w in weights:
            cursor2 = conn.execute(
                "SELECT name FROM outlet WHERE id = ?", (w["outlet_id"],)
            )
            outlet_row = cursor2.fetchone()
            weight_details.append({
                "outlet": outlet_row[0] if outlet_row else f"outlet_{w['outlet_id']}",
                "weight": w["weight"],
                "reason": w["reason"],
            })

        events.append({
            "event_id": event_id,
            "label": label,
            "inferred_state": state,
            "inferred_state_text": "happened" if state else "did not happen",
            "magnitude_bucket": magnitude,
            "confidence": confidence,
            "confidence_pct": int(confidence * 100),
            "corroboration": corroboration,
            "weights": weight_details,
        })

    # Load outlets
    cursor = conn.execute(
        """
        SELECT ror.outlet_id, o.name, ror.est_reliability, ror.est_bias, ror.est_calibration
        FROM run_outlet_result ror
        JOIN outlet o ON ror.outlet_id = o.id
        WHERE ror.run_id = ?
        ORDER BY ror.est_reliability DESC
    """,
        (run_id,),
    )

    outlets = []
    for outlet_id, name, reliability, bias, calibration in cursor.fetchall():
        outlets.append({
            "outlet_id": outlet_id,
            "name": name,
            "reliability": reliability,
            "bias": bias,
            "calibration": calibration,
        })

    # Load recovery verdict if available
    gates_info = {"recovery_verdict": None, "recovery_report_id": None}
    if corpus_id is not None:
        cursor = conn.execute(
            "SELECT id, verdict FROM recovery_report WHERE run_id = ?", (run_id,)
        )
        recovery_row = cursor.fetchone()
        if recovery_row:
            gates_info["recovery_verdict"] = recovery_row[1]
            gates_info["recovery_report_id"] = recovery_row[0]

    # Render charts
    chart_files = render_charts(conn, run_id, str(out_path))

    # Build chart metadata (path + captions for template)
    chart_metadata = []
    chart_captions = {
        "reliability_bias_scatter": "Outlet Reliability vs Bias (size = claim count)",
        "reliability_ranking": "Outlet Reliability Ranking",
        "confidence_hist": "Event Confidence Distribution",
        "convergence_curve": "EM Convergence Curve",
        "corroboration_pie": "Event Corroboration",
    }
    for chart_path in chart_files:
        # Extract chart type from filename (e.g., "assets/run_1_reliability_ranking.png" → "reliability_ranking")
        filename = chart_path.split('/')[-1]
        # Remove run_id prefix and .png extension
        chart_type = filename.replace(f"run_{run_id}_", "").replace(".png", "")
        caption = chart_captions.get(chart_type, chart_type)
        chart_metadata.append({
            "path": chart_path,
            "caption": caption,
        })

    # Build run.json
    run_data = {
        "run_id": run_id_val,
        "status": status,
        "created_at": created_at,
        "events": events,
        "outlets": outlets,
        "gates": gates_info,
        "charts": chart_metadata,
    }

    # Write run_<run_id>.json
    run_json_path = out_path / f"run_{run_id_val}.json"
    run_json_path.write_text(json.dumps(run_data, indent=2))

    # Render templates
    env = Environment(
        loader=PackageLoader("stapled.export", "templates"),
        autoescape=True,
    )

    # Render index.html
    index_template = env.get_template("index.html.j2")
    index_html = index_template.render(
        runs=[{"run_id": run_id_val, "status": status, "created_at": created_at}]
    )
    index_path = out_path / "index.html"
    index_path.write_text(index_html)

    # Render run.html
    run_template = env.get_template("run.html.j2")
    run_html = run_template.render(**run_data)
    run_html_path = out_path / f"run_{run_id_val}.html"
    run_html_path.write_text(run_html)

    # Add note for real runs
    if corpus_id is None:
        # Real run: add footer note about derived outlets
        footer_note = "Outlets derived from ISOT dataset labels (reuters + fake:<channel> pseudo-outlets); reliability/bias are model estimates, not editorial judgments."
        # Could add to run_data or template context
        run_data["footer_note"] = footer_note
