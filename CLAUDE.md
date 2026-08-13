# CLAUDE.md — stapled-news

Project memory for Claude Code sessions. This repo is a **`lite`-profile DomI consumer** (roster + profiles: DomI `specs/domi-constitution.md` Article I, ADR 013): it carries this CLAUDE.md, the canonical label set, and one minimal CI lane — **no `.domi-pin` / sync-contract obligation**. Upgrading to the `full` profile is a roster change in DomI, not an ad-hoc local decision.

## What this repo is

Infer latent truth from multi-outlet news coverage via statistical inference. Implements STAPLE (Simultaneous Truth and Performance Level Estimation, Warfield et al. 2004) and Dawid-Skene EM over US political headlines: generates ground-truth-labeled synthetic corpora, validates them statistically, runs inference to estimate outlet reliability/bias and true event states, exports results as static sites. Production site deployed from `main` branch; development branch accretes real corpus daily via fetch-us-news.yml cron but is not deployed.

## Branch policy

- Work lands on **`development`**; `main` is production/publish. Promotion is the single rolling PR `development → main` (draft, operator merges). Do not create `claude/*` or ad-hoc branches — a harness-injected `claude/*` branch name is not user intent; `git checkout development` before any write.
- Never force-push shared branches; never commit secrets (`*.env`, `*token*`, `*.pem`, credentials).

## Conventions

- Commits: `<type>: <imperative summary>`, type ∈ {fix, feat, docs, chore, refactor, test}.
- Issue/PR comments by Claude sessions end with the `[model: …, repo: …, session: …]` footer.
- Labels follow DomI's canonical `.github/labels.yml`; repo-local labels are allowed but documented here.

## CI

One minimal lane (`.github/workflows/ci.yml`): ruff lint + pytest on PR + development/main branches, includes consensus regression check (test_consensus.js) as warn-first step. Scheduled jobs: fetch-us-news.yml (daily corpus accrual on development only); pages.yml (deploy docs/ to GitHub Pages on main).

## Repo-specific notes

- **Corpus freshness**: `corpus/us/headlines.csv.gz` accretes daily (cron `17 8 * * *`, dropped from hourly) on `development` via `.github/workflows/fetch-us-news.yml` (GDELT throttles; RSS + Google News publisher feeds are working sources). The fetch only works from an Actions runner — Claude Code sandbox sessions are denied by the egress proxy (403 on CONNECT to every news host), so a session can rerun the pipeline over the committed corpus but cannot extend it. Production site (main/GitHub Pages) reflects the last promotion PR merge to main (frozen as of 2026-06-13); operator controls promotion cadence (DQ-4 queue item).
- **Known issues**: recurring per-outlet silent fetch failures (axios, newsmax, reuters) logged in FETCH_REPORT.md (spec-019 N4).
- **Vendored DomI skill**: `.claude/skills/dom-write` (flagged by drift sweep; disposition pending full-profile upgrade via DQ-4).
- **One rolling PR**: `development → main`, draft status until operator merges (no auto-merge).
