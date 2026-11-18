#!/usr/bin/env python
"""One-shot refresh: run E7 consensus over us.db into results_us/.

Mirrors the HANDOFF 4-command recipe step 3. Expects load-us-headlines +
realign-embed to have already populated us.db. Writes results_us/consensus.json
(+ CSVs + PNG); caller copies consensus.json to docs/data/consensus_us.json.
"""
import sys

from stapled.experiments import e7_consensus

DB = sys.argv[1] if len(sys.argv) > 1 else "us.db"
OUT = sys.argv[2] if len(sys.argv) > 2 else "results_us"

result = e7_consensus.run({"db_path": DB, "min_outlets": 5}, seed=42, out_dir=OUT)
print("outputs:", result["outputs"])
print("metrics:", result.get("metrics"))
