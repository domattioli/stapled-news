# Data Model: Atomic Consensus

Existing `article`, `claim`, `event`, and legacy run tables remain unchanged.
Atomic records are versioned and retain original headline text.

## AnalysisRun

Immutable run ID, corpus ref/SHA, cutoff, code revision/SHA, parser artifact/SHA,
grammar/rules/aliases/taxonomy/panel versions and SHAs, config hash,
environment/dependency-lock hash, CPU metadata, canonical semantic hash,
annotation split, estimator mode/status, and evaluation status. Cutoff/as-of and
source published/seen times that affect selection are semantic inputs; only
generated/runtime timestamps and the hash field are excluded. States:
`draft → pilot → frozen → evaluated → exported`, or terminal
`inconclusive|refused`; estimator: `not_run|withheld|published`.

## AspectAssignment

Event/article IDs, taxonomy version, aspect label, assignment rule/confidence,
and nullable `unknown_aspect` reason. Ambiguous and multi-aspect assignment is
explicitly abstained and excluded from matching/scoring.

## HeadlineObservation

Article/outlet/event IDs, URL, title, published/seen time, original text, exact
source span, collection state, reporting-group ID, and provenance.

## AtomOccurrence

One proposition: run/article/event/aspect IDs; subject, predicate, object,
polarity, modality, attribution, quantity, time, location, normalized text,
character span, grammar/rule version, extraction score, nullable abstention
reason. Polarity (`affirmed|negated|uncertain`) and modality
(`asserted|alleged|possible|planned|conditional`) are orthogonal. Attribution
qualifies allegations; it does not assert the underlying event.

## SummaryContentUnit (SCU)

Canonical proposition key/display, event/aspect, classification, orthogonal
`has_dispute`, matching-rule version, and stable ID from
`event|aspect|canonical-key`.

## SCURelation

Occurrence/SCU relation (`support|equivalence|contradiction|possible_conflict`),
governing rule ID/version, compatible-scope summary, evidence occurrence IDs,
and deterministic decision key.

## ReportingGroup

Stable group ID, grouping method/version, member outlets/articles, exact-copy or
demonstrated-lineage evidence, ownership metadata, owner-sensitivity flag, and
cross-stratum home allocation. Event-specific groups collapse evidence for one
signal; source provenance remains visible. Same-group support and contradiction
are both preserved. Estimator parameters are named `theta_source`, persist per
outlet/editorial source, use fixed shrink strength and prior fallback for unseen
sources, and select one canonical source parameter deterministically for a
syndicated family.

## CoverageObservation and SCUObservation

Separate entities. Coverage records event/aspect/group eligibility and state
`eligible|non_coverage|collector_unavailable|unknown_relevance`, reason, cutoff,
and provenance—without reference to SCU mention. SCUObservation records eligible
group state `support|explicit_contradiction|eligible_omission|unknown`, occurrence
IDs, relation/rule evidence, and attribution. Structural absence is masked,
never a negative vote.

## TargetPanel and results

TargetPanel stores roster, taxonomy, strata, weights, unrated policy, ownership,
cross-stratum allocation, and provenance. SCUResult stores raw outlet support,
raw independent-group support, R/M, bounds, effective N, leave-group/stratum
ranges, missing reasons, classification, `has_dispute`, and nullable modeled
score plus estimator status. With zero eligible data, balanced is null, bounds
`[0,1]`, and effective N is 0. Outlet raw counts never substitute for groups.
OutletEventProfile stores event-specific shared/unique/conflict/omission records
after leaving out outlet and demonstrated family; no global outlet score.

## Relationships

`AnalysisRun → AspectAssignment → AtomOccurrence → SCU → SCUResult`;
`Event/Aspect/ReportingGroup → CoverageObservation → SCUObservation`;
`Article/Outlet → ReportingGroup`; `SCURelation` links evidence. Profiles depend
on a completed panel reference and recompute leave-out family evidence.
