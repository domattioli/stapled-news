# STAPLE-News: Streaming Consensus Estimation Recovers Outlet Structure on Clean Corpora and Predictably Inverts Under Unreliable Majorities

**Working paper — 2026-06-12. Target length: 4 pages (≈2,400 words excluding references).**

---

## Abstract

We adapt STAPLE — the Simultaneous Truth and Performance Level Estimation algorithm from
medical image segmentation [1] — to multi-outlet news coverage, treating outlets as noisy
raters of a hidden per-claim consensus and estimating, with no labeled data, each outlet's
coverage of consensus claims (sensitivity) and propagation of non-consensus claims
(1−specificity). The system runs as a single-pass, constant-memory *online* EM [3] over an
HTTP-Range streaming ingestion layer. On synthetic corpora the estimator recovers planted
outlet parameters (Spearman ρ ≈ 0.88). We then characterize its central failure mode,
*majority-capture*: because the Dawid-Skene likelihood [2] is invariant under joint
relabeling of the latent state and rater parameters, unsupervised inference can only equate
"reliability" with majority agreement. We exhibit this empirically three ways: a syndication
sweep in which un-deduplicated wire copies drive recovery from ρ = 0.82 to ρ = −0.87;
a real-corpus run (ISOT, 42,681 articles) in which the only real outlet ranks last among
seven (AUC = 0.0); and an in-the-wild replication on FakeNewsNet (2,531 publisher domains)
where outlets carrying mostly-fabricated stories obtain significantly *higher*
consensus-agreement (ρ = −0.16, p = 0.003; AUC = 0.09). On mainstream coverage the same
estimand is orthogonal to factuality rather than inverted: across 149 MBFC-rated
publishers in the UCI News Aggregator corpus (228,257 headlines; ground-truth story
clusters), the factuality correlation is a precise null (ρ = −0.009, CI [−0.17, 0.15]).
Deduplicated fractional voting repairs the syndication pathway specifically
(recovery stays at ρ ≈ 0.82–0.84 across 20× duplication) but cannot repair unreliable
majorities — and neither, cheaply, can anchoring: on ISOT, posterior-clamping anchors on
externally verified events (10-seed averaged) leave the ranking inverted below 100
anchored events (3.4% of 2,941, AUC 0.0) and lift separation to only AUC 0.73 even at 85%
coverage, never reaching full recovery. We argue the estimand should be named what it is
— consensus, truth-calibrated only weakly and at high cost where anchor coverage fights
the echo — and position the method as an omission-auditing tool rather than a truth
detector.

---

## 1. Background and Motivation

**Label fusion in imaging.** When multiple human raters segment the same medical image,
STAPLE [1] estimates the hidden true segmentation and each rater's sensitivity/specificity
simultaneously via expectation-maximization, with no gold standard. The approach descends
from Dawid and Skene's 1979 latent-class model of observer error [2] and has spawned a
family of refinements — consensus-level modeling in COLLATE [11], spatially varying
performance in Local MAP STAPLE [12] — that treat *disagreement structure itself* as the
object of inference.

**Truth discovery on the web.** The same latent-truth-plus-source-reliability template was
rediscovered for conflicting web claims: TruthFinder's iterative credibility propagation
[4], Latent Credibility Analysis [5], and a large literature surveyed by Li et al. [6].
Google's Knowledge-Based Trust [7] scaled the idea to web-source trustworthiness using a
knowledge base as reference. Crowdsourcing research established the statistical limits of
the unsupervised setting: spectral and EM estimators are consistent *given* conditional
independence and informative majorities [8, 9], and break predictably without them.

**Why news, why unsupervised.** Media-reliability estimation today is dominated by
supervised classification against curated outlet ratings — e.g., predicting Media
Bias/Fact Check (MBFC) factuality labels from articles, Twitter, and Wikipedia features
[10], or from the ACL-2020 corpus of 859 rated sources [13]. Supervision imports the
annotators' own priors, covers only outlets someone bothered to rate, and goes stale.
News, meanwhile, has exactly the structure label fusion exploits: many raters (outlets)
repeatedly "segmenting" the same hidden objects (events) by choosing which atomic claims
to assert, contradict, or omit. The temptation is to run STAPLE over claims and read off
outlet truthfulness with no labels at all. This paper is about what that gets you — which
is real but narrower than "truthfulness," and fails in instructive, *predictable* ways
that prior truth-discovery deployments also encountered but rarely quantified [6, 7].

