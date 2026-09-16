# Tasks: Atomic Consensus

**Status:** Design complete; implementation pending review  
**Rule:** TDD order within every workstream; no labels before panel/aspect/
coverage dependencies. Every task has exact path.

## Dependency graph

`T001–T006 → T007–T016 → T017–T028 (US1) → T029–T035 (US2) →
T036–T044 (US3) → T045–T054 (US4) → T055–T062 (polish/site)`.

## Phase 1 — Setup and frozen inputs

- [x] T001 Create atomic package/version registry at `src/stapled/atomic/__init__.py`
- [x] T002 [P] Record `atomic-grammar-v1`, `aspect-taxonomy-v1`, aliases, rules, and panel versions in `specs/005-atomic-consensus/research.md`
- [x] T003 [P] Write ownership, adjudication, and disagreement protocol for 20 pilot/80 held-out events in `docs/ATOMIC_ANNOTATION_GUIDE.md`
- [x] T004 [P] Add locked CPU compute workflow specification in `.github/workflows/atomic-consensus.yml`
- [x] T005 [P] Add contract/schema validation policy in `pyproject.toml`
- [x] T006 [P] Add simulator parameter registry for panel skew, missingness, syndication, ownership, minority details, contradictions, updates, and outcome-dependent missingness in `configs/atomic-simulator.yml`

## Phase 2 — Foundation (blocking)

- [x] T007 Add migration tables for runs, taxonomy assignments, occurrences, SCUs, relations, reporting groups, coverage, SCU observations, panels, profiles, and results in `src/stapled/migrations/006_atomic_consensus.sql`
- [x] T008 [P] Write contract fixture validation in `tests/unit/test_atomic_contract.py`
- [x] T009 [P] Write semantic canonical JSON/hash tests (timestamps excluded; all semantic SHAs included) in `tests/unit/test_atomic_canonical.py`
- [x] T010 [P] Write taxonomy assignment and `unknown_aspect` determinism tests in `tests/unit/test_atomic_aspects.py`
- [x] T011 [P] Write reporting-group lineage and owner-sensitivity tests in `tests/unit/test_reporting_groups.py`
- [x] T012 [P] Write event/aspect eligibility and distinct collection-state tests in `tests/unit/test_atomic_coverage.py`
- [x] T013 Implement immutable run metadata, stable IDs, canonical serialization, and semantic hashing in `src/stapled/analyze/atomic_run.py` and `src/stapled/export/atomic.py`
- [x] T014 Implement `aspect-taxonomy-v1`, deterministic assignment, and explicit unknown reasons in `src/stapled/analyze/aspects.py`
- [x] T015 Implement conservative reporting groups, ownership metadata, and lineage evidence in `src/stapled/analyze/reporting_groups.py`
- [x] T016 Implement coverage eligibility and frozen target-panel roster/strata/weights, independent of SCU mention, in `src/stapled/analyze/coverage.py` and `src/stapled/analyze/panel.py`

## Phase 3 — User Story 1: Inspect event account (P1)

**Independent gate:** exact-span atoms and rule evidence; ambiguous cases
abstain; compatible propositions match order-stably; conflicts remain visible;
no shared-core label without panel dependencies.

