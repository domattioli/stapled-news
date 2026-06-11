# Checklist: STAPLE-News Study (001)

Quality gates per phase. Tick before declaring phase done.

## P1 — Dedup voting (FR1)
- [ ] `w = 1/cluster_size` applied in likelihood (log-space) AND suffstats (cert*w)
- [ ] `dedup_voting=False` produces results identical to pre-change behavior (snapshot test)
- [ ] Cluster key falls back to per-article uniqueness when `dedup_cluster_id` IS NULL
- [ ] CLI flag `--dedup-voting/--no-dedup-voting` threaded to OnlineEM, default on
- [ ] Unit tests: N-cluster weight, singleton weight, mixed event, off-mode identity
- [ ] Full suite green; ruff clean

## P2 — Baselines (FR8)
- [ ] `majority`, `weighted_majority`, `batch_ds` behind `run_baseline()`
- [ ] Hand-computed micro-fixture test per baseline
- [ ] batch_ds reuses `infer/em.py` (no reimplementation)

## P3 — Experiments skeleton + E1 (FR9, FR3)
- [ ] `python -m stapled.experiments e1 --seed S` produces CSV + figure + manifest entry
- [ ] Manifest entry: experiment id, git SHA, seed, config hash, output paths, timestamp
- [ ] Same seed → byte-identical CSV
- [ ] E1: 30 seeds, mean ± 95% CI, ρ ≥ 0.8 gate passes (dedup on and off)
- [ ] `--quick` mode (2 seeds) runs < 2 min

## P4 — E2 syndication sweep (FR4)
- [ ] m ∈ {1,2,5,10,20} × {dedup on, off} grid complete
- [ ] Exact-copy and perturbed-copy modes reported separately
- [ ] Main figure: distortion vs m, two series, FiveThirtyEight style + caption
- [ ] Result direction sanity: dedup-off distortion grows with m; dedup-on ~flat

## P5 — E3 ISOT (FR5)
- [ ] Dedup backfill pass run on stream.db before inference
- [ ] Labels excluded from training path (join only at scoring)
- [ ] Outputs: parameter distribution figure, AUC table, manifest entry
- [ ] Inverted/non-inverted regime reported descriptively, no truth claims

## P6 — E4/E5 (FR6, FR7)
- [ ] E4 scaffolded; if NELA-GT-2022 unavailable in env, manifest entry `pending-data` +
      documented invocation
- [ ] E5 heatmap (outlet × topic sensitivity) + ≥2 case-study tables

## P7 — Language audit (FR2)
- [ ] User-facing outputs say "consensus-agreement"; no "reliability"/"truth" in rendered
      report/HTML/chart labels (DB/internal names exempt)
- [ ] Lint test asserts the above on a rendered report
- [ ] Caveat box text updated

## P8 — CI
- [ ] `--quick` E1+E2 wired into CI test lane
- [ ] Full suite + ruff green on final commit

## Cross-cutting
- [ ] Every commit message `<type>: <imperative>` format
- [ ] No experiment number cited in paper/ without manifest entry behind it
