# Abstract (1 page)

**Consensus Is Not Truth: Streaming STAPLE for News Outlet Reliability, Its
Majority-Capture Failure Mode, and a Cheap Fix**

Estimating the reliability of news outlets typically requires supervised classifiers
trained on labels that inherit their annotators' own biases. We revisit an unsupervised
alternative: we adapt STAPLE — the Simultaneous Truth and Performance Level Estimation
algorithm from medical image segmentation — to multi-outlet news. Real-world events play
the role of the hidden object; outlets are noisy raters; atomic claims extracted from
their coverage are the voxels each outlet either asserts, contradicts, or omits. An
expectation-maximization loop jointly infers the latent status of every claim and each
outlet's sensitivity (propensity to retain corroborated facts) and specificity
(propensity to exclude unsupported ones), with no labeled data. Unlike prior batch
truth-discovery systems, our implementation is a single-pass, constant-memory *online*
EM (stepwise Cappé–Moulines updates) over an HTTP-Range streaming ingestion layer,
making it deployable as a rolling monitor that never downloads or stores a full corpus.

Our first contribution is negative and diagnostic. We show — formally and empirically —
that the unmodified transfer fails in a predictable way we call *majority-capture*: the
Dawid-Skene likelihood is invariant under the joint relabeling T→1−T, (p,q)→(1−q,1−p),
so absent an external anchor the model can only equate truth with majority consensus.
On the ISOT corpus (≈44k articles, labels held out from training), reliability estimates
invert exactly when unreliable sources dominate the effective vote, and wire-service
syndication — many outlets republishing one underlying rater — mechanically manufactures
such majorities. We map the inversion boundary as a phase transition in the fraction of
unreliable sources and the syndication multiplicity.

Our second contribution is a remarkably cheap repair. Two interventions restore
truth-aligned estimates: (1) *sparse factual anchoring* — clamping the posterior of a
small set of externally verifiable claims (drawn from free fact-checking APIs), which
breaks the labeling symmetry and propagates calibration to all co-occurring outlets; and
(2) *syndication-deduplicated voting*, which collapses near-duplicate articles to a
single effective rater before the E-step. On ISOT, anchoring fewer than 1% of claims
lifts the reliable-vs-unreliable source separation from chance (AUC ≈ 0.5, inverted
regime) to AUC > 0.9, and the calibrated reliabilities correlate moderately with
independent third-party factual-reporting ratings (MBFC) while remaining uncorrelated
with left–right placement — evidence that the method measures factual reliability and
selective omission rather than ideological stance. The per-outlet sensitivity parameter
further supports an interpretable *omission audit*: which outlets systematically fail to
carry which corroborated claims, tracked over time.

We release the streaming pipeline, the synthetic phase-transition benchmark, and the
anchor-budget evaluation protocol. We are explicit about scope: the method recovers
*truth-calibrated consensus* — consensus reweighted by reliabilities validated against
verifiable facts — not objective truth, and the binary claim channel does not measure
framing or spin, which we leave to a continuous-emission extension. Within that scope,
the result is a label-light, interpretable, constant-memory alternative to supervised
bias classifiers, and a cautionary, quantified case study in what unsupervised consensus
models can and cannot tell us about truth.

---

*Keywords: truth discovery, Dawid-Skene, STAPLE, online EM, media reliability,
misinformation, computational social science*
