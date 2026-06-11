# Feature Specification: STAPLE-News Study Implementation

**Branch**: `development` | **Status**: Draft | **Created**: 2026-06-11
**Input**: paper/STUDY.md (study design), paper/ABSTRACT.md (target claims)

## Overview

Implement the model changes and experiments required to produce the results claimed in
paper/ABSTRACT.md, sufficient for submission to EPJ Data Science. Five experiments (E1–E5),
two model changes (dedup-aware voting, consensus-language reporting), three baselines.

## User Scenarios

### US1 — Researcher runs full experiment suite
A researcher checks out the repo and runs one command per experiment; each produces a
figure (PNG) + results table (CSV/JSON) + a row in a master results manifest, reproducible
from a fixed seed.

### US2 — Reader audits a result
Every number in the paper traces to a manifest entry: experiment id, git SHA, seed, config,
output artifact paths.

## Functional Requirements

### FR1 — Dedup-aware E-step (model change, blocking)
- E-step vote counting MUST route through `dedup_cluster_id`: all articles in one
  near-duplicate cluster contribute ONE effective vote per claim.
- [NEEDS CLARIFICATION: which outlet "owns" the deduplicated vote — first-seen article,
  random member, or fractional credit split across cluster members? Affects per-outlet
  suffstats attribution.]
- Existing suffstats persistence and online update path unchanged otherwise.
- Toggleable via config flag (`dedup_voting: on|off`) so E2 can compare both modes.

### FR2 — Consensus-language reporting (model change)
- All user-facing outputs (CLI report, HTML export, chart labels/captions) MUST say
  "consensus-agreement" / "coverage of consensus claims", never "reliability" or "truth".
- Existing caveat box retained and updated to match.

### FR3 — E1: Synthetic recovery
- Reuse existing `recover/score.py` gate (Spearman ρ ≥ 0.8 vs planted parameters).
- Add: run across [NEEDS CLARIFICATION: how many seeds — 10? 30?] seeds, report mean ± CI.
- Output: `results/e1_recovery.csv` + box plot figure.

### FR4 — E2: Syndication sensitivity sweep (main figure)
- Synthetic corpora with controlled duplicate multiplicity m ∈ {1, 2, 5, 10, 20} applied
  to a designated "wire" source bloc.
- For each m × {dedup on, off}: measure shift in consensus estimates (W_i agreement with
  planted consensus) and outlet-parameter distortion.
- [NEEDS CLARIFICATION: synthetic duplicates — exact copies, or perturbed near-duplicates
  that exercise the simhash banding? Latter is more realistic but couples E2 to dedup
  recall.]
- Output: line figure (distortion vs m, two series) + `results/e2_syndication.csv`.

### FR5 — E3: ISOT application (descriptive)
- Run streaming pipeline on full ISOT with dedup voting on; labels held out.
- Report: outlet parameter distributions, AUC of True-corpus vs Fake-corpus source
  separation (descriptive, including the inverted regime if it occurs).
- [NEEDS CLARIFICATION: ISOT fake corpus is largely single-source — keep per-subject
  synthetic outlets (fake:<subject>) as the unit, or collapse to one fake outlet?]
- Output: distribution figure + AUC table.

### FR6 — E4: External correlation
- Corpus: [NEEDS CLARIFICATION: NELA-GT (which year — 2020/2021/2022?) vs own crawl via
  configs/feeds.yml. NELA-GT ships outlet labels aligned to MBFC; crawl is fresher but
  needs scraping infra.]
- Compute Spearman of per-outlet consensus-agreement vs MBFC factual-reporting rating,
  and vs AllSides left–right rating.
- Success criterion: factual-reporting ρ significantly > 0; |ideology ρ| near 0.
- Output: scatter figures + correlation table with CIs (bootstrap).

### FR7 — E5: Omission audit
- Per-outlet sensitivity computed on corroborated-claim subsets grouped by topic cluster.
- Deliverable: 2–3 case studies (tables + short narratives) + heatmap figure
  (outlet × topic sensitivity).
- [NEEDS CLARIFICATION: topic grouping source — existing event clusters, ISOT subject
  field, or a topic model run over claims?]

### FR8 — Baselines
- Majority vote, article-count-weighted majority, batch Dawid-Skene (same data, no
  streaming) — implemented behind a common interface, reported in E1–E3 tables.

### FR9 — Results manifest
- `results/manifest.json`: one entry per experiment run — experiment id, git SHA, seed,
  config hash, output paths, timestamp.
- Every figure regenerable via `python -m stapled.experiments <eN> --seed S`.

## Non-Functional Requirements

- NFR1: All experiments run on laptop-scale hardware; E3/E4 streaming memory stays
  constant (no full-corpus load).
- NFR2: Fixed seeds → byte-identical CSV outputs (figures may differ in metadata only).
- NFR3: CI smoke lane runs E1 with 2 seeds + E2 with m ∈ {1, 5} as regression guard.

## Out of Scope

- Anchoring experiments (anchor-budget sweep) — Discussion/future-work only.
- Continuous-emission (spin/framing) channel.
- Three-valued D_ij (omission vs contradiction split) — noted as limitation.
- Paper prose beyond paper/ — this spec covers code + results artifacts.

## Dependencies & Assumptions

- ISOT already streamed into stream.db (done; 42,681 articles).
- MBFC/AllSides ratings obtainable as static CSV [NEEDS CLARIFICATION: scrape vs use a
  published snapshot, e.g. the ratings file shipped with NELA-GT?].
- Existing dedup banding (`simhash_bucket`, 4 bands) has adequate recall for wire copies.

## Acceptance Checklist

- [ ] FR1 dedup voting behind flag, unit-tested both modes
- [ ] FR2 language audit passes (grep finds no "reliability"/"truth" in outputs)
- [ ] E1–E5 each produce figure + table + manifest entry from one command
- [ ] Baselines reported alongside in E1–E3
- [ ] CI smoke lane green
- [ ] All [NEEDS CLARIFICATION] resolved before implementation
