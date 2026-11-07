# Cutoff sweep and omission test (2026-11-07)

Branch `exp/cutoff-sweep`, cut from `fix/nobs-ncd-rerun` at `a4b4d2a`. The run used a
Claude Code cloud container with Python 3.11.18 and 4 vCPU. Nothing under `paper/` or `docs/`
was edited.

## Verdicts

| test | pre-registered verdict |
|---|---|
| Part 1: e3b minimum-claims sweep | **FILTER ARTIFACT** |
| Part 2: omission → main-topic test | **FAIL** |

**e3b.** The mean ρ never reaches −0.15 at any cutoff. Its most negative value is −0.124, at
`min_obs=1`. Significance (p<0.05) shows up only at `min_obs=1`, where all 10 seeds pass. At
2, 3 and 5 no seed passes. The sign is negative at every cutoff. So REAL fails, and the
FILTER ARTIFACT condition (significance only at `min_obs ≤ 2`) holds. UNDERPOWERED does not
apply, because the CI excludes 0 at `min_obs=1`. Both CI readings below give the same verdict.

**Omission.** Top-100 accuracy is 0.904, which clears the 0.80 bar. All four |ρ| are at
least 0.83, which clears 0.6. The test still fails because the omission score loses to the
raw-count baseline by 0.038 (0.904 vs 0.942). It was required to beat the baseline by
+0.05.

## Setup: rebuilt DBs

I rebuilt the DBs with the recipes in `results/rerun_m1/README.md`:

* FNN: `load-fakenewsnet → dedup → extract → align-cmd → realign-embed → load-external-labels`
* UCI: `load-uci → dedup → load-external-labels`
* ISOT: `load-isot` on marwaa123/fake_real_news, then `dedup → extract → align-cmd →
  realign-embed --max-block-size 300`

The ISOT inputs match the hashes recorded there. True.csv is `d30b97c9…5590` and Fake.csv is
`bebf8bcf…0d0c`. The realign step reported **2,925 multi-outlet events**, as expected.

| DB | sha256 | article | claim | event | outlet | other rows |
|---|---|---|---|---|---|---|
| fnn.db | `b3d35b92522c34d22c8acd6ee30fe4b11b0a5e48bb3e33cdc1fc0861111e86ab` | 21,575 | 6,121 | 2,266 | 2,531 | article_label 21,575; outlet_external_label 859; source_cursor 4 |
| uci.db | `10c256f24bc38f73331664210b6187a267352fafdc33b500086815565f4858df` | 422,703 | 422,703 | 7,231 | 10,980 | article_label 422,703; outlet_external_label 859; uci_story 7,231 |
| stream.db | `e3a99f639dae335a6602f1e2b70629e86bf0e73c847b398a2dc3420023b20a26` | 43,295 | 57,480 | 20,184 | 7 | — |

Every row count matches `results/rerun_m1/db_stats.json`. The file sha256 values do not match
rerun_m1, and cannot. `schema_migrations.applied_at` stores the wall-clock time of the build
(`db.py:48`), so each rebuild produces different bytes. What matters is that the content is
equivalent, and the next section shows that. Full stats are in `db_stats.json`.

## Part 1: minimum-claims cutoff sweep

* **Code change.** e6 now has a `min_obs` config knob, default 3. Outlets below the cutoff
  still take part in EM but are left out of AUC, real-rank and mean-fake reliability, as in
  e3, e3b and e4. The output also records `metrics.min_obs` and `metrics.n_outlets_scored`.
  The test is `tests/unit/test_e6_anchoring.py::test_e6_min_obs_filter`. It checks that the
  default is 3 and that cutoffs of 1, 3 and 5 score 4, 3 and 0 outlets. It also checks that
  the EM event set does not change with the cutoff.
* **Runs.** `scripts/cutoff_sweep.py` uses the configs of `scripts/rerun_m1.py`, with dedup
  voting on, seeds 42–51, and `min_obs` overridden to 1, 2, 3 and 5. That is 4 experiments
  × 4 cutoffs × 10 seeds = 160 runs, and all of them completed. e6 uses budgets 0 to 2500
  with one anchor draw per seed. The per-run folders were kept out of the repo. Every run
  manifest is in `runs.jsonl`.