- [ ] T017 [US1] Write extraction tests for subject/predicate/object, quantities, time/location, exact spans, attribution, orthogonal polarity/modality, and abstention in `tests/unit/test_atomic_extract.py`
- [ ] T018 [US1] Write matching tests for event/aspect scope, aliases, order stability, temporal/numeric updates, polarity conflicts, and governing rules in `tests/unit/test_atomic_match.py`
- [x] T019 [US1] Write SCU/classification tests including orthogonal `has_dispute` and missing-dependency refusal in `tests/unit/test_atomic_classification.py`
- [x] T020 [US1] Implement built-in `atomic-grammar-v1` extraction and span capture in `src/stapled/extract/atomic.py`
- [ ] T021 [US1] Implement versioned normalization, attribution, polarity/modality, aliases, and abstention reasons in `src/stapled/extract/atomic.py`
- [x] T022 [US1] Implement event/aspect-scoped equivalence and compatibility matching in `src/stapled/analyze/atomic_match.py`
- [x] T023 [US1] Implement explicit contradiction/possible-conflict rules with evidence in `src/stapled/analyze/atomic_match.py`
- [x] T024 [US1] Implement SCU grouping and downstream-only classification in `src/stapled/analyze/atomic_summary.py`
- [x] T025 [US1] Write/export exact evidence URL, occurrence ID, rule, and span contract fixtures in `tests/unit/test_atomic_export.py`
- [x] T026 [US1] Export event facts, conflicts, evidence, and abstentions in `src/stapled/export/atomic.py`
- [x] T027 [US1] Add staged extraction/matching/summary CLI commands and refusal paths in `src/stapled/cli.py`
- [ ] T028 [US1] Run 20 pilot annotations and record precision, recall, coverage, abstention, and uncertainty in `docs/ATOMIC_ANNOTATION_GUIDE.md`

## Phase 4 — User Story 2: Inspect outlet coverage (P1)

**Independent gate:** coverage, omission, non-coverage, collector failure, and
unknown relevance remain distinct; outlet/family leave-out is explicit; no
global quality score.

- [ ] T029 [US2] Write outlet profile tests for shared, unique, conflict, omission, and all coverage states in `tests/integration/test_atomic_outlet_profile.py`
- [x] T030 [US2] Implement separate eligible-group SCU observations, preserving same-group support plus contradiction evidence, in `src/stapled/analyze/atomic_observations.py`
- [ ] T031 [US2] Implement leave-out outlet-event profiles only after panel reference is available, recomputing excluded outlet and reporting-family evidence in `src/stapled/analyze/atomic_profiles.py`
- [ ] T032 [US2] Write profile/export schema tests for nullable scores, provenance, and no quality leaderboard in `tests/unit/test_atomic_profiles_export.py`
- [ ] T033 [US2] Export profiles, coverage states, missing reasons, and provenance in `src/stapled/export/atomic.py`
- [x] T034 [US2] Add outlet profile CLI/report command in `src/stapled/cli.py`
- [ ] T035 [US2] Run US2 gate over duplicate wire copy, collector failure, omission, and attributed allegations in `tests/integration/test_atomic_outlet_profile.py`

## Phase 5 — User Story 3: Audit sampling effects (P1)

**Independent gate:** raw/balanced values, equations, missing bounds, effective
N, and sensitivity are visible; duplication invariance holds; unrated panel is
descriptive-only.

- [x] T036 [US3] Write raw/balanced equation and missing-mass bound tests in `tests/unit/test_atomic_panel.py`
- [ ] T037 [US3] Write effective-N, duplicate, owner, leave-group, and leave-stratum sensitivity tests in `tests/unit/test_atomic_sensitivity.py`
- [x] T038 [US3] Write simulator candidate-discovery versus support-scoring experiment tests in `tests/unit/test_atomic_simulator.py`
- [ ] T039 [US3] Integrate frozen panel config, unrated policy, ownership policy, and provenance into run metadata in `src/stapled/analyze/panel.py`
- [x] T040 [US3] Implement raw support, balanced `B`, represented `R`, missing `M`, bounds, and shared-core driver in `src/stapled/analyze/atomic_summary.py`
- [ ] T041 [US3] Implement effective independent N, owner-sensitivity allocations, and leave-group/stratum ranges in `src/stapled/analyze/atomic_sensitivity.py`
- [ ] T042 [US3] Implement simulator and parameter sweeps separating discovery bias from support-estimation bias in `src/stapled/experiments/atomic_simulator.py`
- [ ] T043 [US3] Export panel accounting, owner-sensitivity ranges, missing reasons, and nullable modeled fields in `src/stapled/export/atomic.py`
- [ ] T044 [US3] Run US3 gate on skew/missing/syndication/ownership/minority/update scenarios in `tests/integration/test_atomic_panel.py`

## Phase 6 — User Story 4: Reproduce and evaluate (P1)

