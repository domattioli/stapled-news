# Session Handoff — STAPLE-News US Consensus Distance

**Date:** 2026-06-13 | **Branch:** development (auto-deploys to main via PR → Pages)
**Live:** https://domattioli.github.io/stapled-news/ (single tab: US Outlet Drift)

## What this is
STAPLE (Simultaneous Truth and Performance Level Estimation, Warfield et al. 2004) applied
to US political headlines: group headlines by story, build a coverage-weighted consensus
headline, measure each outlet's wording "drift" from it. One page, FiveThirtyEight/dom-write
voice, driven by `docs/data/consensus_us.json`.

## Current state (as of this handoff)
- **Corpus:** `corpus/us/headlines.csv.gz`, ~2,900 headlines, 684 domains, accreting hourly
  via `.github/workflows/fetch-us-news.yml` (GDELT throttles from runner IPs; RSS + Google
  News publisher-tagged feeds are the working sources; runs in `mode=rss` on cron).
- **Analysis set:** 246 articles across 23 stories with ≥5 outlets, 48 outlets ranked.
- **Key results:** drift ranking led by regional wire-runners (ocregister/sun-sentinel
  ~0.05), Axios farthest (~0.71); distance equal across lean camps but direction sits left
  of midpoint (consensus_lean position 0.28, CI 0.19–0.37) consistent with a 72%-left panel;
  **25.2% of analyzed headlines are verbatim wire copy** (collapsed in the centroid);
  **44.7% of articles are from 27 AllSides-unrated regional outlets** that drift 0.29 vs
  0.47 for rated nationals.
- **Validation:** V1 planted gate passes; V2 split-half ρ below 0.6 — corpus too small.

## How to refresh the numbers (4 commands)
```
python -m stapled.cli load-us-headlines --db us.db --min-outlet-articles 8
python -m stapled.cli realign-embed --db us.db --threshold 0.5
python -m stapled.experiments e7 ...   # or run e7_consensus.run(db_path=us.db) into results_us/
cp results_us/consensus.json docs/data/consensus_us.json
```
Then commit + PR → main. Always re-verify the page with the strict DOM stub (below) before
shipping — two blank-render regressions traced to a missing element id swallowed by a
page-wide catch.

## Strict render check (mandatory before any consensus.html ship)
node: extract inline scripts; getElementById returns null for ids NOT in the HTML; fetch
returns the real bundle; execute; assert zero uncaught errors, zero section console.errors,
and the expected Plotly.newPlot ids fire. This is the regression guard.

## Files
- `src/stapled/analyze/consensus_distance.py` — distance, lean axis, 5-point spectrum
  (PANEL_LEAN5), syndication-weighted centroid, panel_composition/spectrum, regional_impact,
  token_impacts.
- `src/stapled/experiments/e7_consensus.py` — runs EM + builds the bundle; FAMOUS_OUTLETS +
  `_curate_members` (8-10 lean-mixed members per story for the diff explorer).
- `docs/consensus.html` — the page; `docs/index.html` redirects to it.
- `docs/FUTURE_WORK.md` — enumerated future work + assessed chart-type shortlist.
- `.claude/skills/dom-write/SKILL.md` — installed DomI voice skill (applied to page prose).

## Known limitations (honest)
- Lean axis rests on 8 two-camp stories — wide CIs, will firm up as the corpus grows.
- Distance is lexical (TF-IDF char+word), not semantic; paraphrase reads as drift.
- The 44.7% unrated regional outlets shape the consensus but are invisible to the lean axis.
- Commits show GitHub "Unverified": committer email is correct; the env's SSH signing key
  is an empty 0-byte file, so signatures cannot be produced here.

## Open follow-ups
- Build the outlet×story heatmap and/or syndication UpSet (both supported by current bundle).
- Near-duplicate (not just exact) syndication collapse via simhash.
- Daily CI auto-refresh of the bundle.
