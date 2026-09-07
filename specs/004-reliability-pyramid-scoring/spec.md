# Spec 004: Reliability-weighted pyramid scoring — feasibility test

**Status:** spike result, NOT a feature spec for implementation. Re-scoped after an adversarial review (Luna, GPT-5.6) found the original single-event proof-of-concept invalid. See `.claude/handoffs/2026-09-07-stapled-pyramid-headline.md` in `agents_Inc` for full prior-session narrative.

## Motivation

`stapled-news`'s Dawid-Skene EM (`src/stapled/infer/em.py`) estimates per-outlet reliability and a binary per-event true state, but produces no synthesized text, no per-claim evidence, and no ranking of candidate headlines. The Pyramid method (Nenkova & Passonneau, 2004) extracts atomic claims and weights each by source count. Both weight by corroboration; neither alone distinguishes corroboration from correctness. The question: does replacing naive source-count weighting with EM-estimated reliability weighting produce a **validated** improvement, not just a **different** score?

## Why the original PoC didn't answer this

A prior session hand-built one micro-PoC: 15 headlines about one event (Maine's 2026 Senate nomination), 6 keyword-matched "SCUs," fed as 6 fake independent binary "events" into `_run_em_single`. Adversarial review found 5 issues, all structural, not implementation bugs:

1. **No anchor** — no gold labels, so EM's binary state can arbitrarily flip which label means "true" (label-switching).
2. **Absence-as-denial** — `obs = 1 if fn(headline) else 0` coded "doesn't mention this claim" as "asserts it's false." Dawid-Skene's binary model reads 0 as an active false claim, not silence.
3. **Circularity** — outlet reliability was estimated from the very SCU-assertion pattern it was then used to reweight.
4. **No ground truth** — two schemes producing different scores (0.65 vs 0.70) proves the scores differ, not that either is more accurate.
5. **SCU independence violated** — the 6 "SCUs" were causally entangled facts about one event, not independent binary items.

## Test design (this spec's actual contribution)

Re-ran the comparison against the design flaws directly, using the real pipeline and the full corpus instead of a hand-built PoC. Script: `scripts/ab_test_reliability_pyramid.py`.

| Finding | How this test addresses it |
|---|---|
| 1. No anchor | Outlets with an independent MBFC `fact: high` rating (`outlet_external_label`, loaded via `load-external-labels`, sourced outside this corpus) form a held-out anchor panel. Anchor outlets are excluded from reliability fitting entirely — their assertions are read only as the validation target. |
| 2. Absence-as-denial | Uses the real `claim`/`article`/`event` tables via the same query shape as `em._load_claims_by_event(is_real=True)`: a row exists only if that outlet actually made that claim. No keyword-coded "0 = denies" anywhere. |
| 3. Circularity | Outlet reliability is fit via `_run_em_single` on a 70% **train** split of real events (anchor outlets excluded from the fit). Scoring happens only on the disjoint 30% **test** split, using non-anchor outlets' claims — the weights are never fit on the data they're then used to score. |
| 4. No ground truth | Each scheme's test-side score (built only from non-anchor outlets) is compared against the anchor panel's own majority assertion for that same event — an externally sourced signal neither scheme's weights were fit on. This is a proxy-ground-truth test (see Limitations), not a truth oracle, but it is an independent target, which finding 4 says a valid test needs. |
| 5. SCU independence | Units of analysis are the pipeline's real aligned events (`align-cmd`: TF-IDF + entity clustering over the full 37k-article corpus), not hand-picked sub-claims of one story. |

Unit of analysis note: the real extraction pipeline (`src/stapled/extract/claims.py`) currently produces one `occurred`/`not-occurred` claim per article per aligned event, not multiple decomposed sub-claims per article. So "SCU" in this test maps to **one real-world event**, not a further decomposition of a single story into atomic facts the way classic Pyramid scoring does within one summary. That's a narrower unit than the original PoC's per-story SCU pyramid — see Limitations.

## Method

1. `load-us-headlines` (37,358 articles, 323 outlets) → `extract` (37,358 claims) → `align-cmd` (4,276 real events).
2. `load-external-labels` → 859 MBFC ratings; join on outlet domain gives 32 outlets in-corpus with `fact: high`.
3. Filter to events with ≥3 distinct outlets and ≥1 anchor outlet (395 of 4,276).
4. Split events 70/30 (seed 42) into train/test.
5. Fit EM (`_run_em_single`, 5 restarts, best log-likelihood, non-degenerate) on train events, anchor outlets excluded → per-outlet reliability = mean(sensitivity, specificity).
6. Per test event: `naive_score` = mean observation across non-anchor outlets; `reliability_score` = reliability-weighted mean across the same outlets; `anchor_label` = majority observation among anchor outlets (excluded from steps 4-5 entirely).
7. Compare both scores to `anchor_label` via MAE and thresholded accuracy.

## Results

269 train events (258 non-anchor outlets), 116 test events scored against the anchor panel:

| Metric | Naive count | Reliability-weighted |
|---|---|---|
| MAE vs. anchor | 0.0671 | 0.0644 |
| Accuracy vs. anchor | 0.9569 | 0.9569 |

Full output: `results_us/ab_test_reliability_pyramid.json`.

**Verdict: no validated improvement.** Reliability-weighting produces a marginally lower MAE but identical thresholded accuracy on this corpus and this anchor. The two schemes are not meaningfully different once measured against an independent, non-circular target — this is the same direction of skepticism the adversarial review raised about the original PoC, now backed by a real, cross-validated, anchored test rather than a single-event divergence.

Read together with the 4,276-vs-395 filter drop: of 4,276 real events, only 395 (9.2%) had both enough outlet coverage and any anchor-outlet coverage at all — anchor coverage is the binding constraint, not corpus size. A different or larger anchor set could change this result; this test does not rule that out.

## Limitations

- **Proxy ground truth, not truth.** "The anchor panel says X" is an independently-sourced signal, not a metaphysical truth oracle — MBFC's `fact: high` label is itself a human editorial judgment about outlets, not events. Treat the reported accuracy/MAE numbers as "agreement with a trusted-outlet panel," not "correctness."
- **SCU granularity is event-level, not sub-event.** This test validates reliability-weighting at the same granularity `stapled-news`'s EM already operates at (one binary claim per event). It does not test the original ambition — weighting sub-claims *within* one story to synthesize a single reliability-aware headline — because the extraction pipeline doesn't yet decompose one event into multiple atomic sub-claims. That remains unbuilt and untested.
- **Anchor panel is small and US/English-language MBFC-rated only** (32 outlets, 9.2% event coverage) — results may not generalize to outlets or event types outside that overlap.
- **EM non-convergence / degeneracy**: `_run_em_single` restarts (5x) and discards degenerate or non-converged fits; if none of 5 restarts converge non-degenerately, the script raises rather than silently reporting a bad fit (`SystemExit`, not swallowed).
- Reliability estimate here is a single point estimate (mean of sens/spec) per outlet; no confidence interval reported, so the near-tie between schemes is a qualitative read, not a hypothesis-tested difference.

## Recommendation

Do not implement reliability-weighted pyramid scoring as a shipped feature on the strength of this result — it does not clear its own bar. If revisited: (a) grow the anchor set (more MBFC-rated outlets, or a second independent rating source) to raise the 9.2% coverage ceiling and get a real confidence interval on the MAE gap, and (b) build genuine within-event sub-claim (SCU) decomposition in `extract/claims.py` before attempting the original per-story pyramid comparison — the event-level test here is a necessary precursor, not a substitute for that.

## Provenance

`stapled-news`: https://github.com/domattioli/stapled-news. Pyramid method: Nenkova & Passonneau (2004), HLT-NAACL. MBFC labels: `mbfc_acl2020` source in `src/stapled/ingest/fakenewsnet.py`, already used for this purpose in `src/stapled/experiments/e4_external.py`. Original PoC and adversarial review: `.claude/handoffs/2026-09-07-stapled-pyramid-headline.md` (`agents_Inc` repo).
