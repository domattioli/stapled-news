# Abstract

**Many Biased Witnesses: Does Dependence-Aware Consensus Across News Outlets Recover Fact-Checked Truth?**

Every outlet's account of an event is a partial, slanted guess at what happened. The
intuition that "enough guesses average out to the truth" fails for news in two ways:
outlets copy each other, so their errors are not independent, and bias leans in shared
directions, so errors do not cancel. We test whether a model that corrects for both
failures recovers externally verified truth better than counting outlets.

We treat outlets as noisy raters of a hidden event, in the tradition of Dawid–Skene,
STAPLE, and truth discovery (including the Latent Truth Model's use of source silence as
negative evidence). Coverage is decomposed into atomic claims. For every event an outlet
covered, each claim is either carried or omitted; omission counts only when the outlet
covered the event. The model jointly estimates the consensus status of each claim and two
error rates per outlet: coverage of consensus claims (sensitivity) and propagation of
non-consensus claims (one minus specificity). Near-duplicate syndicated copies are
clustered so that one underlying account casts one vote. Estimation uses no labels and
runs as an online EM over a streaming news feed.

Consensus is not truth: unsupervised inference cannot tell a reliable majority from an
unreliable one. We therefore evaluate against open fact-check verdicts (ClaimReview
records and public fact-check datasets), held out from estimation. The primary question
is whether dependence-aware weighted consensus matches fact-check verdicts more often,
and with better calibration, than majority vote and than unclustered weighting. We also
test whether using fact-check verdicts as anchors during estimation improves held-out
accuracy. The study is pre-registered to stop if fewer than 50 claims match a fact-check
verdict.

Supporting results: on synthetic corpora with planted parameters, the streaming EM
recovers outlet parameters (Spearman ρ ≥ 0.8), and clustering syndicated copies corrects
the consensus distortion that wire republication otherwise causes. Outlet lean, taken
from open academic ratings, is used only as a covariate to check that the error rates do
not simply encode left–right position.

Contribution: the inference methods exist; the contribution is an empirical test, on
real multi-outlet coverage, of when cross-outlet consensus can stand in for truth, and of
how much dependence correction and anchoring matter. Code, the streaming pipeline, and
the synthetic benchmark are released.

---

*Keywords: truth discovery, latent-class models, Dawid–Skene, source dependence,
fact-checking, news coverage, computational social science*