* **Outputs.**
  * `sweep.csv`: one row per (experiment, min_obs, seed).
  * `summary.csv` and `summary.md`: the summary table.
  * `rho_vs_min_obs.png`: the 4-panel plot.
  * `verdict_e3b.json`: the rule check.
  * `compare_rerun_m1.md`: the per-seed check against rerun_m1.

### Summary table

How to read the columns:

* **95% CI over seeds** is a t-interval for the mean across the 10 seeds. It only reflects
  how much EM batch order moves ρ.
* **Bootstrap CI** is a 1000-resample CI over outlets within each seed, with the bounds
  averaged over seeds. This is the interval that reflects sampling uncertainty.
* **Dropped vs prev** is how many fewer outlets are scored than at the previous cutoff.

| exp | min_obs | seeds | ρ mean ± SD | 95% CI over seeds | 95% bootstrap CI (mean bounds) | seeds p<0.05 | AUC mean ± SD | outlets | dropped vs prev |
|---|---|---|---|---|---|---|---|---|---|
| e3b | 1 | 10 | -0.1244 ± 0.0042 | [-0.1274, -0.1215] | [-0.217, -0.030] | 10/10 | 0.1045 ± 0.0035 | 341 | — |
| e3b | 2 | 10 | -0.1121 ± 0.0031 | [-0.1143, -0.1098] | [-0.224, 0.002] | 0/10 | 0.1420 ± 0.0047 | 246 | 95 |
| e3b | 3 | 10 | -0.1168 ± 0.0045 | [-0.1200, -0.1135] | [-0.243, 0.014] | 0/10 | 0.1602 ± 0.0057 | 192 | 54 |
| e3b | 5 | 10 | -0.0890 ± 0.0092 | [-0.0956, -0.0824] | [-0.256, 0.080] | 0/10 | 0.2253 ± 0.0080 | 127 | 65 |
| e4 | 1 | 10 | -0.0869 ± 0.0576 | [-0.1281, -0.0457] | [-0.424, 0.253] | 0/10 | — | 34 | — |
| e4 | 2 | 10 | -0.0344 ± 0.0604 | [-0.0776, 0.0088] | [-0.412, 0.318] | 0/10 | — | 27 | 7 |
| e4 | 3 | 10 | -0.0434 ± 0.0714 | [-0.0945, 0.0077] | [-0.473, 0.371] | 0/10 | — | 22 | 5 |
| e4 | 5 | 10 | -0.1112 ± 0.0826 | [-0.1703, -0.0521] | [-0.552, 0.361] | 0/10 | — | 18 | 4 |
| e4_uci | 1 | 10 | -0.0903 ± 0.0567 | [-0.1309, -0.0498] | [-0.226, 0.046] | 2/10 | — | 207 | — |
| e4_uci | 2 | 10 | -0.0903 ± 0.0567 | [-0.1309, -0.0498] | [-0.226, 0.046] | 2/10 | — | 207 | 0 |
| e4_uci | 3 | 10 | -0.0903 ± 0.0567 | [-0.1309, -0.0498] | [-0.226, 0.046] | 2/10 | — | 207 | 0 |
| e4_uci | 5 | 10 | -0.0903 ± 0.0567 | [-0.1309, -0.0498] | [-0.226, 0.046] | 2/10 | — | 207 | 0 |
| e6 | 1 | 10 | — | — | — | — | 0.1167 ± 0.1766 | 7 | — |
| e6 | 2 | 10 | — | — | — | — | 0.1167 ± 0.1766 | 7 | 0 |
| e6 | 3 | 10 | — | — | — | — | 0.1167 ± 0.1766 | 7 | 0 |
| e6 | 5 | 10 | — | — | — | — | 0.1167 ± 0.1766 | 7 | 0 |

What each experiment measures:

