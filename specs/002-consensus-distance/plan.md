# Implementation Plan: Consensus Distance (002)

**Spec**: spec.md | **Created**: 2026-06-12

## Design decisions

### D1 — Corpus access via local archive clone
`/tmp/fp2026` shallow clone of defgsus/frontpage-archive-2026, deepened with
`--shallow-since=2026-05-13` (299 hourly snapshots, 2026-05-13 → 2026-06-12). Loader
walks `git log --format=%H %cI` and reads files with `git show <sha>:<path>` —
no checkouts, no network after the clone. Clone commands recorded in the experiment
manifest config for reproducibility.

### D2 — Outlet/section map (political coverage only)
| outlet | sections |
|---|---|
| bild.de | politik |
| compact-online.de | (all — single-topic far-right outlet) |
| faz.net | politik, aktuell |
| fr.de | politik |
| spiegel.de | politik, ausland |
| sueddeutsche.de | politik |
| t-online.de | politik (or nachrichten) |
| welt.de | politik |
| zeit.de | politik, news |
| gmx.net / web.de | news/politik sections |
| volksstimme.de | politik if present |
Exact filenames resolved at load time per outlet directory (sections vary); heise.de,
zeitfuerdieschule.de, spiegeldaily.de excluded (tech/school/defunct).

### D3 — Article identity and headline variants
Key = URL (normalized: strip query/fragment). first_seen = earliest snapshot containing
the URL, last_seen = latest. Title/teaser = latest variant; variant count stored
(`title_variants`). New table `fp_article_meta(url PRIMARY KEY, outlet, section,
first_seen, last_seen, title_variants)` via migration 005; articles also inserted into
the standard `article` table (body = title + ". " + teaser) so the existing pipeline
(claims → embed-align → dedup → EM) runs unchanged.

### D4 — German text handling
Claim builder for this corpus mirrors the UCI loader's synthesized-claim approach
(one claim per article, negation regex extended:
`\b(nicht|kein|keine|keinen|dementiert|widerspricht|bestreitet|falsch|fake)\b`).
Event clustering relies on the char(3-5)-gram channel of embed_align, which is
language-agnostic; entity anchoring works on German capitalized spans (nouns are
capitalized in German — entity extraction will over-fire; mitigated by requiring
multi-token entity phrases OR cosine ≥ threshold as already implemented).

### D5 — Distance metric (new module `src/stapled/analyze/consensus_distance.py`)
For each event with ≥ 5 distinct outlets:
1. Vectorize member titles with the same dual word+char TF-IDF as the aligner (fit on
   the event-set corpus once).
2. Event centroid = W-weighted mean of member vectors, where W is the EM posterior mass
   of the member's claim observation (anchorless run → consensus-weighted centroid).
3. Consensus headline = member title with max cosine to centroid (reported verbatim).
4. distance(article) = 1 − cosine(article vector, centroid).
5. Outlet aggregate = mean distance over its qualifying articles; 95% CI by bootstrap
   over articles (1,000 resamples, seeded). Weekly series = same, grouped by ISO week
   of first_seen.
Outputs: results/e7_consensus_distance.csv (article-level),
results/e7_outlet_distance.csv (aggregate), docs/data/consensus.json (site bundle:
ranking, distributions (decile summaries), weekly series, top-30 event explorer
entries).

### D6 — Validation lanes
- V1 (gate): synthetic planted outlets — "copier" reprints each consensus headline
  verbatim, "noise" emits shuffled cross-event titles; require
  mean_dist(copier) < 0.1 and mean_dist(noise) > mean_dist(copier) + 0.3.
- V2 (gate): split-half stability — outlet means on weeks {1,3} vs {2,4}; Spearman
  ρ ≥ 0.6 to pass; reported either way.
- V3 (reported): compact-online.de vs mainstream ordering; portal cluster
  (t-online/gmx/web.de) proximity.

### D7 — Pages tab
`docs/consensus.html` ("Consensus Distance" nav item added to all 6 pages). Charts
(Plotly, house palette): ranking bar + CI, per-outlet distribution strips, weekly
multi-line, event-explorer table. dom-write voice. Corpus/language/author limitations
in a callout: German corpus; no bylines → outlet-level only.

### D8 — Experiment registration
`e7` in experiments __main__: `run(config, seed, out_dir)` does D5+D6 against the
prepared fp.db and writes the manifest entry (corpus SHA range in config).

## Phases
| Phase | Work | Owner |
|---|---|---|
| C1 | Migration 005 + frontpage loader + tests | Haiku |
| C2 | Run loader on /tmp/fp2026 → fp.db; pipeline (claims, align, dedup, EM) | Main |
| C3 | consensus_distance module + V1/V2 gates + tests; register e7 | Haiku |
| C4 | Run e7 real; review V1–V3 | Main |
| C5 | consensus.html + nav update + bundle | Haiku |
| C6 | Verify, commit, push, PR, deploy | Main |
