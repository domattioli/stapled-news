# Future Work — STAPLE-News US Consensus Distance

Brainstorm of where this can go, ordered roughly by value-to-effort. Written 2026-06-13
after the syndication fix and the move to a five-point lean spectrum.

## Data / corpus
- **More history, more two-camp stories.** Only 8 of 23 events currently have both a
  left-rated and a right-rated outlet, which is what bounds the directional-lean estimate.
  The hourly Google-News + RSS collector accrues ~500 headlines/run; a week of
  accumulation should multiply qualifying events and tighten every CI. No code change —
  just time, then rerun `load → realign → e7`.
- **Bring in palewire/news-homepages** (892 US outlets) once the HuggingFace connector is
  attached to a fresh session, or via a CI job that pulls its archive.org extracts. That
  turns the panel from ~50 outlets into hundreds and makes the lean spectrum dense.
- **Outlet-level lean coverage.** ~27 of the corpus's outlets are AllSides-unrated (mostly
  regional chains). Add the AllSides 2024 ratings CSV in full, or fall back to MBFC, so
  fewer outlets drop out of the directional analysis.
- **Bylines / authors.** The original ask included author-level drift. RSS/Google-News
  items sometimes carry `<dc:creator>`; harvest it where present to enable a
  per-author view, with the honest caveat that coverage will be partial.

## Method
- **Near-duplicate syndication, not just exact.** We now collapse byte-identical wire
  headlines (25% of the corpus). Light edits ("The Latest: …" prefixes, trailing
  attributions) slip through. A simhash / MinHash pass over titles would catch near-dupes;
  fold the cluster id into the centroid weight the same way exact-dups are handled now.
- **Embedding distance.** TF-IDF char+word cosine is lexical; two headlines that paraphrase
  the same framing in different words read as "far". A sentence-embedding distance (when a
  model is reachable) would measure semantic rather than surface drift and likely reshuffle
  the ranking.
- **Directional axis robustness.** The left/right wording axis is built per event from that
  event's camp members; with 1-2 outlets per camp it is noisy. Pool a global lean axis
  from all camp-labeled headlines (a single left-centroid and right-centroid across the
  corpus) and project every consensus headline onto it — more stable, comparable across
  stories.
- **Separate framing from topic.** Distance currently mixes "covered a different angle"
  with "phrased the same angle differently". Conditioning on the event's dominant entities
  would isolate framing.
- **Time dynamics.** Does an outlet's drift move when a story is breaking vs a day later
  (headline revisions)? `fp_article_meta.title_variants` already tracks rewrites; analyze
  drift against revision count.

## Visualization / story
- **Story-level drilldown.** Click an event in the explorer to see the full spread of every
  outlet's headline on that story, sorted by distance, with the syndicated cluster grouped.
- **Outlet profile cards.** Per outlet: distance distribution, lean, syndication rate, the
  stories where it drifted most.
- **"Who wrote the consensus" credit.** For each event, which outlet's headline was nearest
  the centroid — a leaderboard of "writes the sentence everyone converges on".
- **Animated accrual.** As the corpus grows, show CIs tightening over successive daily
  snapshots (the data to do this is already committed per fetch).

## Validation / rigor
- **V2 split-half** fails today purely on sample size; revisit once the corpus is larger.
- **Human spot-check** of the consensus headline per event — does the algorithm's "nearest"
  read as a fair neutral summary to a person? A small rater study would ground-truth it.
- **Sensitivity to the vectorizer** (n-gram ranges, char vs word weight): report how much
  the ranking moves under reasonable hyperparameter changes.

## Productization
- Daily auto-refresh of the bundle in CI (the collector already runs hourly; add a
  `load → realign → e7 → commit bundle` job).
- An RSS/email digest: "this week's most- and least-consensus outlets, and the stories
  where the field most disagreed on wording."

## Candidate chart types (assessed by fit, not novelty)

Honest read on which advanced visuals the data actually supports:

- **UpSet plot — strong fit.** The 25%-syndication finding is set-shaped: each verbatim
  wire headline is carried by a *set* of outlets. An UpSet of wire-copy sharing (which
  combinations of outlets most often run the identical sentence) extends the syndication
  story and is more honest than a pie — it shows *who* clusters, not just how much. Also
  works for co-coverage (which outlets tend to cover the same stories). With ~48 outlets,
  scope to the top intersections.
- **Sankey — plausible fit.** Two clean versions: (a) lean category (5) → drift band
  (near / mid / far from consensus), flows = outlet counts, to see whether a camp funnels
  into low drift; (b) syndication flow: wire-story clusters → the outlets that republished.
  (a) is the more legible.
- **Outlet × story heatmap — strongest underused fit.** Rows = outlets, cols = stories,
  cell = distance (blank where the outlet didn't cover it). Surfaces both coverage gaps
  (omission) and drift patterns in one grid; arguably more informative than anything on the
  page now.
- **Ridgeline / violin by lean — good fit.** Distance distribution per lean bucket stacked
  vertically; shows shape, not just the mean+CI the current dot plot shows.
- **Parallel coordinates — niche fit.** Outlets as lines across [lean, drift, syndication
  rate, stories covered]; good for the "near-consensus outlets are high-syndication"
  correlation, but reads as a specialist chart.
- **Radar / spider — weak fit, mostly decorative.** Only justified as per-outlet profile
  cards across 4-5 metrics; radar distorts comparison and there aren't enough independent
  clean axes. Prefer small-multiple bars for outlet profiles.

Recommendation if adding one: the **outlet × story heatmap** (most information per pixel,
directly shows omission + drift), then the **syndication UpSet** (extends a finding the
page now states but doesn't yet visualize).
