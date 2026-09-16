# Feature Specification: Atomic Consensus

**Status:** Draft for clarification  
**Created:** 2026-09-15  
**Scope:** Deterministic atomic-content analysis of multi-outlet event headlines

## Purpose

For a news event, derive small, auditable propositions from collected headlines and show which propositions recur across a declared, balanced panel of independent reporting groups. Separate broad shared reporting from disputed reports, partial coverage, unique details, and insufficient sampling.

The feature measures reported agreement. It does not determine objective truth, grade outlet quality, or infer claims absent from all sampled headlines.

## Clarifications

### Session 2026-09-15

- Q: What operational rule defines a reference `shared core` unit? → A: A proposition must appear in at least two independent source strata and meet a frozen balanced-support threshold.
- Q: What real-event annotation budget follows the pilot? → A: Annotate 20 pilot events and 80 frozen held-out events.
- Q: How do unrated sources enter the target panel? → A: Keep them as a separate descriptive panel; exclude them from the primary left/center/right balanced score.
- Q: What is the v1 parser? → A: Built-in deterministic `atomic-grammar-v1`; unsupported or multi-aspect forms abstain with a reason.
- Q: What annotation status is currently known? → A: Budget is 20 pilot + 80 held-out events; completed/adjudicated counts remain planned until recorded.

## Target Quantity

For event `e`, analysis cutoff `t`, aspect `a`, and proposition `k`, estimate how often independent reporting groups mention `k` among target-panel groups observed covering `a` of `e` by `t`.

The system MUST report three distinct quantities when available:

1. observed support in captured headlines;
2. standardized support across represented target-panel strata;
3. experimental modeled core-membership score, only after independent validation.

“Balanced” describes a declared comparison design, not public opinion, factual truth, or ideological neutrality.

For stratum `s`, `A_s` means eligible independent reporting groups and `m_s`
means groups supporting a proposition. With weights `w_s`, represented mass is
`R=Σobserved w_s`, missing mass `M=1-R`, raw outlet and raw group support are
reported separately, balanced support is `B=Σobserved w_s(m_s/A_s)/R`, and
identification bounds are `[R·B,R·B+M]`. Group weight is `q_g=w_s/A_s` after
one deterministic home-stratum allocation for cross-stratum families; alternate
allocations are sensitivity. `N_eff=(Σq_g)^2/Σq_g²`. If no eligible groups,
`B=null`, bounds `[0,1]`, `N_eff=0`.

## User Scenarios and Testing

### Scenario 1: Inspect an event account

A reader opens an event and sees atomic propositions with their supporting and contradicting headlines, independent reporting-group count, panel representation, cutoff, and sensitivity to source composition.

**Acceptance scenarios:**

- A proposition repeated across independent panel strata is labeled `shared core`.
- A proposition supported within narrow or incomplete coverage is labeled `partial coverage` or `insufficient panel`.
- An explicit incompatible assertion is shown alongside, not erased by majority aggregation.
- Every displayed proposition and conflict links to exact source text.

### Scenario 2: Inspect outlet coverage

A reader selects one outlet within an event and sees shared units included, unique details added, explicit conflicts, and eligible omissions.

**Acceptance scenarios:**

- Non-coverage, collection failure, unknown relevance, and eligible omission remain distinct.
- Omission is described as headline coverage, never deception or falsehood.
- Shared wire material remains visible but does not create multiple independent votes.
- No scalar outlet-quality score is displayed.

### Scenario 3: Audit sampling effects

A researcher compares raw, syndication-collapsed, and balanced-panel results and can see how missing source strata constrain conclusions.

**Acceptance scenarios:**

- Missing target-panel mass is displayed rather than silently redistributed.
- Results include an effective independent sample size and source-removal sensitivity range.
- Candidate-discovery loss and support-estimation bias are evaluated separately.

### Scenario 4: Reproduce an analysis

A researcher reruns a frozen analysis and obtains identical canonical propositions, matches, classifications, and scores.

**Acceptance scenarios:**

- Each run records corpus, code, rules, parser, aliases, source panel, and configuration versions.
- Two clean pinned CPU runs produce byte-identical canonical outputs, excluding non-semantic timestamps.
- Uncertain extraction and matching abstain with a reason instead of guessing.