* **e3b:** ρ(reliability, 1 − fake share); AUC is `auc_mostly_fake`.
* **e4 / e4_uci:** ρ(reliability, MBFC fact).
* **e6:** AUC for reuters vs fake:* at k=2500. The per-budget AUCs are in
  `sweep.csv:auc_by_budget`.

The bootstrap CI excluded 0 in this many seeds per cutoff:

| exp | min_obs 1 | 2 | 3 | 5 |
|---|---|---|---|---|
| e3b | 10 | 4 | 0 | 0 |
| e4 | 0 | 0 | 0 | 0 |
| e4_uci | 2 | 2 | 2 | 2 |

### e3b rule check (`verdict_e3b.json`)

| condition | result |
|---|---|
| REAL: mean ρ ≤ −0.15 with CI excluding 0 at every `min_obs ≥ 3`, and sign stable | **no**. Mean ρ is −0.117 at 3 and −0.089 at 5, both above −0.15. The sign is stable (all negative). |
| FILTER ARTIFACT: significance only at `min_obs ≤ 2` | **yes**. Most seeds have p<0.05 only at `min_obs=1` (10/10). The other cutoffs have 0/10. |
| UNDERPOWERED: CI spans 0 at every cutoff | no. Under the bootstrap CI it excludes 0 at `min_obs=1`. Under the seed CI it excludes 0 at every cutoff. |

**Verdict: FILTER ARTIFACT** under both CI readings.

The committed e3b result (ρ = −0.1587, p = 0.0033 on 341 outlets) also does not come back at
`min_obs=1`. That cutoff scores the same 341 outlets but gives ρ = −0.124 ± 0.004. Removing
the filter recovers significance but not the old effect size. Something else about the old
run therefore contributed, such as its DB build or its unseeded batch order.

### Check against `results/rerun_m1/COMPARE.md`

All 40 `min_obs=3` cells (4 experiments × 10 seeds) match the rerun_m1 per-seed manifests
exactly. There are **0 metric mismatches**. The fields compared were:

* e3b: ρ, AUC and outlet count
* e4 and e4_uci: ρ_fact and outlet count
* e6: the full `auc_by_budget`

The seed means therefore equal COMPARE.md:

* e3b: −0.1168 ± 0.0045 on 192 outlets, AUC 0.1602, 0/10 seeds significant
* e4: −0.0434 ± 0.0714 on 22 outlets
* e4_uci: −0.0903 ± 0.0567 on 207 outlets; 2/10 seeds have a CI excluding 0
* e6: AUC[2500] of 0.1167 ± 0.1766, on 2,925 events

The only differences in `compare_rerun_m1.md` are the `db_sha256` values, explained above.

## Part 2: omission test (`results/omission_test/`)

Script: `scripts/omission_test.py`. Seeds 42–51.

**Method.**

