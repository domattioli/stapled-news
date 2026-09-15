# Atomic Consensus Research-Quality Checklist

**Purpose:** Unit tests for requirements writing; review scientific claims,
identifiability, sampling, extraction, evaluation, and UI non-overclaim.  
**Created:** 2026-09-15  
**Feature:** [spec.md](../spec.md) · [plan.md](../plan.md)

## Scientific claim boundaries

- [ ] CHK001 Does the specification consistently distinguish reported agreement, balanced support, modeled score, and objective truth? [Consistency, Spec §Purpose, §Target Quantity]
- [ ] CHK002 Are prohibited interpretations (truth, trustworthiness, outlet quality, ideology) explicit for every result surface? [Completeness, Spec §Non-Goals, §FR-024]
- [ ] CHK003 Is “shared core” defined as a frozen operational label rather than a factual assertion? [Clarity, Spec §FR-021a]
- [ ] CHK004 Are high-support propositions that also have conflicts allowed and explained? [Completeness, Spec §FR-022]
- [ ] CHK005 Are claims absent from sampled headlines explicitly outside the system’s inferential scope? [Boundary, Spec §Purpose, §Non-Goals]

## Identifiability and inference

- [ ] CHK006 Does the spec state what can and cannot be identified without external annotations or verified outcomes? [Gap, Spec §FR-027]
- [ ] CHK007 Are support, contradiction, eligible omission, and unknown defined as distinct observables? [Completeness, Spec §FR-026]
- [ ] CHK008 Does the spec prohibit structural absence from becoming a negative vote? [Clarity, Spec §FR-026]
- [ ] CHK009 Are model-training events, anchored reference units, and evaluation events disjoint and measurable? [Measurability, Spec §FR-027–FR-030]
- [ ] CHK010 Is the fallback behavior specified when the experimental estimator fails its preregistered baseline or control gate? [Recovery, Spec §FR-030, §SC-010]
- [ ] CHK011 Are confidence/probability terms qualified so modeled membership cannot be read as factual probability? [Ambiguity, Spec §FR-027]

## Sampling, dependence, and missingness

- [ ] CHK012 Are target roster, strata, weights, cutoff, and provenance mandatory and versioned for each analysis? [Completeness, Spec §FR-016]
- [ ] CHK013 Is “independent reporting group” operationally defined with conservative evidence requirements? [Clarity, Spec §FR-013–FR-014]
- [ ] CHK014 Are exact duplication, demonstrated syndication, common ownership, and unknown dependence distinguished? [Completeness, Spec §FR-013–FR-014]
- [ ] CHK015 Does the specification state whether eligibility is assessed independently of proposition mention? [Clarity, Spec §FR-012]
- [ ] CHK016 Are missing strata represented as bounds or insufficient panel rather than zero support? [Measurability, Spec §FR-018, §SC-009]
- [ ] CHK017 Are unrated sources’ descriptive role and exclusion from the primary balanced score unambiguous? [Consistency, Spec §FR-020a]
- [ ] CHK018 Are collector unavailability, unknown relevance, non-coverage, and eligible omission defined without overlap? [Clarity, Spec §FR-011, §SC-008]
- [ ] CHK019 Are discovery bias and support-estimation bias separately defined with distinct acceptance measures? [Completeness, Spec §FR-031]
- [ ] CHK020 Is the required effective independent sample size interpretation documented for duplicate and ownership sensitivity? [Gap, Spec §FR-019]

## Extraction and matching requirements

- [ ] CHK021 Does “minimal proposition” have a written boundary for conjunctions, coordination, headlines, and fragments? [Ambiguity, Spec §FR-001]
- [ ] CHK022 Are exact source-span, normalization, parser, alias, and abstention requirements complete? [Completeness, Spec §FR-002, §FR-004–FR-005]
- [ ] CHK023 Are attribution and modality rules explicit enough to prevent reported allegations becoming unqualified propositions? [Clarity, Spec §FR-003]
- [ ] CHK024 Are pronouns, ambiguous entities, scope, quantities, dates, and locations covered by explicit abstention or recovery rules? [Coverage, Spec §FR-004, §FR-009]
- [ ] CHK025 Are equivalence and contradiction scopes defined for entity, predicate, polarity, time, quantity, and aspect? [Completeness, Spec §FR-006–FR-010]
- [ ] CHK026 Does the spec define how possible conflicts differ from explicit contradictions? [Gap, Spec §FR-008]
- [ ] CHK027 Are temporal updates and compatible numeric revisions protected from automatic contradiction labels? [Clarity, Spec §FR-009]
- [ ] CHK028 Is match ordering deterministic and independent of input row order? [Measurability, Spec §FR-007]
- [ ] CHK029 Are low-frequency and unique details inspectable without implying falsehood? [Consistency, Spec §FR-023]

## Evaluation and reproducibility

- [ ] CHK030 Are the 20 pilot and 80 held-out events disjoint, frozen, and sufficient for each reported metric? [Completeness, Spec §FR-033a]
- [ ] CHK031 Are precision, recall, coverage, abstention, and uncertainty all required, preventing a high-precision/zero-coverage loophole? [Measurability, Spec §SC-003–SC-006]
- [ ] CHK032 Are accepted-atom, equivalence-match, and explicit-conflict units defined for annotation and scoring? [Clarity, Spec §SC-003–SC-005]
- [ ] CHK033 Does byte-identical reproduction exclude only non-semantic timestamps and include all semantic versions/hashes? [Clarity, Spec §FR-033, §SC-002]
- [ ] CHK034 Are CPU/platform/dependency assumptions and failure behavior documented for reproducibility? [Dependency, Spec §Assumptions]
- [ ] CHK035 Are synthetic stress cases for skew, missing strata, syndication, minority details, contradictions, updates, and outcome-dependent missingness required? [Coverage, Spec §FR-032]
- [ ] CHK036 Is the experimental estimator’s preregistration and null-result retention requirement explicit? [Completeness, Spec §FR-030, §SC-010]