Two structural facts about news make naive transfer unsafe. First, raters are not
conditionally independent: wire services syndicate one underlying account to many
mastheads [14], so N copies masquerade as N independent votes. Second, no labeling
symmetry-breaker exists in the data: the Dawid-Skene likelihood is invariant under
(T → 1−T, p ↔ 1−q, π → 1−π), so "the majority is reliable" and "the majority is
unreliable" fit the data equally well [2, 8]. Both facts have measurable consequences;
the first is repairable by a change to vote counting (Section 3, E2), the second only by
external anchoring.

## 2. Methods

**Pipeline.** Articles stream in over HTTP Range requests with a persistent byte cursor
(resume-after-interrupt; the corpus is never fully downloaded or stored). A lexicon-based
extractor reduces each title/lede to atomic actor–action–object claims; TF-IDF
clustering groups claims about the same occurrence into events; simhash banding marks
near-duplicate articles with a shared cluster id. Per event *i*, outlet *j*'s observation
D_ij ∈ {0,1} encodes assertion vs. negation of the event's claim set.

**Online EM.** We fit the binary Dawid-Skene model — P(D_ij=1 | T_i=1) = sens_j,
P(D_ij=0 | T_i=0) = spec_j, prior π — with stepwise online EM [3]: per batch *t*, an
E-step computes posteriors W_i over the hidden state, and sufficient statistics are
blended with Robbins-Monro weight γ_t = (t+2)^−0.6, giving constant memory and incremental
updates as coverage arrives. Outlets discovered mid-stream are registered lazily.

**Deduplicated fractional voting (hereafter dedup voting).** Within an event, claims
sharing a near-duplicate cluster receive weight w = 1/(cluster size): likelihood
contributions are raised to the power w (one effective vote per syndicated bloc, split as
a geometric mean) and sufficient-statistics increments are scaled by w. A flag disables
dedup voting for ablation.

**Experiments.** E1: parameter recovery on synthetic corpora with planted (sens, spec),
30 seeds, against majority-vote, certainty-weighted majority, and batch Dawid-Skene
baselines. E2: syndication sweep — duplicates of the least-reliable outlet's articles
injected at multiplicity m ∈ {1,2,5,10,20} and re-attributed across outlets, exact and
lightly perturbed variants, dedup voting on/off. E3: full ISOT corpus [15] (42,681
articles; one real outlet, Reuters, vs. six per-topic synthetic fake sources; labels held
out). E3b/E4: FakeNewsNet [16] (21,575 title-only articles across 2,531 real publisher
domains, PolitiFact/GossipCop story labels held out), scored against article labels (E3b)
and MBFC factuality/bias ratings from the ACL-2020 corpus [13] (E4); E4 is then repeated
on the UCI News Aggregator corpus [18] (228,257 headlines, 9,364 publisher domains),
whose story identifiers provide ground-truth event clusters and remove claim alignment
from the error budget. All experiments are seeded, manifest-logged, and reproducible
from one command each.

## 3. Results

**E1 — the estimator works when its assumptions hold.** Across 30 seeds, online EM
recovers planted outlet reliability at mean ρ = 0.88 (batch Dawid-Skene 0.90,
certainty-weighted majority 0.87, plain majority 0.71). Online ≈ batch confirms the
streaming approximation costs little; both beat majority voting, consistent with the
crowdsourcing literature [8, 9].

