# Feature Specification: Consensus Distance on Recent Political News

**Branch**: `development` | **Status**: Planned | **Created**: 2026-06-12
**Spec ID**: 002-consensus-distance

## Goal

Apply the STAPLE-News model to a corpus of recent political news where each story is
covered by at least 5 sources, validate the resulting estimates, and quantify + visualize
how far each source sits, on average, from the consensus headline across the corpus.
Results ship as a dedicated tab on the GitHub Pages deployment.

## Corpus research (performed 2026-06-12)

Egress from this environment permits only github.com / raw.githubusercontent.com /
media.githubusercontent.com. Candidates evaluated:

| Candidate | Verdict |
|---|---|
| Live RSS (Reuters, Politico, BBC, memeorandum) | blocked (403/000) |
| Wikipedia Current Events / Wikinews API | blocked (403) |
| NELA-GT, POLUSA (Zenodo), All-the-News-2 (components.one), Dataverse, CommonCrawl, GDELT | hosts blocked |
| GitHub mirrors of the above | none at usable scale |
| **defgsus/frontpage-archive-2026** | **selected** |

**Selected corpus**: `defgsus/frontpage-archive-2026` (plus `-2025` if more depth is
needed) — hourly GitHub-Actions snapshots of 15 German online-press frontpages, current
through the day of writing. Per outlet, per section, JSON files of
`{title, teaser, url, image_url, image_title}`. Political sections (`politik`,
`ausland`, portal news pages) across bild.de, faz.net, fr.de, spiegel.de,
sueddeutsche.de, t-online.de, welt.de, zeit.de, gmx.net, web.de, volksstimme.de and
compact-online.de give well over five outlets on every major national/international
political story. The presence of compact-online.de (far-right) provides a built-in
face-validity probe. Corpus is German; the distance metric (character-n-gram cosine) is
language-agnostic, and event clustering already uses char-n-gram TF-IDF.

**History access**: shallow clone + `git fetch --shallow-since=<date>`; each commit is an
hourly corpus snapshot; `git show <sha>:<path>` extracts files without checkout.

## Definitions

- **Story (event)**: cluster of articles across outlets covering the same occurrence,
  built with the existing char+word n-gram + entity-anchored alignment over
  title+teaser text. Only events with ≥ 5 distinct outlets enter the analysis
  (the goal's corpus constraint).
- **Consensus headline**: for each event, the article title whose TF-IDF vector is
  closest to the event's claim-weighted centroid, where claim weights are the STAPLE
  posterior-informed weights (W_i from the online EM run over the event set). Reported
  verbatim on the site.
- **Distance from consensus**: cosine distance (1 − cosine similarity) between an
  article's title vector and its event centroid. Per-source distance = mean over all
  the source's articles in qualifying events, with a bootstrap 95% CI.
- **Authors**: frontpage teasers carry no bylines (verified on the schema; `image_title`
  credits photographers, not writers). The author axis is therefore reported at the
  source (outlet) level only, and this limitation is stated on the page. Where URL
  slugs embed author names (rare), they are ignored rather than half-measured.

## Functional requirements

- FR1 Loader `load-frontpages`: walk the local archive clone's commit history between
  configurable dates; per commit, parse the political-section JSONs for the configured
  outlets; upsert articles keyed by URL (first_seen, last_seen, latest title/teaser,
  outlet, section). German negation lexicon (nicht/kein/keine/widerspricht/dementiert)
  added to the claim builder used for this corpus.
- FR2 Pipeline run: claims from title+teaser; embed-align clustering; dedup (portal
  sites gmx/web.de syndicate t-online content — dedup voting matters here and the
  syndication structure is reported); online EM with dedup voting on, consensus-language
  outputs.
- FR3 Distance module `consensus_distance.py`: event centroids, consensus headline
  selection, per-article distances, per-outlet aggregation with bootstrap CIs, weekly
  time series. Exports CSV + JSON bundle.
- FR4 Validation (three lanes):
  - V1 planted-paraphrase synthetic: inject a synthetic outlet that always reprints the
    consensus headline (expected distance ≈ 0) and one that emits shuffled unrelated
    titles (expected distance ≫ 0); the metric must separate them (sanity gate).
  - V2 split-half stability: outlet mean distances computed on disjoint week halves
    must correlate (Spearman ρ ≥ 0.6 target) — distance is a stable outlet property,
    not noise.
  - V3 face validity (reported, not gated): compact-online.de expected farther from
    consensus than dpa-fed mainstream outlets; portal sites (gmx/web.de/t-online)
    expected nearest (shared wire copy).
- FR5 Visualizations (new Pages tab `consensus.html`, nav label "Consensus Distance"):
  1. Outlet ranking — mean distance from consensus headline, bootstrap CI bars.
  2. Distance distributions — per-outlet strip/box of article distances.
  3. Weekly trajectory — mean distance per outlet over time.
  4. Event explorer — table of high-coverage events: consensus headline, nearest and
     farthest outlet headlines with distances.
  All driven by `docs/data/consensus.json`; dom-write voice; nav updated on all pages.
- FR6 Reproducibility: experiment registered as `e7` in the experiments runner with
  manifest entry; corpus build documented (clone commands + date window) since the
  archive itself is not vendored.

## Out of scope

- Author-level analysis beyond the documented limitation (no bylines in the corpus).
- English-language corpus (none reachable at ≥5-outlets-per-story scale; revisit if
  egress policy changes).
- Translation of headlines on the site (originals shown; the page notes the corpus
  language).

## Risks

- R1 Frontpage A/B headline variants inflate within-outlet variance → keep latest title
  per URL; variant count recorded.
- R2 Portal syndication (t-online/gmx/web.de share a newsroom) → dedup voting +
  reported as a syndication finding, not hidden.
- R3 German compound words weaken word-level matching → char-n-gram channel dominates
  (already in the aligner); validated by V1.
- R4 30-day window may be thin for weekly trajectories → extend via
  `--shallow-since` further back or the -2025 repo if V2 stability fails.
