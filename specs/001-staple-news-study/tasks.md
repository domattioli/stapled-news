# Tasks: STAPLE-News Study (001)

Tier: H = Haiku subagent (implementation), M = main session (design/review/integration/runs).
[P] = parallelizable with previous task.

## P1 — FR1 dedup voting
- T101 (M) Design weight threading (done in plan D1)
- T102 (H) Modify `online_em.py`: vote_key in `_e_step_from_ids` SQL, per-claim weight
  `w=1/cluster_size`, apply `**w` in likelihood + `cert*w` in suffstats accumulation;
  `dedup_voting` ctor arg (default True); `_e_step_from_dicts` accepts optional
  per-claim `weight` key
- T103 (H) Thread CLI flag in `cli.py` (`train_stream`, `infer`)
- T104 (H) Unit tests: `tests/unit/test_dedup_voting.py`
- T105 (M) Review + run full suite

## P2 — FR8 baselines [P with P1]
- T201 (H) `src/stapled/baselines.py`: majority, weighted_majority, batch_ds wrapper
- T202 (H) `tests/unit/test_baselines.py` micro-fixtures
- T203 (M) Review

## P3 — FR9 + E1
- T301 (H) `src/stapled/experiments/` package: `__main__.py`, `runner.py` (seed, config
  hash, manifest append, output paths), `e1_recovery.py` (30 seeds, ρ ≥ 0.8, baselines
  compared, box plot)
- T302 (H) `tests/unit/test_experiments_runner.py`: manifest determinism, quick mode
- T303 (M) Review, run E1 full, verify gate both dedup modes

## P4 — E2
- T401 (H) `e2_syndication.py`: duplicate injection (exact + perturbed), m-sweep grid,
  distortion metrics, line figure (538 style)
- T402 (M) Run full grid, sanity-check direction, iterate if flat/noisy

## P5 — E3
- T501 (M) Dedup backfill on stream.db; run e3_isot.py (H scaffolds script first)
- T502 (H) `e3_isot.py`: param distributions, AUC vs held-out corpus labels, figures
- T503 (M) Run + interpret

## P6 — E4/E5
- T601 (H) `e4_external.py` scaffold (NELA-GT-2022 loader, MBFC join, Spearman + bootstrap
  CI, scatter) — runs to `pending-data` if dataset absent
- T602 (M) Attempt NELA-GT download in env; else document fetch instructions
- T603 (H) `e5_omission.py`: outlet × topic sensitivity heatmap + case-study tables
- T604 (M) Run E5 on stream.db

## P7 — FR2 language audit
- T701 (H) Sweep `cli.py` report strings, `export/templates/*.j2`, `viz/*.py` labels:
  reliability → consensus-agreement (user-facing only); update caveat box; lint test
- T702 (M) Review rendered output

## P8 — CI
- T801 (M) Wire `--quick` E1/E2 into CI lane; final suite + ruff; commit train

## Status log
- 2026-06-11: P1–P3 dispatched.