1. Each outlet's articles are split 50/50 at random, stratified by outlet.
2. The omission score is computed from half A only, using the E5 logic:
   * Audit events are events covered by at least 3 distinct outlets in half A.
   * An event's category is the majority label among its half-A articles.
   * omission = 1 − (share of the category's audit events that the outlet covers).
3. Prediction = the category with the lowest omission score.
4. Truth = the category with the largest share of the outlet's half-B articles.
5. Baseline = the argmax of the outlet's half-A raw article counts per category, scored
   against the same truth.

**Check that this is the E5 logic.** On the full data, my vectorised coverage matrix equals
`e5_omission._compute_coverage_matrix` exactly (max abs diff 0.0). Its category denominators
are b 1999, t 1779, e 2068, m 1320, the same as the committed `results/e5_omission.csv`.

| | top-30 | top-100 |
|---|---|---|
| omission accuracy (mean ± SD over seeds) | 0.970 ± 0.011 | **0.904 ± 0.018** |
| raw-count baseline accuracy | 0.997 ± 0.011 | **0.942 ± 0.015** |
| omission − baseline | −0.027 | **−0.038** |
| chance | 0.25 | 0.25 |

Spearman ρ between half-A omission score and half-B article share, across outlets, per
category (mean ± SD over seeds):

| category | top-30 | top-100 |
|---|---|---|
| b (business) | −0.970 ± 0.003 | −0.952 ± 0.003 |
| t (sci/tech) | −0.880 ± 0.014 | −0.830 ± 0.009 |
| e (entertainment) | −0.959 ± 0.004 | −0.947 ± 0.003 |
| m (health) | −0.923 ± 0.015 | −0.895 ± 0.011 |

The pre-registered criteria:

| criterion | result |
|---|---|
| top-100 accuracy ≥ 0.80 | met (0.904) |
| beats the baseline by ≥ 0.05 | **not met (−0.038)** |
| \|ρ\| ≥ 0.6 in all 4 categories | met |

**Verdict: FAIL.** The omission score tracks topic share closely, but it adds nothing over
counting the outlet's articles. Its misses lean toward t and m, the categories with the fewest
audit events. Dividing by a small category denominator inflates coverage rates for outlets
with modest t or m output. `predictions_seed42.csv` lists every top-100 outlet's prediction.

The truth labels are lopsided. Among the top-100 outlets, 39 are b, 12 are t, 48 are e and
1 is m. Among the top-30: b 13, t 3, e 14, m 0. So 0.25 understates the accuracy of always
guessing the majority class. For reference, the in-sample version (no split, so circular) on
the full data scores 0.967 on the top-30 and 0.900 on the top-100. Taking the argmin of the
committed `results/e5_omission.csv` top-30 scores against full-data shares gives 29 of 30
correct.

## Deviations from the spec

1. **e6 has no rank correlation.** Its outcome is the AUC between 1 real and 6 fake outlets.
   The e6 rows of `sweep.csv` leave `rho` and `p` blank and report the AUC at the largest
   budget (k=2500), with every budget in `auc_by_budget`. The fourth plot panel shows that
   AUC, not ρ.
2. **The cutoff does not bind in e4_uci or e6.** Their rows are identical across cutoffs by
   construction.
   * e4_uci: each UCI article carries exactly one claim, and e4 already requires at least 5
     articles per outlet. Every joined outlet therefore has n_obs ≥ 5 (the minimum is 5).
   * e6: the 7 ISOT outlets have between 993 and 14,919 hard claims each.
3. **Two CI readings were evaluated, and both give FILTER ARTIFACT.** "CI" was not defined
   in the spec. The seed CI only captures batch-order noise (SD around 0.004), so on its own
   it would call any nonzero mean significant. The bootstrap CI over outlets is reported
   alongside it.
4. **"Significance" means p<0.05 in most seeds.** In practice the split is clean: 10/10 at
   `min_obs=1` and 0/10 elsewhere.
5. **Some p-values and CIs were computed after the runs.**
   * e4 does not output a p-value. It is computed from ρ and n with the t approximation that
     `scipy.spearmanr` uses. The e4 CIs are the experiment's own bootstrap.
   * e3b has no CI output. Its CI is a 1000-resample bootstrap over the per-outlet CSV,
     seeded with the run's own seed.
6. **Some omission details were not set by the spec.**
   * Top-N outlets are ranked by total article count over the full corpus. E5 instead ranks
     by articles in audit events.
   * Ties in argmin or argmax go to the first category in the order b, t, e, m.
   * The audit events, event categories and coverage are all recomputed from half A, so no
     half-B information enters the predictor.
7. **Per-run output folders are not committed.** That is 160 folders of CSV, PNG and
   manifest files. `runs.jsonl` holds every run manifest, and `sweep.csv` holds the numbers.
8. **Lint.** `ruff check` passes on the two new scripts. CI's `ruff check .` reports 428
   findings across the repo under the ruff version pip installs today (0.17.4). That count
   was the same on the base commit before these changes. I left them alone because they are
   out of scope.

## Reproduce

```
.venv/bin/python scripts/cutoff_sweep.py run --db-dir ../dbs --work ../sweep_runs
.venv/bin/python scripts/cutoff_sweep.py summarize --work ../sweep_runs
.venv/bin/python scripts/omission_test.py --db ../dbs/uci.db
```
