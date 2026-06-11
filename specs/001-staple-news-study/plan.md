# Implementation Plan: STAPLE-News Study (001)

**Spec**: spec.md (Clarified) | **Created**: 2026-06-11

## Technical Context

- Python 3.11, typer CLI, sqlite3, numpy, matplotlib; pytest + ruff in CI.
- Inference: `src/stapled/infer/online_em.py` (OnlineEM, streaming Dawid-Skene) and
  `src/stapled/infer/em.py` (batch EM, reusable as baseline).
- Dedup machinery exists: `article.dedup_cluster_id` populated by `ingest/dedup.py`
  (simhash, 4 bands); `gates.py:46` already uses `COALESCE(a.dedup_cluster_id, a.outlet_id)`.
- Synthetic generator: `src/stapled/synth/generator.py` (planted sens/spec per outlet);
  recovery scorer: `src/stapled/recover/score.py` (Spearman gate).
- Data: ISOT fully streamed into `stream.db` (42,681 articles, done=1 cursors).

## Key Design Decisions

### D1 — Fractional dedup voting as per-claim weight (FR1)
One mechanism serves both likelihood and suffstats: each claim row gets weight
`w = 1/cluster_size`, where cluster = `COALESCE(dedup_cluster_id, 'article:'||article_id)`
within the event.

- Likelihood: per-claim factor becomes `p_obs_given_state ** w` (log-space fractional
  vote — a cluster of N syndicated copies contributes exactly one effective vote, split
  as geometric mean over members).
- Suffstats: existing `cert` multiplier becomes `cert * w` in the exp_tp/fp/tn/fn and
  n_obs accumulation. Every member outlet gets 1/N credit (spec FR1 resolution).
- Off mode: `w = 1.0` for all claims → bitwise-identical to current behavior.
- Surface: `OnlineEM(dedup_voting: bool)`, threaded from CLI `--dedup-voting/--no-dedup-voting`
  (default on) and config. SQL in `_e_step_from_ids` gains a `vote_key` column; weight
  computed per event group in Python.

### D2 — Baselines behind one interface (FR8)
New `src/stapled/baselines.py`: `run_baseline(name, conn|events) -> {outlet_id: params, event_posteriors}`
with `name ∈ {majority, weighted_majority, batch_ds}`. `batch_ds` wraps existing
`infer/em.py`. Pure functions, no persistence — experiments call them directly.

### D3 — Experiments package + manifest (FR9)
New `src/stapled/experiments/` package:
- `runner.py`: seed control, config hash, manifest append (`results/manifest.json`),
  figure/CSV output conventions (`results/eN_*.{csv,png}`).
- `e1_recovery.py`, `e2_syndication.py`, `e3_isot.py`, `e4_external.py`, `e5_omission.py`.
- Entry: `python -m stapled.experiments <e1|e2|e3|e4|e5> --seed S [--quick]`.
- `--quick` = reduced grid for CI smoke (E1: 2 seeds; E2: m ∈ {1,5}).

### D4 — E2 duplicate injection
`e2_syndication.py` generates a synthetic corpus (reuse `synth/generator.py`), designates
one "wire" outlet bloc, then injects duplicates of its articles at multiplicity
m ∈ {1,2,5,10,20}: exact copies (main figure) and perturbed copies (~5% token swaps,
robustness figure). Runs OnlineEM with dedup_voting on and off; metric = mean |posterior
shift| on consensus claims + outlet-parameter distortion vs planted values.

### D5 — E3/E4/E5 on real data
- E3: stream.db as-is, dedup voting on, labels (True/Fake corpus membership) joined only
  at scoring time. Outputs: parameter distribution figure + AUC table (descriptive).
- E4: NELA-GT-2022 (network download required — if blocked in this environment, scaffold
  the experiment + document the invocation; mark manifest entry `pending-data`).
- E5: heatmap of per-outlet sensitivity over existing event clusters grouped by ISOT
  subject; 2–3 case-study tables.

### D6 — Language audit (FR2)
Grep-driven sweep over CLI report strings, HTML templates, chart labels:
"reliability" → "consensus-agreement", "truth/true state" → "consensus state" in
user-facing text only (DB column names, internal identifiers unchanged — rename cost not
justified). Caveat box updated. Lint check added to tests (grep assertion on rendered
report output).

## Phases

| Phase | Content | Model tier |
|---|---|---|
| P1 | FR1 dedup voting (online_em.py + cli.py + tests) | Haiku subagent, main reviews |
| P2 | FR8 baselines module + tests | Haiku subagent (parallel with P1) |
| P3 | FR9 experiments package skeleton + manifest + E1 | Haiku subagent |
| P4 | E2 syndication sweep + main figure | Haiku impl, main verifies math |
| P5 | E3 ISOT run + figures | Main session (runs against real DB) |
| P6 | E4/E5 (NELA-GT-dependent) | Scaffold Haiku; run when data available |
| P7 | FR2 language audit + lint test | Haiku subagent |
| P8 | CI smoke lane (`--quick` runs) wired into existing CI | Main session |

## Risks

- R1: NELA-GT-2022 download may exceed environment network policy/disk → E4 scaffolded,
  marked pending; paper can proceed with E1–E3+E5 while data is fetched elsewhere.
- R2: Fractional weighting changes convergence dynamics → E1 regression (ρ ≥ 0.8 gate)
  must pass with dedup_voting on AND off.
- R3: stream.db ISOT articles may have sparse dedup_cluster_id population (dedup ran
  incrementally) → P5 includes a dedup backfill pass before E3.

## Test Plan

- Unit: weight computation (cluster of N → w=1/N; no cluster → w=1), off-mode identity
  (results equal to pre-change snapshot), baselines vs hand-computed micro-fixtures,
  manifest determinism (same seed → same CSV bytes).
- Regression: existing 77-test suite stays green; `recover/score.py` gate passes both modes.
- CI: `--quick` smoke for E1+E2 added to test lane.
