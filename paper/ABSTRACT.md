# Abstract

**A Streaming Latent-Class Model of Cross-Outlet News Consensus and Selective Omission**

When many outlets cover the same event, their accounts overlap imperfectly: claims are
asserted, contradicted, or silently omitted. We present a method for quantifying this
structure without labeled data, adapting the STAPLE algorithm from medical image
segmentation — where an expectation-maximization loop jointly estimates a hidden
segmentation and each rater's performance — to multi-outlet news. Events take the role of
the hidden object, outlets act as raters, and atomic claims extracted from coverage are
the units each outlet includes or omits. The model jointly infers the consensus status of
every claim and two interpretable parameters per outlet: coverage of consensus claims
(sensitivity) and propagation of non-consensus claims (one minus specificity). We
deliberately frame the estimand as *consensus*: this is what unsupervised latent-class
inference identifies, and we examine its relationship to factual accuracy in the
discussion rather than claiming it in the results.

Methodologically, the system is an *online* EM (stepwise Cappé–Moulines updates) over an
HTTP-Range streaming ingestion layer: a single constant-memory pass with resumable byte
cursors, requiring no full corpus download and suitable for continuous monitoring of a
rolling news stream. Per-outlet sufficient statistics persist across batches, so estimates
update incrementally as new coverage arrives.

We validate the estimator in three steps. First, on synthetic corpora with planted
parameters, the streaming EM recovers outlet parameters reliably (Spearman ρ ≥ 0.8).
Second, we characterize a key robustness concern: wire-service syndication, where many
outlets republish a single underlying account, inflates that account's effective vote
share and pulls the consensus toward it. Routing votes through near-duplicate clusters so
syndicated copies count once measurably corrects this distortion. Third, applying the
model to the ISOT corpus (~44k articles, labels held out) and to a multi-outlet corpus, we
find that consensus-agreement parameters correlate positively with independent third-party
factual-reporting ratings while remaining uncorrelated with left–right placement —
indicating the model captures agreement with the cross-outlet factual record rather than
ideological stance. The coverage parameter supports a per-outlet, per-topic *omission
audit*: which outlets systematically fail to carry claims that the rest of the field
corroborates, tracked over time.

We discuss the limits of consensus as an estimand — including the identifiability argument
for why unsupervised inference cannot distinguish a reliable majority from an unreliable
one, the conditions under which consensus and accuracy diverge, and a low-cost anchoring
mechanism (already implemented) for tying estimates to externally verified claims. Code,
the streaming pipeline, and the synthetic benchmark are released.

---

*Keywords: latent-class models, Dawid-Skene, online EM, news coverage, media consensus,
selective omission, computational social science*