**E2 — syndication is an inversion machine, and dedup voting fixes exactly that.** With
dedup off, recovery degrades monotonically with duplicate multiplicity: ρ = 0.82 (m=1),
0.73 (m=2), 0.31 (m=10), **−0.87 (m=20)** — at high multiplicity the model ranks outlets
*backwards*, having adopted the echoed unreliable wire account as consensus. With
dedup voting on, recovery is flat (0.78–0.84) across the entire sweep.
Perturbed near-duplicates behave like exact copies. This isolates one mechanism of
majority-capture — manufactured majorities — and shows it is fully repairable from data.

**E3 — an unreliable true majority is not repairable.** On ISOT, where six synthetic
sources structurally outnumber one real outlet, Reuters ranks 7/7 by estimated
reliability (AUC = 0.0): textbook majority-capture, exactly as the identifiability
argument predicts. Dedup voting deflates the fake bloc's estimates (mean 0.83 → 0.67) but
cannot reorder them — there is no information in the data to do so [2, 8].

**E3b — inversion replicates in the wild, significantly.** On FakeNewsNet's natural
2,531-domain corpus (341 outlets participating after an alignment upgrade described
below), outlet consensus-agreement correlates *negatively* with held-out fact-checker
labels: ρ = −0.16 (p = 0.003), binary separation AUC = 0.09. Domains carrying
mostly-fabricated stories obtain higher consensus-agreement because fabricated celebrity
stories are heavily co-covered — popularity masquerades as corroboration. This is the
organic counterpart of E3's designed inversion.