**Independent gate:** frozen 20/80 isolation, measurable uncertainty and
minimum-N rules, byte-identical semantic output, categorical estimator only
published after paired non-inferiority/control gates.

- [ ] T045 [US4] Write held-out annotation isolation and metric tests in `tests/unit/test_atomic_evaluation.py`
- [ ] T046 [US4] Write categorical likelihood, EM convergence, anchor, and refusal tests in `tests/unit/test_atomic_em.py`
- [ ] T047 [US4] Write two-clean-run byte identity tests covering cutoff/as-of and result-affecting source published/seen times, excluding only generated/runtime timestamps and hash field in `tests/integration/test_atomic_reproducibility.py`
- [ ] T048 [US4] Implement precision/recall/coverage/abstention, uncertainty, minimum conflict N, and inconclusive status in `src/stapled/analyze/atomic_evaluation.py`
- [ ] T049 [US4] Implement frozen 20-pilot/80-held-out split and adjudication ownership checks in `src/stapled/analyze/atomic_evaluation.py`
- [ ] T050 [US4] Implement categorical `support|contradiction|omission` likelihood EM with unknown/masked states excluded, α=1 weighted counts, fixed λ=10 shrinkage, deterministic syndicated-family source selection, anchors, max-200/3×1e-8 convergence, and disjoint fitting in `src/stapled/infer/atomic_em.py`
- [ ] T051 [US4] Implement paired baseline superiority plus paired non-inferiority on every control and balanced-control gate with `published|withheld|inconclusive` status in `src/stapled/infer/atomic_em.py`
- [ ] T052 [US4] Add staged export semantics: draft/pilot/frozen/evaluated/exported and unified `inconclusive|refused` terminal status, evaluation/estimator metadata, hashes, and metrics in `src/stapled/export/atomic.py`
- [ ] T053 [US4] Add evaluate/reproduce/estimator CLI commands and refusal paths in `src/stapled/cli.py`
- [ ] T054 [US4] Complete explicit 80-event held-out annotation/adjudication milestone, run locked CPU workflow, and record planned-versus-completed counts plus SC-002–SC-010 results in `docs/ATOMIC_EVALUATION.md` and `.github/workflows/atomic-consensus.yml`

## Phase 7 — Polish and website follow-up

- [ ] T055 Add schema/rules/parser/panel/corpus/code/environment SHAs and export cutoff to `docs/data/meta.json` in `src/stapled/export/atomic.py`
- [ ] T056 Specify browser loading/error/empty/oversized-payload behavior and test static paths in `tests/integration/test_atomic_browser_contract.py`
- [ ] T057 Preserve and label legacy centroid pages while adding atomic explorer to `docs/consensus.html`
- [ ] T058 Add atomic bundle navigation and non-overclaim UI copy to `docs/consensus.html`
- [ ] T059 Update build-time fetch/ref/SHA/freshness handling in `domattioli.github.io/scripts/fetch-stapled-news.mjs`
- [ ] T060 Update private vault links/status and atomic-vs-legacy wording in `domattioli.github.io/src/content/vault/stapled-news.md`
- [ ] T061 Add software citation and methodological references in `CITATION.cff`, `README.md`, and `docs/ATOMIC_EVALUATION.md`
- [ ] T062 Run pytest/ruff/test_consensus.js, schema validation, browser contract, npm check/build, and final non-overclaim review in `docs/ATOMIC_EVALUATION.md`

## Parallelism and sequencing

Tests within each phase may parallelize only when they touch disjoint fixtures;
implementation follows its tests. T010–T012 precede any labels. T014–T016
precede T024 and all panel results. T038 precedes simulator implementation.
T045–T047 precede estimator/export claims. T056 precedes T057–T060 so browser
requirements/tests gate UI changes. T055–T061 wait for T054. Site work is a
follow-up after verified upstream export, never a substitute for gates.

## MVP

MVP ends at T028: deterministic atoms, aspect assignment, scoped matching,
evidence, conflicts, and pilot measurements. It does not publish shared-core
scores without panel dependencies or any experimental model. Research-result
and website refresh require T029–T062.
