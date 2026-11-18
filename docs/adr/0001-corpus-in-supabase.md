---
status: accepted
date: 2026-11-18
---

# Corpus lives in Supabase, not in git

A daily cron recommitted `corpus/us/headlines.csv.gz` whole. Gzip blobs do not delta-compress. 513 versions of that file made up 2,405 MB of a 2.4 GB repository. All other history was under 5 MB. We moved the corpus to a Supabase Postgres table and removed the file from git history.

## Decision

- Headlines are stored in `public.headlines`, primary key `url`. Other columns: `domain`, `title`, `seendate`, `source`, `first_seen_at`. Row level security is on with no policies, so only the service role key reaches the table. The schema is in `supabase/migrations/20261118000000_headlines.sql`.
- The daily cron (`.github/workflows/fetch-us-news.yml`) upserts only the rows of the current run and commits nothing, when the repository variable `CORPUS_STORE` is `supabase`. It is `supabase` now. Unset or `git` restores the old commit-the-gzip behaviour. Each run also uploads its rows as a 90-day Actions artifact before the upsert.
- Secrets used: `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` (Actions secrets).
- The gzip path is gitignored. Code reads the corpus through `resolve_corpus()` in `src/stapled/ingest/snapshot.py`. It uses a local file if present, else a snapshot whose sha256 matches `corpus/us/SNAPSHOT.json`.
- The file was removed from all history with `git filter-repo`. All seven remote branches were force-pushed on 2026-11-18. A fresh clone's `.git` went from 2.5 GB to 8.6 MB.

## Considered options

- Keep files in git as append-only daily partitions. This stops the growth and needs no external service. It does not reclaim the existing 2.4 GB without the same rewrite, and it keeps the data in the repo.
- Gzip file in Supabase Storage. The code change is smaller. There is no row-level dedup and no queries.
- Public snapshot as a GitHub Release asset. The maintainer deferred this. It is not rejected.

## Consequences

- Every commit SHA from before 2026-11-18 changed. Old SHAs in notes or links no longer resolve in a fresh clone. The pre-rewrite backup was deleted, so the rewrite cannot be undone.
- At migration the table held 111,988 rows. This equals the unique URLs in the last committed gzip. It is about 87 MB of the 500 MB free tier.
- No public snapshot exists yet: `SNAPSHOT.json` has `published: false`. A clone without a local corpus file and without Supabase access cannot load the corpus. Reproducing the paper needs a published snapshot first.
- The pipeline now depends on an external service on a free tier. The daily cron keeps the project active.
- `supabase-backfill.yml` can only be dispatched once it exists on `main`.
- GitHub still stores the old objects through hidden pull-request refs (about 2.65 GB reported server-side). Clones are not affected.
