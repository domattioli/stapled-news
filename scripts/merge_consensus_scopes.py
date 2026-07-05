#!/usr/bin/env python
"""Merge two E7 consensus bundles into the site bundle with split scopes.

Global/aggregate visualizations (outlet ranking, lean axis, weekly series,
syndication, regional impact, panel composition, article swarm, corpus counts)
come from the FULL-corpus run. The example-headline cards (the diff explorer,
`events`/`events_detail`) come from a RECENT-window run so the illustrative
stories stay current instead of surfacing months-old coverage.

Usage: merge_consensus_scopes.py FULL.json WINDOW.json OUT.json [--window-since DATE --window-until DATE]

Note: the window bundle's own corpus.since/until is unreliable if the window DB
was built by pruning `article` rows without also pruning `fp_article_meta` (that
table is keyed by URL and tracks first_seen/last_seen independently, so it still
reports the full historical range). Pass --window-since/--window-until with the
window DB's actual article date range to override.
"""
import argparse
import json

parser = argparse.ArgumentParser()
parser.add_argument("full_path")
parser.add_argument("window_path")
parser.add_argument("out_path")
parser.add_argument("--window-since", default=None)
parser.add_argument("--window-until", default=None)
args = parser.parse_args()

full_path, window_path, out_path = args.full_path, args.window_path, args.out_path

with open(full_path) as f:
    full = json.load(f)
with open(window_path) as f:
    window = json.load(f)

# Base = full-corpus bundle (all aggregate sections + article swarm).
merged = dict(full)

# Example-headline portion comes from the recent window.
merged["events"] = window.get("events", [])
merged["events_detail"] = window.get("events_detail", [])

# Record the two scopes so the page (and readers) can tell them apart.
merged["scopes"] = {
    "aggregates": {
        "since": full["corpus"].get("since"),
        "until": full["corpus"].get("until"),
        "n_corpus_articles": full["corpus"].get("n_corpus_articles"),
        "n_events": full["corpus"].get("n_events"),
        "note": "All aggregate charts reflect the full corpus.",
    },
    "examples": {
        "since": args.window_since or window["corpus"].get("since"),
        "until": args.window_until or window["corpus"].get("until"),
        "n_corpus_articles": window["corpus"].get("n_corpus_articles"),
        "n_events": window["corpus"].get("n_events"),
        "note": "Example story cards reflect the trailing recent window.",
    },
}

with open(out_path, "w") as f:
    json.dump(merged, f, indent=2)

print(
    f"merged: aggregates over {merged['scopes']['aggregates']['n_corpus_articles']} "
    f"articles / {len(merged['ranking'])} outlets; "
    f"{len(merged['events_detail'])} example stories from "
    f"{merged['scopes']['examples']['since']}..{merged['scopes']['examples']['until']}"
)