## Functional Requirements

### Atomic extraction

- **FR-001:** The system MUST deterministically decompose supported English declarative headlines into minimal propositions.
- **FR-002:** Each occurrence MUST preserve its original text span and record subject, predicate, object, polarity, modality, attribution, quantities, time, and location when explicitly recoverable.
- **FR-003:** Attributed speech MUST remain attributed: “X alleges Y did Z” supports the allegation event, not the unqualified proposition “Y did Z.”
- **FR-004:** Ambiguous entities, pronouns, scope, or parsing MUST produce an abstention reason.
- **FR-004a:** Ambiguous or multi-aspect assignment MUST produce `unknown_aspect` and be excluded from matching and shared-core scoring.
- **FR-005:** Extraction rules, aliases, parser artifact, and normalization rules MUST be versioned.

### Proposition matching

- **FR-006:** Occurrences MAY match only within compatible event/aspect, entity, predicate, polarity, attribution, temporal, and quantitative scopes.
- **FR-007:** Matching MUST be deterministic and order-stable.
- **FR-008:** Contradiction MUST require compatible referents and scope plus mutually exclusive polarity or values.
- **FR-009:** Time updates and compatible numeric statements MUST NOT be labeled contradictions automatically.
- **FR-010:** Every equivalence or contradiction decision MUST record its governing rule and evidence.

### Coverage and dependence

- **FR-011:** The system MUST distinguish support, explicit contradiction, eligible omission, unknown relevance, non-coverage, and collector unavailability.
- **FR-011a:** Structural absence, non-coverage, collector unavailability, and unknown relevance MUST be masked from the SCU observation alphabet; eligible omission remains a distinct categorical observation.
- **FR-012:** Eligibility MUST be based on event aspect independently of whether the target proposition is mentioned.
- **FR-013:** Exact and demonstrated syndicated reporting groups MUST contribute one independent signal while preserving per-outlet provenance.
- **FR-014:** Common ownership MUST be exposed as a dependence sensitivity dimension, not automatically treated as one report.
- **FR-015:** Missing collection data MUST NOT be interpreted as editorial non-coverage.

### Panel accounting

- **FR-016:** Each analysis MUST declare a target source roster, strata, weights, and provenance.
- **FR-017:** Raw and balanced results MUST be shown separately.
- **FR-018:** Missing target-stratum mass MUST be reported with identification bounds; it MUST NOT be silently reallocated.
- **FR-019:** Results MUST include raw source count, independent-group count, effective sample size, represented target mass, and leave-group/stratum-out sensitivity.
- **FR-020:** Unrated sources MUST remain visible and separate until an explicit target-panel policy assigns them.
- **FR-020a:** In v1, unrated sources MUST remain a separate descriptive panel and MUST NOT affect the primary left/center/right balanced score.

### Classification and presentation

- **FR-021:** Event propositions MUST use these non-truth labels: `shared core`, `partial coverage`, `disputed reports`, `unique detail`, and `insufficient panel`.
- **FR-021a:** A `shared core` proposition MUST appear in at least two independent source strata and meet a balanced-support threshold frozen before held-out evaluation.
- **FR-022:** A proposition MAY be both high-support and disputed.
- **FR-023:** Low-frequency propositions MUST remain inspectable and MUST NOT be labeled false solely from frequency.
- **FR-024:** Outlet views MUST use event-specific coverage descriptions and MUST NOT publish a global quality leaderboard in v1.
- **FR-025:** Legacy headline-centroid results MUST remain available and clearly distinct from atomic-consensus results.

### Experimental estimator

- **FR-026:** Any categorical STAPLE-style extension MUST use only support, contradiction, and eligible omission observations; unknown, structural absence, non-coverage, collection failure, and unknown relevance are masked from estimation and contribute no negative vote.
- **FR-027:** Core membership MUST be anchored by independently annotated reference units; unanchored model output MUST NOT be called truth or probability.
- **FR-028:** Source-response parameters MUST be fit on events disjoint from evaluation events.
- **FR-029:** Outlet assessment MUST exclude that outlet and its demonstrated reporting family from its reference result.
- **FR-030:** Experimental modeled scores MUST ship only if they beat preregistered simple baselines without degrading balanced-control behavior; otherwise the balanced descriptive baseline remains the product result.
- **FR-030a:** The experimental estimator MUST demonstrate superiority on a preregistered primary paired metric and non-inferiority on every preregistered control metric; underpowered results are `inconclusive`.

