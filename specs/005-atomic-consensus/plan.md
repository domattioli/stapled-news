# Implementation Plan: Atomic Consensus

**Spec:** `spec.md`  
**Status:** Analysis-ready after Cycle-2 fixes; implementation not started  
**Scope:** deterministic atomic analysis, gated categorical estimator, static export, private site

## Pipeline and dependency order

`freeze corpus/panel → taxonomy assignment → reporting groups → event/aspect
eligibility → atom extraction → scoped matching → observations/SCUs → balanced
accounting/sensitivity → held-out evaluation → optional estimator → canonical
export → browser/private site`.

Taxonomy, reporting groups, eligibility, roster, and observation states are
foundational. Labels are downstream. MVP is extraction + matching only when
these dependencies exist; no shared-core claim without panel/eligibility.

## Technical targets

- `src/stapled/migrations/006_atomic_consensus.sql`: schema.
- `src/stapled/analyze/{atomic_run,aspects,reporting_groups,coverage,panel,atomic_match,atomic_summary,atomic_sensitivity,atomic_evaluation}.py`.
- `src/stapled/extract/atomic.py`: built-in `atomic-grammar-v1`.
- `src/stapled/infer/atomic_em.py`: categorical likelihood/EM, fully specified
  in `research.md`, gated and nullable.
- `src/stapled/export/atomic.py`, `src/stapled/cli.py`.
- `docs/data/atomic_consensus.json`, `docs/data/meta.json`; legacy pages kept.
- Website: `domattioli.github.io/scripts/fetch-stapled-news.mjs`,
  `src/content/vault/stapled-news.md`, fetched `/vault/stapled-news/app/`.

## Balanced accounting

For strata s, `A_s` eligible independent groups, `m_s` supporting groups,
weights `w_s`, `R=Σobserved w_s`, `M=1-R`, raw outlet support and raw group
support are reported separately, `B=Σobserved w_s(m_s/A_s)/R`, bounds=`[R·B,R·B+M]`,
effective N=`(Σq)^2/Σq²`. `q_g=w_s/A_s` after deterministic cross-stratum
family home allocation; alternate family allocations appear in sensitivity.
When no eligible groups: `B=null`, bounds=`[0,1]`, N=0. Primary B excludes
unrated sources. Shared-core driver requires ≥2 independent strata, frozen B
threshold, minimum R, and no unresolved aspect/identity ambiguity. `has_dispute`
is orthogonal.

## Gates frozen after pilot

Pilot freezes thresholds, uncertainty method, minimum conflict N, recall/coverage
floor, primary paired superiority metric, two paired non-inferiority control
metrics, and margins. Held-out acceptance requires atom precision ≥.90, match
precision ≥.95, conflict precision ≥.95, and stated recall/coverage floors with
uncertainty. Underpowered results are `inconclusive`. Estimator must beat the
balanced baseline on the primary paired metric and be non-inferior on both
controls; it also requires disjoint train/eval, convergence, and no control
degradation.

## Determinism and hashes

Stable IDs derive from `event|aspect|canonical-key` with sorted collision suffix.
Canonical JSON uses UTF-8, sorted keys, fixed decimal formatting, stable arrays.
Semantic hash covers exact payload, schema, records, rules, parser artifact,
aliases, taxonomy, panel, corpus SHA, code SHA, config, environment lock,
estimator status, cutoff/as-of, and source published/seen times that affect
results; it excludes only generated/runtime timestamps and the hash field itself.
Two pinned CPU runs must match bytes.

## Delivery and compute

Stages: annotate 20 pilot events, freeze, annotate 80 disjoint held-out events,
deterministic CPU compute, evaluate, export, browser validation, site update.
Add `.github/workflows/atomic-consensus.yml`: checkout pinned refs, install locked
deps, run deterministic CPU compute/evaluate, validate schema/hash/digests, and
upload artifacts; never publish modeled scores when `withheld` or `inconclusive`.
Export is staged: incomplete runs remain non-exportable; `inconclusive` and
`refused` are the single unified terminal non-publication status.
Website work executes from sibling absolute workdir
`/Users/domattioli/Projects/domattioli.github.io`, pins immutable ref+SHA, and
validates bundle before build.

## Constitution check

No `.specify` scaffold/local constitution exists; no CLAUDE markers changed.
Plan preserves migrations/tests/static export and avoids public truth or quality
claims. `CITATION.cff` cites stapled-news and methodological inspirations.
Export is staged: incomplete runs remain non-exportable; `inconclusive` and
`refused` are the single unified terminal non-publication status.