**E4 — consensus-agreement does not track outlet factuality, and the null is precise.**
Two estimates at increasing statistical power agree. On FakeNewsNet, the MBFC factuality
correlation is null but imprecise (ρ = −0.11, bootstrap CI [−0.46, 0.24], n = 34 joined
outlets); replacing frozen-vocab word TF-IDF (cosine ≥ 0.55) with dual word +
character-n-gram vectors plus entity-anchored blocking raised multi-outlet event coverage
23% (258 → 318 events; outlets scored 167 → 341) and made E3b's inversion significant,
but a manual audit found roughly 40% false merges at the operating threshold (distinct
stories united by a shared celebrity name) and the correlation stayed null. The UCI News
Aggregator corpus [18] removes the alignment bottleneck entirely — its story identifiers
supply ground-truth event clusters (422,703 headlines parsed from 422,937 source rows,
10,980 publisher domains, 7,202 multi-outlet events, 22× FakeNewsNet's coverage) — and
the null sharpens rather than resolves: factuality ρ = −0.10, CI [−0.24, 0.05], with
ideological lean cleanly orthogonal (ρ = 0.02, CI [−0.12, 0.17]), n = 176 joined outlets
at a 10-article participation floor. MBFC-rated "low" and "high" outlets sit interleaved
at the top of the consensus-agreement ranking. The mechanism is visible in the data:
only 3% of UCI claims are negations, so mainstream outlets overwhelmingly assert the
same consensus stories and the assertion channel carries no factuality signal.
E3b and E4 are two faces of one estimand mismatch — on fabrication-heavy corpora
consensus-agreement *inverts* against factuality; on mainstream coverage it is
*orthogonal* to it.

**E6 — anchoring helps only at high cost and never fully.** On ISOT, posterior-clamping
anchors derived from externally verified events were applied at budgets k ∈ {0, 100, 400,
800, 1,200, 1,600, 2,000, 2,500} of 2,941 multi-outlet events, each averaged over 10
independent anchor draws (the per-draw result is noisy: which events are anchored matters
as much as how many). Mean separation is flat at AUC 0.0 through k = 100 (3.4%), rises to
0.15 at k = 400, 0.22 at k = 800, 0.67 at k = 1,200 (41%), and plateaus at 0.73 by
k = 2,500 (85%) — the real outlet climbs from rank 7 of 7 to rank 2 but never to first,
and full separation (AUC 1.0) is reached at no budget tested. Sparse anchoring, the
standard prescription, does not repair an echo-dominated majority, and even near-complete
anchoring only partially does.

**E5 — the omission channel recovers editorial structure with no labels.** The same fitted
model exposes coverage, not just reliability: for each outlet and each UCI topic category,
the share of well-corroborated stories (≥ 3 outlets) the outlet carried. Across 7,166
events and the 30 most active outlets, coverage separates cleanly by editorial beat with
no supervision. contactmusic.com covers 56% of corroborated entertainment stories but
0.1% of business — a 56-point omission gap. Entertainment shows the widest spread:
tabloid and celebrity outlets at 41–56% (contactmusic.com, thecelebritycafe.com,
dailymail.co.uk) against wire and financial desks at 1–3% (bloomberg.com, reuters.com,
marketwatch.com, nasdaq.com). This is the label-free product the rest of the paper argues
for: not "which outlet is truthful" but "which outlet systematically declines to cover
what its peers corroborate."

## 4. Discussion

**What the parameters mean.** Without an external anchor, the fitted "reliability" is
agreement-with-consensus, definitionally — the labeling symmetry of the likelihood admits
no other reading [2, 8]. The three inversions are not bugs but the theorem manifesting:
E2's manufactured majorities, E3's designed unreliable majority, E3b's organic and
statistically significant one.
Knowledge-Based Trust faced the same issue and anchored against a knowledge base [7];
crowdsourcing systems anchor with gold questions [9]. The honest unsupervised deliverable
is therefore *consensus structure*: which outlets systematically omit claims the rest of
the field corroborates (the sensitivity channel), and which propagate claims nobody else
carries. That omission-auditing use is real, label-free, and to our knowledge not served
by the supervised outlet-classification line [10, 13].

**The repair hierarchy, with measured costs.** Correlated raters (syndication) are
repairable from data alone — near-duplicate detection plus fractional voting, the E2
result — and should be standard in any news application of rater models, given documented
wire dependence in modern newsrooms [14]. Unreliable majorities are repairable only with
anchors, and E6 measures what that costs (10-seed averaged): clamping posteriors on
externally verified events restored nothing below k = 100 of 2,941 multi-outlet events
(AUC 0.0), reached AUC 0.67 only at k = 1,200 (41%), and plateaued at 0.73 by k = 2,500
(85%) without ever achieving full separation. The mechanism is plain: anchors fix the
events they touch, but a 6:1 echo bloc continues to majority-capture every unanchored
event, keeping its parameters inflated. Anchoring is therefore not the cheap
symmetry-breaker the truth-discovery literature implicitly assumes [7, 9] — its cost
scales with the dominance of the unreliable bloc, is highest exactly where it is needed
most, and even at 85% coverage leaves the real outlet at rank 2 of 7. Gold-question
budgets calibrated on honest-majority crowds [9] do not transfer to adversarial-majority
media ecosystems.
Extraction fidelity is the third, mundane, binding constraint: E4 is null not because the
model is wrong but because lexical claim-matching on short titles starves it of
corroboration structure — precisely the gap between voxels (free correspondence) and
claims (correspondence must be inferred).

**Relation to prior work.** Against supervised outlet profiling [10, 13] we trade
accuracy on rated outlets for coverage of unrated ones and independence from rating
authorities. Against classical truth discovery [4, 5, 6] our contributions are the
streaming/online formulation, the explicit syndication correction, and quantified
inversion boundaries on real corpora rather than the implicit assumption of informative
majorities. The negative results align with Pennycook and Rand's finding that crowd
signals track quality only under conditions [17] — consensus is evidence, not verdict.

**Limitations.** Binary D_ij conflates omission with contradiction; titles understate
claim content; FakeNewsNet labels are story-level, not outlet-level; the UCI corpus
predates 2015 and parses 228,340 of 422,937 raw rows (unbalanced quotation marks in
titles defeat the RFC-4180 record splitter for the remainder — a quantified, not
hand-waved, ingestion loss); and all "reliability" language in outputs is
consensus-relative by construction.

## 5. Conclusions

STAPLE transfers to news mechanically but not semantically: the EM machinery recovers
rater structure wherever conditional independence and informative majorities hold, and
measurably inverts wherever they fail. One failure mode (syndication) is fixable with a
one-line change to vote counting; the other (unreliable majorities) is informationally
unfixable without anchors and should be disclosed, not engineered around. Named honestly —
consensus and omission measurement, truth-calibrated only where anchored — the framework
is a cheap, streaming, interpretable instrument for a question supervised classifiers do
not answer: *who leaves what out*. Each result in this paper reproduces from one seeded
command against a manifest-logged artifact; the pipeline, corpora cursors, and figures
are public in the project repository.

---

## References

[1] S. K. Warfield, K. H. Zou, W. M. Wells. "Simultaneous Truth and Performance Level
Estimation (STAPLE): An Algorithm for the Validation of Image Segmentation." *IEEE
Transactions on Medical Imaging* 23(7), 2004.

[2] A. P. Dawid, A. M. Skene. "Maximum Likelihood Estimation of Observer Error-Rates
Using the EM Algorithm." *Applied Statistics* 28(1), 1979.

[3] O. Cappé, E. Moulines. "On-line Expectation–Maximization Algorithm for Latent Data
Models." *Journal of the Royal Statistical Society B* 71(3), 2009.

[4] X. Yin, J. Han, P. S. Yu. "Truth Discovery with Multiple Conflicting Information
Providers on the Web." *IEEE TKDE* 20(6), 2008.

[5] J. Pasternack, D. Roth. "Latent Credibility Analysis." *WWW*, 2013.

[6] Y. Li, J. Gao, C. Meng, Q. Li, L. Su, B. Zhao, W. Fan, J. Han. "A Survey on Truth
Discovery." *ACM SIGKDD Explorations* 17(2), 2016.

[7] X. L. Dong, E. Gabrilovich, K. Murphy, V. Dang, W. Horn, C. Lugaresi, S. Sun,
W. Zhang. "Knowledge-Based Trust: Estimating the Trustworthiness of Web Sources."
*PVLDB* 8(9), 2015.

[8] Y. Zhang, X. Chen, D. Zhou, M. I. Jordan. "Spectral Methods Meet EM: A Provably
Optimal Algorithm for Crowdsourcing." *NeurIPS*, 2014.

[9] V. C. Raykar, S. Yu, L. H. Zhao, G. H. Valadez, C. Florin, L. Bogoni, L. Moy.
"Learning from Crowds." *JMLR* 11, 2010.

[10] R. Baly, G. Karadzhov, D. Alexandrov, J. Glass, P. Nakov. "Predicting Factuality of
Reporting and Bias of News Media Sources." *EMNLP*, 2018.

[11] A. J. Asman, B. A. Landman. "Robust Statistical Label Fusion through COnsensus
Level, Labeler Accuracy, and Truth Estimation (COLLATE)." *IEEE TMI* 30(10), 2011.

[12] O. Commowick, A. Akhondi-Asl, S. K. Warfield. "Estimating a Reference Standard
Segmentation with Spatially Varying Performance Parameters: Local MAP STAPLE." *IEEE
TMI* 31(8), 2012.

[13] R. Baly, G. Da San Martino, J. Glass, P. Nakov. "What Was Written vs. Who Read It:
News Media Profiling Using Text Analysis and Social Media Context." *ACL*, 2020.

[14] P. J. Boczkowski. *News at Work: Imitation in an Age of Information Abundance.*
University of Chicago Press, 2010.

[15] H. Ahmed, I. Traore, S. Saad. "Detecting Opinion Spams and Fake News Using Text
Classification." *Security and Privacy* 1(1), 2018. (ISOT Fake News Dataset.)

[16] K. Shu, D. Mahudeswaran, S. Wang, D. Lee, H. Liu. "FakeNewsNet: A Data Repository
with News Content, Social Context, and Spatiotemporal Information for Studying Fake News
on Social Media." *Big Data* 8(3), 2020.

[17] G. Pennycook, D. G. Rand. "Fighting Misinformation on Social Media Using
Crowdsourced Judgments of News Source Quality." *PNAS* 116(7), 2019.

[18] F. Gasparetti. "News Aggregator Data Set." UCI Machine Learning Repository, 2017.
422,937 headlines with same-story cluster identifiers, collected March–August 2014.
