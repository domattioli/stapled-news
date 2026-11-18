"""Golden fixture for the browser "Fool the crowd" demo (JS port parity, SC-001).

Each case is a batch-DS input (``events``) plus the Python reference outputs of
``baselines._majority_vote`` and ``baselines._batch_ds`` and the Spearman rho of
planted vs. (sens + spec) / 2 over the original outlets.

Cases (55, schema 1):
  * ``world-sNN`` (35): ``synth.generator.generate`` worlds at seed 42 + NN with
    configs/synth-baseline.yml, the same worlds E1 uses. NN < 30 also carry
    ``e1_csv_rho`` read from results/e1_recovery.csv.
  * ``copy-mNN`` (20): the seed-42 world with m - 1 exact copies of the least
    reliable outlet (the E2 wire) added as new outlets, m = 1..20. Copies repeat
    the source's observation and certainty on every event, as the demo's
    world.js does; they have no planted value and are left out of rho.
"""

import csv
import json
import os
import tempfile
from pathlib import Path

import yaml

from stapled.baselines import _batch_ds, _majority_vote
from stapled.db import connect
from stapled.experiments.e1_recovery import _build_events_for_baselines, _compute_rho
from stapled.synth.generator import generate

SCHEMA = 1
BASE_SEED = 42
N_WORLDS = 35
N_E1_SEEDS = 30
MAX_M = 20


def seeded_world(synth_config: dict, seed: int):
    """Return (events, planted) for one generator world."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    try:
        conn = connect(db_path)
        corpus_id = generate(conn, synth_config, seed=seed)
        planted = dict(conn.execute(
            "SELECT outlet_id, reliability FROM outlet_truth WHERE corpus_id = ?",
            (corpus_id,),
        ).fetchall())
        event_ids = [r[0] for r in conn.execute(
            "SELECT id FROM event WHERE corpus_id = ? ORDER BY id", (corpus_id,))]
        events = _build_events_for_baselines(conn, event_ids)
        conn.close()
        return events, planted
    finally:
        try:
            os.remove(db_path)
        except OSError:
            pass


def add_copies(events: list[dict], src_outlet: int, m: int) -> list[dict]:
    """Copy of ``events`` with m - 1 new outlets repeating ``src_outlet``'s claims."""
    max_id = max(c["outlet_id"] for e in events for c in e["claims"])
    out = []
    for e in events:
        claims = [dict(c) for c in e["claims"]]
        src = next(c for c in e["claims"] if c["outlet_id"] == src_outlet)
        for k in range(1, m):
            claims.append({"outlet_id": max_id + k, "observation": src["observation"],
                           "certainty": src["certainty"]})
        out.append({"event_id": e["event_id"], "claims": claims})
    return out


def _expected(events: list[dict], planted: dict[int, float]) -> dict:
    exp = {}
    for name, fn in (("majority", _majority_vote), ("batch_ds", _batch_ds)):
        res = fn(events)
        params = {str(k): {"sens": float(v["sens"]), "spec": float(v["spec"])}
                  for k, v in res["outlet_params"].items()}
        exp[name] = {
            "posteriors": {str(k): float(v) for k, v in res["posteriors"].items()},
            "outlet_params": params,
            "rho": _compute_rho(planted, res["outlet_params"]),
        }
    return exp


def read_e1_csv(path: Path) -> dict[int, dict[str, float]]:
    out: dict[int, dict[str, float]] = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            out.setdefault(int(row["seed"]), {})[row["method"]] = float(row["rho"])
    return out


def build_fixture(synth_config: dict, e1_csv: Path | None = None) -> dict:
    e1 = read_e1_csv(e1_csv) if e1_csv and Path(e1_csv).is_file() else {}
    cases = []
    base_events = base_planted = None
    for s in range(N_WORLDS):
        events, planted = seeded_world(synth_config, BASE_SEED + s)
        if s == 0:
            base_events, base_planted = events, planted
        case = {
            "id": f"world-s{s:02d}",
            "kind": "world",
            "seed": BASE_SEED + s,
            "m": 1,
            "planted": {str(k): float(v) for k, v in planted.items()},
            "events": events,
            "expected": _expected(events, planted),
        }
        if s < N_E1_SEEDS and s in e1:
            case["e1_csv_rho"] = {k: e1[s][k] for k in ("majority", "batch_ds") if k in e1[s]}
        cases.append(case)

    wire = min(base_planted, key=lambda o: base_planted[o])
    for m in range(1, MAX_M + 1):
        events = add_copies(base_events, wire, m)
        cases.append({
            "id": f"copy-m{m:02d}",
            "kind": "copy",
            "seed": BASE_SEED,
            "m": m,
            "copy_source": wire,
            "planted": {str(k): float(v) for k, v in base_planted.items()},
            "events": events,
            "expected": _expected(events, base_planted),
        })
    return {
        "schema": SCHEMA,
        "generator": "stapled.export.ftc_golden",
        "synth_config": "configs/synth-baseline.yml",
        "tolerance": 1e-6,
        "cases": cases,
    }


def write_fixture(out: Path, synth_config_path: str = "configs/synth-baseline.yml",
                  e1_csv: str | None = "results/e1_recovery.csv") -> dict:
    with open(synth_config_path) as f:
        synth_config = yaml.safe_load(f)
    fx = build_fixture(synth_config, Path(e1_csv) if e1_csv else None)
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(fx, indent=1, sort_keys=False) + "\n")
    return fx