### Research and citation

- **FR-031:** Discovery bias and support-estimation bias MUST be measured separately.
- **FR-032:** Synthetic evaluation MUST include skewed panels, missing strata, syndication, minority details, contradictions, temporal updates, and outcome-dependent missingness.
- **FR-033:** Real evaluation MUST use frozen extraction/matching rules on held-out independently annotated events.
- **FR-033a:** The annotation program MUST cover 20 pilot events for rule development and 80 disjoint held-out events for final evaluation.
- **FR-033b:** The run MUST record planned, completed, and adjudicated counts plus annotation owners; held-out events MUST remain isolated from rule tuning.
- **FR-034:** Repository documentation MUST instruct users to cite `stapled-news` itself; STAPLE, Dawid–Skene, Pyramid, and dependence-aware truth discovery MUST be described as methodological inspirations.

## Key Entities

- **Analysis run:** immutable versions and hashes defining a reproducible result.
- **Headline observation:** captured source text plus outlet, event, URL, and timing provenance.
- **Atom occurrence:** structured proposition extracted from one headline span.
- **Summary content unit:** canonical proposition grouping compatible occurrences.
- **SCU relation:** support, equivalence, contradiction, or possible conflict with evidence.
- **Reporting group:** demonstrated shared reporting lineage or conservative duplicate cluster.
- **Source metadata:** versioned source identity, strata, ownership, and provenance.
- **Coverage observation:** event/aspect eligibility and collection state for one reporting group.
- **SCU observation:** one group’s support, contradiction, eligible omission, or unknown state.
- **SCU result:** raw, balanced, sensitivity, and optional modeled outputs.
- **Outlet-event profile:** descriptive coverage relative to a leave-out reference.

## Non-Goals

- Objective factual verification or metaphysical truth inference.
- Outlet truthfulness, trustworthiness, or quality grades.
- Claims absent from every sampled headline.
- Generative-model extraction or adjudication.
- Full-article comprehension in v1.
- Automatic ideological classification.
- Unrestricted open-domain contradiction detection.
- Automatic production deployment or publication conclusions.

## Success Criteria

- **SC-001:** Every displayed proposition or conflict links to exact original headline text.
- **SC-002:** Two pinned clean runs produce identical canonical analysis artifacts.
- **SC-003:** Held-out accepted-atom precision reaches at least 0.90.
- **SC-004:** Held-out proposition-match precision reaches at least 0.95.
- **SC-005:** Held-out explicit-conflict precision reaches at least 0.95.
- **SC-006:** Recall, coverage, and abstention are reported with uncertainty; a high-precision system with negligible coverage does not pass.
- **SC-007:** Duplicating known syndicated headlines changes neither balanced support nor effective independent sample size.
- **SC-008:** Every excluded or absent source has a visible reason category.
- **SC-009:** Missing panel strata widen bounds or trigger `insufficient panel`; they never become zero-support votes.
- **SC-010:** The experimental estimator advances only with a preregistered event-paired improvement over balanced counting; a null result is retained and reported.

## Assumptions

- Initial domain is English-language US political-event headlines.
- CPU-only GitHub workspace compute is available.
- The primary comparison panel uses fixed left/center/right strata; unrated sources remain a separate descriptive panel and do not affect its score.
- Demonstrated syndication is collapsed; ownership is analyzed through sensitivity rather than assumed equivalence.
- Human annotation is available for 20 pilot events and 80 disjoint held-out events.
- The public-facing target is a panel-adjusted account of reported propositions, not a verified fact list.

## Dependencies

- A frozen source roster and stratum policy.
- A written annotation guide and independently annotated reference set.
- Versioned collection-health and source-provenance data.
- A pinned deterministic parser artifact and reproducible execution environment.