## User interface and public interpretation

- [ ] CHK037 Does each displayed proposition and conflict require exact source text and provenance links? [Completeness, Spec §SC-001]
- [ ] CHK038 Are raw, balanced, modeled, missing-mass, and sensitivity quantities visually and textually distinct? [Clarity, Spec §FR-017–FR-019]
- [ ] CHK039 Are panel limits and missing strata shown beside conclusions rather than hidden in methodology text? [Coverage, Spec §FR-018, §SC-009]
- [ ] CHK040 Does the outlet view describe event-specific coverage without a global quality leaderboard? [Boundary, Spec §FR-024]
- [ ] CHK041 Are legacy headline-centroid results retained and clearly distinguished from atomic results? [Consistency, Spec §FR-025]
- [ ] CHK042 Are UI labels prohibited from using “true fact,” “truth,” “reliability,” or equivalent unsupported claims? [Non-Functional, Spec §Purpose, §FR-024]
- [ ] CHK043 Is the private-vault/site integration boundary documented, including snapshot cutoff and mutable upstream-ref risk? [Dependency, Plan §Website integration]

## Traceability and unresolved risks

- [ ] CHK044 Does every functional requirement map to at least one acceptance scenario or success criterion? [Traceability, Spec §FR-001–FR-034]
- [ ] CHK045 Does every success criterion identify its unit, split, threshold, and uncertainty treatment? [Measurability, Spec §SC-001–SC-010]
- [ ] CHK046 Are annotation-guide ownership, adjudication, and disagreement-resolution requirements specified? [Gap, Spec §Dependencies]
- [ ] CHK047 Are parser/rule changes required to trigger re-annotation or invalidate prior comparisons? [Gap, Spec §FR-005, §SC-002]
- [ ] CHK048 Are export schema evolution, backward compatibility, and oversized static payload behavior specified? [Gap, Contract §atomic-consensus.schema.json]
- [ ] CHK049 Are citation requirements for `stapled-news` and methodological inspirations explicit without implying copied ground truth? [Completeness, Spec §FR-034]
- [ ] CHK050 Are assumptions about English US political headlines, source roster, CPU compute, and annotation availability labeled as assumptions rather than guarantees? [Clarity, Spec §Assumptions]

## Cycle-1 resolution checks

- [ ] CHK051 Is the closed aspect taxonomy, deterministic assignment rule, and `unknown_aspect` behavior specified before proposition labels? [Completeness, Plan §Pipeline]
- [ ] CHK052 Are coverage eligibility and SCU observation requirements separate, with no ambiguity between non-coverage and eligible omission? [Consistency, Data Model §CoverageObservation and SCUObservation]
- [ ] CHK053 Are raw support, balanced support, represented mass, missing mass, bounds, and effective-N equations defined with denominators and zero cases? [Measurability, Plan §Balanced accounting]
- [ ] CHK054 Is the categorical estimator likelihood, observation categories, smoothing, initialization, convergence, anchor/training split, and withheld status specified? [Completeness, Research §Categorical experimental estimator]
- [ ] CHK055 Are candidate discovery and conditional support scoring evaluated as separate sources of bias? [Clarity, Research §Evaluation experiments]
- [ ] CHK056 Are owner sensitivity and demonstrated syndication policies distinct and measurable? [Coverage, Data Model §ReportingGroup]
- [ ] CHK057 Are semantic-hash inputs, stable-ID collision handling, array ordering, and timestamp exclusion complete enough for byte identity? [Reproducibility, Plan §Determinism and hashes]
- [ ] CHK058 Are browser loading, error, empty, oversized-payload, cutoff, and source-SHA requirements defined for the sibling vault paths? [Gap, Plan §Delivery and compute]
- [ ] CHK059 Are structural absence and non-eligible coverage explicitly masked from the estimator alphabet, while eligible omission remains a categorical observation? [Clarity, Research §Panel estimator]
- [ ] CHK060 Are estimator priors, clamped anchors, E/M updates, persisted outlet/source parameters, hierarchical shrinkage, unseen-source fallback, and frozen scoring all specified? [Completeness, Research §Categorical experimental estimator]
- [ ] CHK061 Is superiority on the primary paired metric required in addition to non-inferiority on every control metric? [Consistency, Plan §Gates frozen after pilot]
- [ ] CHK062 Does the semantic hash include cutoff/as-of and result-affecting source times while excluding only generated/runtime timestamps and its own hash field? [Clarity, Plan §Determinism and hashes]
- [ ] CHK063 Are git revision formats, SHA-256 artifact digests, nullable modeled scores, and `inconclusive` statuses unambiguous in the export contract? [Completeness, Contract §analysis]
- [ ] CHK064 Are zero-data values (`B=null`, bounds `[0,1]`, effective N `0`) and cross-stratum family allocation/sensitivity defined? [Measurability, Plan §Balanced accounting]
- [ ] CHK065 Are planned versus completed pilot/held-out annotation and adjudication counts, owners, and isolation requirements explicit? [Gap, Research §Evaluation experiments]
