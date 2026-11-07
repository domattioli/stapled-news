"""Milestone-1 rerun: 10 seeds per real-data experiment, outputs under results/rerun_m1/.

Configs mirror stapled.experiments.__main__ (e3, e3b, e4, e4_uci) so the numbers are
comparable with results/manifest.json. Extras that the CLI cannot express:
  * e2 runs its own 10 inner seeds (worlds 42..51) once per dedup method
    (simhash, ncd); both exact and perturbed modes, dedup voting on and off.
  * e6 uses the budgets of the last committed e6 run and one anchor draw per
    outer seed (n_seeds=1), so 10 outer seeds give 10 independent draws.

Usage: .venv/bin/python scripts/rerun_m1.py --db-dir ../dbs [--only e3b,e4]
"""

import argparse
import json
import time
from pathlib import Path

from stapled.experiments import e2_syndication, e3_isot, e3b_fnn, e4_external, e6_anchoring
from stapled.experiments.runner import run_experiment

E6_BUDGETS = [0, 100, 400, 800, 1200, 1600, 2000, 2500]


def plan(db_dir: Path):
    fnn, uci, stream = str(db_dir / "fnn.db"), str(db_dir / "uci.db"), str(db_dir / "stream.db")
    seeds = list(range(42, 52))
    return {
        "e4_uci": (e4_external, {"db_path": uci, "min_outlets": 2, "batch_size": 32,
                                 "min_articles_per_outlet": 5, "min_obs": 3}, seeds),
        "e4": (e4_external, {"quick": False, "db_path": fnn}, seeds),
        "e3b": (e3b_fnn, {"quick": False, "db_path": fnn}, seeds),
        "e2": (e2_syndication, {"quick": False, "n_seeds": 10, "dedup_method": "simhash"}, [42]),
        "e2_ncd": (e2_syndication, {"quick": False, "n_seeds": 10, "dedup_method": "ncd"}, [42]),
        "e6": (e6_anchoring, {"quick": False, "db_path": stream, "budgets": E6_BUDGETS,
                              "n_seeds": 1}, seeds),
        "e3": (e3_isot, {"quick": False, "db_path": stream}, [42]),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db-dir", required=True)
    ap.add_argument("--out", default="results/rerun_m1")
    ap.add_argument("--only", default=None)
    a = ap.parse_args()
    jobs = plan(Path(a.db_dir).resolve())
    names = a.only.split(",") if a.only else list(jobs)
    for name in names:
        module, config, seeds = jobs[name]
        for seed in seeds:
            out_dir = Path(a.out) / name / (f"seed_{seed}" if len(seeds) > 1 else "")
            t0 = time.perf_counter()
            entry = run_experiment(name, module.run, dict(config), seed, out_dir=str(out_dir))
            dt = time.perf_counter() - t0
            print(f"{name} seed={seed} {dt:.1f}s {json.dumps(entry['metrics'])[:300]}", flush=True)


if __name__ == "__main__":
    main()
