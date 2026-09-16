# Research Decisions: Atomic Consensus

## Frozen deterministic extraction

V1 uses built-in rule grammar `atomic-grammar-v1` in
`src/stapled/extract/atomic.py`, with versioned aliases and normalization. It
accepts supported English declarative headline forms only; unsupported
coordination, coreference, scope, entity, or quantity cases abstain with coded
reasons. No generative or external parser is a v1 dependency.

Registry: parser=`atomic-grammar-v1`, taxonomy=`aspect-taxonomy-v1`,
rules=`atomic-rules-v1`, aliases=`atomic-aliases-v1`, and
panel=`atomic-panel-v1`. Changes require a new frozen run and cannot be applied
to held-out evaluation retrospectively.

## Aspect taxonomy and assignment

`aspect-taxonomy-v1` is closed: `occurrence`, `decision`, `appointment`,
`statement`, `proposal`, `legal_action`, `casualty`, `quantity`, `location`,
`time_update`, `other`. Stable keyword/predicate rules assign aspects. Ambiguous
or multi-aspect headlines receive `unknown_aspect` and cannot enter matching or
shared-core scoring. Taxonomy and assignment freeze before held-out evaluation.

## Scope and matching

Occurrences remain separate from canonical SCUs. Matching is event/aspect-local,
then exact-normalized subject/predicate/object, polarity, modality, attribution,
temporal, and quantity scopes. Lexical fallback requires all scopes to agree.
Contradiction requires compatible referents/scope plus exclusive polarity/value;
time updates and compatible numeric revisions are not contradictions. Every
decision stores rule, evidence, and spans.

## Panel estimator

For stratum `s`, let `A_s` be eligible independent groups and `m_s` groups
mentioning an SCU, with declared weights `w_s`, Σw=1. `R=Σobserved w_s`,
`M=1-R`; raw support=`Σm_s/ΣA_s`; balanced support
`B=Σobserved w_s(m_s/A_s)/R`; primary B undefined when R=0. Unconstrained
identification bounds are `[R·B, R·B+M]`. Effective N is Kish
`(Σq)^2/Σq²` over independent-group weights. `shared core` requires ≥2
independent strata, frozen B threshold, minimum R, and no unresolved
aspect/identity ambiguity. `has_dispute` is orthogonal; unrated sources remain
descriptive and excluded from primary B.

Alphabet and masking are explicit. Each eligible group/SCU observation is one
of `support`, `contradiction`, or `eligible_omission`; `unknown` is retained for
descriptive audit but masked from estimation, as are structural absence,
collector failure, non-coverage, and unknown relevance. Masked states are never
negative observations. With no eligible data,
`B=null`, bounds are `[0,1]`, and effective N is 0. For a group, `q_g` is its
declared stratum weight divided equally among eligible independent groups in
that stratum (after any cross-stratum family allocation); `N_eff=(Σq_g)^2/Σq_g²`.
Cross-stratum reporting families receive one deterministic home-stratum
allocation, with alternate allocations included in sensitivity.

## Categorical experimental estimator

Optional model observations are `y ∈ {support, contradiction, omission}` with
latent `z ∈ {core, not_core}`. For source/editorial source s, row-normalized
parameters `theta_source_s[z,y]` define likelihood `P(y|z,s)`; a demonstrated
syndicated family uses one deterministically selected canonical source parameter
(lowest stable source ID), while member evidence remains visible. Independent
observations multiply across groups. EM fits theta_source/posterior z on
annotated training events only,
anchored by pilot labels, Dirichlet α=1, deterministic initialization from the
balanced baseline, max 200 iterations, and convergence when parameter and
log-likelihood deltas are both ≤1e-8 for 3 iterations. Anchors are clamped
(`z` fixed) and never scored as predictions. E-step computes normalized
posterior over `z`; M-step updates each outlet/editorial-source row with
smoothed weighted counts (`count + α·prior`, α=1); persist theta_source per
outlet/editorial source. Use hierarchical shrinkage with fixed strength λ=10
toward stratum hyperparameters and a declared symmetric prior `P(y|z,s)=1/3`
for unseen sources/groups. Unknown and all masked states are absent. Scoring
uses frozen theta_source/prior/anchors and no post-hoc tuning. Export is withheld
unless the primary paired superiority metric beats balanced counting and both
paired non-inferiority control metrics pass.

## Evaluation experiments

Annotation plan is 20 pilot events plus 80 held-out events; current design status
is planned (completed/adjudicated counts must be recorded before evaluation).
Develop on 20 pilot events, freeze all artifacts, then evaluate 80 disjoint
held-out events. Pilot freezes minimum conflict N, recall/coverage floor,
uncertainty method, primary paired superiority metric, two paired
non-inferiority controls, and margins; underpowered results are `inconclusive`.
The estimator’s primary claim is superiority on the paired metric, never merely
non-inferiority. Separate candidate-discovery (found/not found) and
support-scoring (conditional on found) experiments. Sweep panel skew, missing
strata, syndication, ownership, minority details, contradictions, updates, and
outcome-dependent missingness.

## Export and website

Publish separate `docs/data/atomic_consensus.json`; preserve legacy centroid
bundles. Export parser/rules/aliases/taxonomy/panel/corpus/code/environment
provenance, immutable ref/SHA, SHA-256 artifact digests, run hashes, estimator
status, profiles, sensitivity, and missing reasons. Site work runs from the
absolute sibling workdir `/Users/domattioli/Projects/domattioli.github.io`,
fetches an immutable stapled-news commit (ref plus 40/64-character Git SHA),
and validates bundle schema/digests before publishing into the private vault.
Browser contract covers loading, error, empty, and oversized-payload states and
displays cutoff plus source SHA.
