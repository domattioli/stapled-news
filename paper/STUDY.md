# Study Design: Measuring Cross-Outlet Consensus and Selective Omission with Streaming Latent-Class Models

## Working title

**"A Streaming Latent-Class Model of Cross-Outlet News Consensus and Selective Omission"**

## Framing

The model measures *consensus*: the latent variable is the consensus status of each atomic
claim across outlets, and per-outlet parameters quantify agreement with and deviation from
that consensus (coverage of consensus claims; propagation of non-consensus claims). This is
the honest, identifiable target of unsupervised Dawid-Skene/STAPLE inference. The
relationship between consensus and objective truth — including the conditions under which
they diverge (unreliable majorities, syndication-inflated vote shares) and the cost of
anchoring them together — is treated in the Discussion, not claimed in the title or results.

## Research questions

- **RQ1 (Validity):** Does the streaming STAPLE/Dawid-Skene adaptation recover planted
  consensus structure and outlet parameters on synthetic corpora, and produce stable,
  interpretable estimates on real multi-outlet news (ISOT, ~44k articles)?
- **RQ2 (Robustness):** How do consensus estimates respond to syndication (near-duplicate
  articles inflating effective vote share), and does deduplication-aware voting correct this?
- **RQ3 (Utility):** Do per-outlet consensus-agreement parameters correlate with independent
  third-party factual-reporting ratings, and does the coverage parameter (sensitivity p_j)
  support an interpretable selective-omission audit?

## Method (implemented in this repo)

- Online/stepwise EM (Cappé–Moulines), step γ_t = (t+2)^-0.6, per-outlet sufficient
  statistics persisted in SQLite (`src/stapled/infer/online_em.py`).
- HTTP-Range streaming ingestion with resumable byte cursors — constant memory, no full
  corpus download (`src/stapled/ingest/stream.py`).
- Claim extraction → event clustering → binary decision matrix D_ij per (claim, outlet).
- Model changes for the study:
  1. Dedup-aware E-step: votes routed through `dedup_cluster_id` so syndicated copies count once.
  2. Reporting language: parameters labeled consensus-agreement, not reliability/truth.

## Experiments (5)

| # | Experiment | Data | Metric | Expected result |
|---|---|---|---|---|
| E1 | Synthetic recovery | Seeded corpora, planted parameters | Spearman ρ vs planted values | ρ ≥ 0.8 (existing gate) — validates the estimator |
| E2 | Syndication sensitivity | Synthetic, sweep duplicate multiplicity m | Consensus-estimate shift vs m, with/without dedup voting | Without dedup, consensus tracks the syndicated bloc; dedup restores independence — main methods figure |
| E3 | Real-data application | ISOT (labels held out) | Outlet parameter distributions; separation of True- vs Fake-corpus sources (AUC), reported descriptively | Characterizes what consensus-agreement does and does not capture on real data, including the regime where consensus diverges from held-out labels |
| E4 | External correlation | Multi-outlet corpus (NELA-GT or crawl) | Spearman of consensus-agreement vs MBFC factual-reporting; vs AllSides left–right | Positive correlation with factual-reporting, near-zero with ideology — parameter measures consensus alignment, not political stance |
| E5 | Omission audit | Same | Per-outlet sensitivity on corroborated-claim subsets by topic; case studies | Interpretable patterns of selective omission per outlet/topic over time |

Streaming efficiency (memory, single pass, resumability) reported as implementation
properties in the system description, not as a separate experiment.

## Baselines

Majority vote; weighted majority (article counts); vanilla batch Dawid-Skene.

## Discussion section (where truth enters)

- Consensus ≠ objective truth: the Dawid-Skene likelihood is invariant under joint
  relabeling (T→1−T, (p,q)→(1−q,1−p), π→1−π), so the unsupervised estimand is consensus by
  construction. E3 quantifies the divergence on ISOT.
- Anchoring path: sparse externally verified claims (free fact-checking APIs) can tie
  consensus estimates to verifiable facts at low labeling cost — sketched as future work
  with the anchor mechanism already implemented.
- Scope: binary claim channel measures coverage/omission, not framing or spin
  (continuous-emission extension noted as future work).

## Venue

Primary: **EPJ Data Science** (open-access journal; computational social science methods;
rolling submission, no length pressure). Backup: *Computational Communication Research*
(diamond open access, no APC).

## Resources

All data free (ISOT, MBFC/AllSides public ratings, NELA-GT). No paid annotation.
Compute: laptop-scale.
