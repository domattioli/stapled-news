# Rerun M1 (2026-11-07)

Ten-seed rerun of the real-data experiments after the hard `n_obs` filter
(3307109). Built and run in a Claude Code cloud container (Python 3.11.18,
4 vCPU). The committed `results/` files are untouched. Comparison:
[`COMPARE.md`](COMPARE.md) (built by `scripts/rerun_m1_compare.py`).

## Input DBs (rebuilt from the repo loaders; not committed)

| DB | recipe | sha256 | articles | claims | events | outlets |
|---|---|---|---|---|---|---|
| fnn.db | `load-fakenewsnet` → `dedup` → `extract` → `align-cmd` → `realign-embed` → `load-external-labels` | `33ece161…d6b5d0` | 21,575 | 6,121 | 2,266 | 2,531 |
| uci.db | `load-uci` → `dedup` → `load-external-labels` | `a02cca34…e92f27d` | 422,703 | 422,703 | 7,231 | 10,980 |
| stream.db (ISOT) | `load-isot` (marwaa123/fake_real_news True.csv + Fake.csv) → `dedup` → `extract` → `align-cmd` → `realign-embed --max-block-size 300` | `c58dd725…5bd253` | 43,295 | 57,480 | 20,184 | 7 |

Full hashes and per-table row counts: [`db_stats.json`](db_stats.json). Each
run's `manifest.json` also logs `db_sha256`; they match the table.
ISOT inputs: True.csv `d30b97c9…5590`, Fake.csv `bebf8bcf…0d0c`.

The original build recipes are not recorded in the repo, so these are
reconstructions. The FNN outlet count (2,531) matches PAPER.md, and the ISOT
multi-outlet event count (2,925) is close to the committed 2,941. UCI is the
full 423k-row file, which the last e4_uci entry also used (7,202 events).
`realign-embed` with no block cap ran out of memory on ISOT (15 GB), so the cap
of 300 from the US-corpus fix was used. A stream.db built with `align-cmd` only
(no realign) gave e3 451 events and 4 outlets and crashed e6 (next section). It
was discarded.

## Runs (`scripts/rerun_m1.py`)

* e3b, e4, e4_uci, e6: seeds 42–51, one folder per seed. Configs match
  `stapled.experiments.__main__`. e6 uses the last committed budgets
  (0…2500) with one anchor draw per seed, which gives 10 independent draws.
* e2 (simhash) and e2_ncd (`dedup_method="ncd"`, tau 0.29): E2's own 10
  inner worlds (seeds 42–51), exact and perturbed modes, dedup voting on and
  off. SD is taken over the inner seeds from `e2_syndication.csv`.
* e3: one refresh at seed 42.

## Caveats

* **The e2 NCD arm is identical to simhash.** E2 template bodies are about
  110 bytes, below NCD's 200-byte floor, so `ncd_dedup` sends every document
  down its SimHash path. The arm cannot tell the two methods apart on E2 as
  built. `scripts/calibrate_ncd_tau.py` uses long synthetic bodies for this
  reason.
* **e6 fix.** The anchor truth lookup in e6 did `int(event_id)` on claims with
  `event_id IS NULL`, and it crashed on any DB with unaligned Reuters claims.
  It now filters those claims. A regression test was added.
* The manifests record `git_dirty: true`: the scripts and the e6 fix were not
  yet committed when the runs started (base 8841393).
