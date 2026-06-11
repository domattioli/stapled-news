# Study Design: Streaming Truth Discovery for News Outlet Reliability and Omission Auditing

## Working title

**"Consensus Is Not Truth: Streaming STAPLE for News Outlet Reliability, Its Majority-Capture
Failure Mode, and a Cheap Fix"**

## Research questions

- **RQ1 (Transfer):** Does the STAPLE/Dawid-Skene latent-truth model transfer from spatial
  voxels to atomic news claims — i.e., can it recover planted outlet reliabilities from
  synthetic corpora and separate labeled-reliable from labeled-unreliable sources on real data?
- **RQ2 (Failure):** Under what conditions does unsupervised consensus inference invert
  (majority-capture), and can the inversion be predicted from corpus composition?
- **RQ3 (Fix):** Do two cheap interventions — (a) sparse factual anchoring (<1% of claims)
  and (b) syndication-deduplicated voting — restore truth-aligned reliability estimates
  without full supervision?
- **RQ4 (Utility):** Do the resulting per-outlet parameters correlate with independent
  third-party ratings (MBFC factual-reporting, AllSides), and does the omission channel
  (sensitivity p_j) surface interpretable selection-bias patterns?

## Method (already implemented in this repo)

- Online/stepwise EM (Cappé–Moulines), Robbins–Monro step γ_t = (t+2)^-0.6, per-outlet
  sufficient statistics persisted in SQLite (`src/stapled/infer/online_em.py`).
- HTTP-Range streaming ingestion with resumable byte cursors — no full corpus download
  (`src/stapled/ingest/stream.py`); full ISOT corpus (~44k articles) processed this way.
- Claim extraction → event clustering → binary decision matrix D_ij per (claim, outlet).
- Planned model changes for the study (from external review):
  1. Dedup-aware E-step: route votes through `dedup_cluster_id` so syndicated copies count once.
  2. Anchor seeding: clamp posterior W_i for a small set of externally verified claims.
  3. Inversion sanity gate: flag runs where mean sensitivity < 0.5.
  4. (Stretch) Three-valued D_ij separating omission (absent) from contradiction.

## Experiments

| # | Experiment | Data | Metric | Expected result |
|---|---|---|---|---|
| E1 | Synthetic recovery | Seeded corpora, planted (p_j, q_j) | Spearman ρ vs planted reliability | ρ ≥ 0.8 (existing gate passes) — validates the EM machinery |
| E2 | Majority-capture characterization | Synthetic, sweep unreliable-source fraction f ∈ {0.1…0.9} and syndication multiplicity m | Inversion rate vs (f, m) | Phase transition: inversion when effective unreliable vote share > 0.5; syndication multiplicity shifts the boundary left — the headline figure |
| E3 | Real-data baseline (no fix) | ISOT (labels held out) | AUC separating True-corpus vs Fake-corpus sources by estimated reliability | AUC near or below 0.5 in inverted regime — reproduces the observed failure honestly |
| E4 | Anchoring fix | ISOT + k anchored claims, k ∈ {0, 10, 50, 100, 500} | AUC vs k; anchor budget curve | AUC > 0.9 with k ≈ 50–100 (<1% of claims) — "small labeled seed leverages large unlabeled corpus" |
| E5 | Dedup-aware voting | ISOT with injected wire-duplicate blocks | Inversion threshold shift | Dedup restores the f > 0.5 boundary; without it, inversion at much lower f |
| E6 | External validity | Multi-outlet crawl or NELA-GT-style corpus | Spearman vs MBFC factual-reporting; vs AllSides bias | Moderate positive correlation for reliability (ρ ≈ 0.4–0.6 plausible); near-zero for left/right bias axis — supports "measures reliability/omission, not ideology" |
| E7 | Omission audit (qualitative + quantitative) | Same | Per-outlet sensitivity on corroborated-claim subsets by topic | Interpretable case studies: outlets with low p_j on specific topic clusters |
| E8 | Streaming efficiency | ISOT full stream | Wall-clock, peak memory, bytes transferred vs batch EM | Constant memory, single pass, resume-after-interrupt — systems contribution |
| E9 | Temporal holdout (no labels) | Rolling window | Predict later corroboration of early claims | Calibrated W_i predicts corroboration above majority-vote baseline |

## Baselines

Majority vote; weighted majority (article counts); vanilla batch Dawid-Skene;
TruthFinder-style iterative credibility; supervised logistic regression on outlet features
(upper-bound reference, uses labels).

## Anticipated results / claims

1. Unmodified Text-STAPLE measures consensus, not truth — inversion is a provable
   identifiability property (likelihood invariant under joint relabel
   T→1−T, (p,q)→(1−q,1−p), π→1−π), and we exhibit it empirically on ISOT (E2, E3).
2. Two cheap fixes (sparse anchors + dedup voting) restore truth alignment at <1%
   supervision cost (E4, E5) — the practical contribution.
3. The calibrated per-outlet sensitivity supports an interpretable omission/selection-bias
   audit that ideology-focused classifiers do not provide (E6, E7).
4. The whole pipeline runs as a constant-memory single-pass stream (E8) — deployable as a
   rolling monitor, unlike batch truth-discovery systems.

## Honest scope limits (stated up front)

- Output is truth-calibrated consensus, never objective truth; contested interpretive
  claims are out of scope by construction.
- Framing/spin is not measured by the binary-claim channel; flagged as future work
  (continuous-emission two-channel extension).
- ISOT's fake corpus is a single-source artifact; E6 on a multi-outlet corpus is the
  external-validity check.

## Resources required

All data free (ISOT, MBFC/AllSides public ratings, NELA-GT, Google Fact Check API for
anchors). No paid annotation. Compute: laptop/CI-scale (online EM is O(claims) memory-light).
