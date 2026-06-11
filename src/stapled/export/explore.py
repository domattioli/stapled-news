"""Build the interactive dashboard data bundle (docs/data/explore.json).

Aggregates everything the Pages dashboard needs into one committed JSON file so the
static site renders without a database at serve time:
  - outlets: reliability / bias landscape (from an exported run JSON)
  - events: confidence + corroboration distribution (from the same run JSON)
  - trajectory: per-batch reliability snapshots (from a streaming DB)
  - recovery: E1 method-comparison rho values (from results/e1_recovery.csv)
  - dedup: syndication collapse stats (from a streaming DB)
"""

import csv
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Optional


def build_bundle(
    run_json_path: str,
    stream_db_path: Optional[str],
    e1_csv_path: Optional[str],
    out_path: str,
) -> dict:
    """Assemble explore.json from available artifacts. Missing sources are skipped."""
    bundle: dict = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "outlets": [],
        "events": [],
        "trajectory": {"batches": [], "series": []},
        "recovery": {"methods": [], "rho_by_seed": {}},
        "dedup": {},
    }

    # --- Outlets + events from the exported run JSON ---
    if run_json_path and os.path.exists(run_json_path):
        with open(run_json_path) as f:
            run = json.load(f)
        bundle["run_id"] = run.get("run_id")
        for o in run.get("outlets", []):
            bundle["outlets"].append({
                "name": o.get("name"),
                "reliability": o.get("reliability"),
                "bias": o.get("bias"),
                "is_synthetic": str(o.get("name", "")).startswith("fake:"),
            })
        for e in run.get("events", []):
            bundle["events"].append({
                "label": e.get("label"),
                "confidence": e.get("confidence"),
                "corroboration": e.get("corroboration"),
                "state": e.get("inferred_state_text") or e.get("inferred_state"),
                "n_outlets": len(e.get("weights", [])),
            })

    # --- Streaming reliability trajectory + dedup stats ---
    if stream_db_path and os.path.exists(stream_db_path):
        conn = sqlite3.connect(stream_db_path)
        try:
            rows = conn.execute(
                "SELECT batch, outlet_id, reliability FROM reliability_snapshot ORDER BY batch"
            ).fetchall()
            names = dict(conn.execute("SELECT id, name FROM outlet").fetchall())
            batches = sorted({r[0] for r in rows})
            by_outlet: dict = {}
            for batch, oid, rel in rows:
                by_outlet.setdefault(oid, {})[batch] = rel
            bundle["trajectory"]["batches"] = batches
            for oid, series in by_outlet.items():
                bundle["trajectory"]["series"].append({
                    "name": names.get(oid, f"outlet-{oid}"),
                    "values": [series.get(b) for b in batches],
                })

            total = conn.execute("SELECT COUNT(*) FROM article").fetchone()[0]
            clustered = conn.execute(
                "SELECT COUNT(*) FROM article WHERE dedup_cluster_id IS NOT NULL"
            ).fetchone()[0]
            clusters = conn.execute(
                "SELECT COUNT(DISTINCT dedup_cluster_id) FROM article WHERE dedup_cluster_id IS NOT NULL"
            ).fetchone()[0]
            bundle["dedup"] = {
                "total_articles": total,
                "syndicated_articles": clustered,
                "clusters": clusters,
                "effective_after_collapse": total - clustered + clusters,
            }
        finally:
            conn.close()

    # --- E1 recovery rho by method/seed ---
    if e1_csv_path and os.path.exists(e1_csv_path):
        rho_by_seed: dict = {}
        methods = []
        with open(e1_csv_path) as f:
            for row in csv.DictReader(f):
                method = row.get("method")
                try:
                    rho = float(row.get("rho"))
                    seed = int(row.get("seed"))
                except (TypeError, ValueError):
                    continue
                rho_by_seed.setdefault(method, []).append({"seed": seed, "rho": rho})
                if method not in methods:
                    methods.append(method)
        bundle["recovery"]["methods"] = methods
        bundle["recovery"]["rho_by_seed"] = rho_by_seed

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(bundle, f, indent=1)
    return bundle
