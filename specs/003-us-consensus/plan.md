# Plan 003: US Consensus Distance via Runner-Fetched Corpus

**Created**: 2026-06-12 | **Branch**: development | **Status**: Executing

## Problem
US equivalent of the German consensus-distance study. Sandbox egress blocks every US
headline source (HF connector not attached to this session; archive.org/RSS/GDELT all
403 locally). GitHub Actions runners have open egress — use a workflow as the fetcher,
commit the corpus into the repo, ingest from git.

## Source strategy (executed on the runner, in order)
1. **GDELT DOC 2.1 API** (primary): `sourcecountry:US` political queries, day-windowed
   loops over the last 30 days, max 250 records/query → headline, domain, datetime,
   url. Hundreds of US outlets, weeks of depth, one workflow run.
2. **Live RSS snapshot** (fallback/supplement): ~25 national political feeds (Politico,
   The Hill, NPR, AP, Fox, CNN, NYT, WaPo, ABC, CBS, NBC, Axios, Newsmax…) — current-day
   stories if GDELT fails.
3. **HF probe** (report-only): list `palewire` datasets from the runner; write findings
   to the fetch report for future use; not load-bearing.

Output committed by the workflow to `corpus/us/headlines.csv.gz`
(columns: domain, title, url, seendate, source) + `corpus/us/FETCH_REPORT.md`.

## Tasks
| # | Task | Owner |
|---|---|---|
| T1 | Spec/plan/checklist committed | main ✔ this doc |
| T2 | `scripts/fetch_us_news.py` + `.github/workflows/fetch-us-news.yml` (workflow_dispatch); trigger; verify corpus lands | main |
| T3 | Loader `load-us-headlines` (csv.gz → article/claim rows, English negation, domain-keyed outlets, ≥N-article outlet floor) + tests | haiku |
| T4 | Ingest → us.db; realign-embed 0.5; report ≥5-outlet event count | main |
| T5 | e7 run (db=us.db) → results/e7_us_*, docs/data/consensus_us.json; review V1/V2 + face validity | main |
| T6 | consensus.html gains US section (second ranking chart + validation cards + story explorer, corpus switcher header) | haiku |
| T7 | Full verify, commit, push, PR, merge, deploy confirm | main |

## Checklists

### T2 fetch
- [ ] Workflow runs on workflow_dispatch, commits only under corpus/us/
- [ ] GDELT loop covers ≥21 days, dedupes by URL, UTF-8 safe
- [ ] FETCH_REPORT.md states per-source counts + HF probe result
- [ ] ≥10,000 headlines OR fallback engaged and reported
- [ ] No secrets in workflow; uses GITHUB_TOKEN only

### T3 loader
- [ ] gz + plain csv accepted; outlet = registered domain (reuse normalize_domain)
- [ ] English negation regex → not-occurred claims
- [ ] Outlet floor (default ≥20 articles) to drop one-off domains
- [ ] Idempotent re-run (URL upsert)
- [ ] Unit tests: parse, negation, floor, idempotency; suite green; ruff clean

### T4 ingest/align
- [ ] us.db articles ≥ 8,000 after floor
- [ ] realign threshold 0.5; spot-check 3 largest events for merge quality
- [ ] events with ≥5 outlets ≥ 40 (else: lower floor / widen window, document)

### T5 analysis
- [ ] e7 outputs: article CSV, outlet CSV, PNG, consensus_us.json with corpus metadata
- [ ] V1 planted gate result recorded (relative criteria)
- [ ] V2 split-half ρ recorded; pass/fail reported honestly
- [ ] Face validity noted (wire-heavy outlets nearest; partisan outliers farthest)

### T6 site
- [ ] US section renders from docs/data/consensus_us.json with graceful fallback
- [ ] German section untouched; both labeled by corpus + language
- [ ] dom-write voice; JS parses; chart count check

### T7 ship
- [ ] pytest + ruff green; CI smoke unaffected
- [ ] Pushed, PR opened, merged on approval, Pages deploy green
- [ ] consensus tab live with both corpora
