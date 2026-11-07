# Rerun M1 vs committed results

Old = last entry per experiment in `results/manifest.json` (line of the metric key). New = mean ± SD (ddof=1) over seeds; `n` = seed count. See `README.md` in this folder for DBs, configs and caveats.

| exp | metric | old | manifest line | new mean ± SD | n | flags |
|---|---|---|---|---|---|---|
| e3b | spearman_rho | -0.1587 | L292 | -0.1168 ± 0.0045 | 10 | SIGNIFICANCE CHANGE: p<0.05 in 0/10 seeds (old: sig) |
| e3b | spearman_pval | 0.0033 | L293 | 0.1074 ± 0.0139 | 10 | SHIFT > 2 SD |
| e3b | auc_mostly_fake | 0.0882 | L294 | 0.1602 ± 0.0057 | 10 | SHIFT > 2 SD |
| e3b | n_outlets_scored | 341 | L290 | 192.0000 ± 0.0000 | 10 | SHIFT > 2 SD |
| e3b | n_events_used | 318 | L291 | 310.0000 ± 0.0000 | 10 | SHIFT > 2 SD |
| e4 | spearman_fact | -0.1093 | L310 | -0.0434 ± 0.0714 | 10 | 95% CI excludes 0 in 0/10 seeds (old: no) |
| e4 | spearman_bias_abs | 0.2003 | L311 | 0.1362 ± 0.0684 | 10 | 95% CI excludes 0 in 0/10 seeds (old: no) |
| e4 | n_outlets_joined | 34 | L308 | 22.0000 ± 0.0000 | 10 | SHIFT > 2 SD |
| e4 | n_events_used | 318 | L309 | 310.0000 ± 0.0000 | 10 | SHIFT > 2 SD |
| e4_uci | spearman_fact | -0.1015 | L352 | -0.0903 ± 0.0567 | 10 | 95% CI excludes 0 in 2/10 seeds (old: no) |
| e4_uci | spearman_bias_abs | 0.0229 | L353 | -0.0032 ± 0.0400 | 10 | SIGN FLIP; 95% CI excludes 0 in 0/10 seeds (old: no) |
| e4_uci | n_outlets_joined | 176 | L350 | 207.0000 ± 0.0000 | 10 | SHIFT > 2 SD |
| e4_uci | n_events_used | 7202 | L351 | 7202.0000 ± 0.0000 | 10 |  |
| e2 | exact dedup_on m=1 | 0.8200 | L144 | 0.8200 ± 0.2251 | 10 |  |
| e2 | exact dedup_on m=2 | 0.7800 | L145 | 0.7800 ± 0.2098 | 10 |  |
| e2 | exact dedup_on m=5 | 0.8200 | L146 | 0.8200 ± 0.2251 | 10 |  |
| e2 | exact dedup_on m=10 | 0.8200 | L147 | 0.8200 ± 0.2251 | 10 |  |
| e2 | exact dedup_on m=20 | 0.8400 | L148 | 0.8400 ± 0.2221 | 10 |  |
| e2 | exact dedup_off m=1 | 0.8200 | L151 | 0.8200 ± 0.2251 | 10 |  |
| e2 | exact dedup_off m=2 | 0.7300 | L152 | 0.7300 ± 0.2497 | 10 |  |
| e2 | exact dedup_off m=5 | 0.7900 | L153 | 0.7900 ± 0.2183 | 10 |  |
| e2 | exact dedup_off m=10 | 0.3100 | L154 | 0.3100 ± 0.6315 | 10 |  |
| e2 | exact dedup_off m=20 | -0.8700 | L155 | -0.8700 ± 0.1160 | 10 |  |
| e2 | exact distortion_at_max_m | -1.7100 | L158 | -1.7100 ± 0.2470 | 10 |  |
| e2 | perturbed dedup_on m=1 | — | — | 0.8200 ± 0.2251 | 10 |  |
| e2 | perturbed dedup_on m=2 | — | — | 0.7300 ± 0.2497 | 10 |  |
| e2 | perturbed dedup_on m=5 | — | — | 0.7900 ± 0.2183 | 10 |  |
| e2 | perturbed dedup_on m=10 | — | — | 0.5100 ± 0.4149 | 10 |  |
| e2 | perturbed dedup_on m=20 | — | — | -0.6900 ± 0.4408 | 10 |  |
| e2 | perturbed dedup_off m=1 | — | — | 0.8200 ± 0.2251 | 10 |  |
| e2 | perturbed dedup_off m=2 | — | — | 0.7300 ± 0.2497 | 10 |  |
| e2 | perturbed dedup_off m=5 | — | — | 0.7900 ± 0.2183 | 10 |  |
| e2 | perturbed dedup_off m=10 | — | — | 0.3100 ± 0.6315 | 10 |  |
| e2 | perturbed dedup_off m=20 | — | — | -0.8700 ± 0.1160 | 10 |  |
| e2 | perturbed distortion_at_max_m | — | — | -0.1800 ± 0.4104 | 10 |  |
| e2_ncd | exact dedup_on m=1 | 0.8200 | L144 | 0.8200 ± 0.2251 | 10 |  |
| e2_ncd | exact dedup_on m=2 | 0.7800 | L145 | 0.7800 ± 0.2098 | 10 |  |
| e2_ncd | exact dedup_on m=5 | 0.8200 | L146 | 0.8200 ± 0.2251 | 10 |  |
| e2_ncd | exact dedup_on m=10 | 0.8200 | L147 | 0.8200 ± 0.2251 | 10 |  |
| e2_ncd | exact dedup_on m=20 | 0.8400 | L148 | 0.8400 ± 0.2221 | 10 |  |
| e2_ncd | exact dedup_off m=1 | 0.8200 | L151 | 0.8200 ± 0.2251 | 10 |  |
| e2_ncd | exact dedup_off m=2 | 0.7300 | L152 | 0.7300 ± 0.2497 | 10 |  |
| e2_ncd | exact dedup_off m=5 | 0.7900 | L153 | 0.7900 ± 0.2183 | 10 |  |
| e2_ncd | exact dedup_off m=10 | 0.3100 | L154 | 0.3100 ± 0.6315 | 10 |  |
| e2_ncd | exact dedup_off m=20 | -0.8700 | L155 | -0.8700 ± 0.1160 | 10 |  |
| e2_ncd | exact distortion_at_max_m | -1.7100 | L158 | -1.7100 ± 0.2470 | 10 |  |
| e2_ncd | perturbed dedup_on m=1 | — | — | 0.8200 ± 0.2251 | 10 |  |
| e2_ncd | perturbed dedup_on m=2 | — | — | 0.7300 ± 0.2497 | 10 |  |
| e2_ncd | perturbed dedup_on m=5 | — | — | 0.7900 ± 0.2183 | 10 |  |
| e2_ncd | perturbed dedup_on m=10 | — | — | 0.5100 ± 0.4149 | 10 |  |
| e2_ncd | perturbed dedup_on m=20 | — | — | -0.6900 ± 0.4408 | 10 |  |
| e2_ncd | perturbed dedup_off m=1 | — | — | 0.8200 ± 0.2251 | 10 |  |
| e2_ncd | perturbed dedup_off m=2 | — | — | 0.7300 ± 0.2497 | 10 |  |
| e2_ncd | perturbed dedup_off m=5 | — | — | 0.7900 ± 0.2183 | 10 |  |
| e2_ncd | perturbed dedup_off m=10 | — | — | 0.3100 ± 0.6315 | 10 |  |
| e2_ncd | perturbed dedup_off m=20 | — | — | -0.8700 ± 0.1160 | 10 |  |
| e2_ncd | perturbed distortion_at_max_m | — | — | -0.1800 ± 0.4104 | 10 |  |
| e6 | auc_by_budget[0] | 0.0000 | L491 | 0.0000 ± 0.0000 | 10 |  |
| e6 | auc_by_budget[100] | 0.0000 | L492 | 0.0000 ± 0.0000 | 10 |  |
| e6 | auc_by_budget[400] | 0.1500 | L493 | 0.0000 ± 0.0000 | 10 | SHIFT > 2 SD |
| e6 | auc_by_budget[800] | 0.2167 | L494 | 0.0000 ± 0.0000 | 10 | SHIFT > 2 SD |
| e6 | auc_by_budget[1200] | 0.6667 | L495 | 0.0333 ± 0.0703 | 10 | SHIFT > 2 SD |
| e6 | auc_by_budget[1600] | 0.6667 | L496 | 0.0833 ± 0.0878 | 10 | SHIFT > 2 SD |
| e6 | auc_by_budget[2000] | 0.7000 | L497 | 0.1167 ± 0.0805 | 10 | SHIFT > 2 SD |
| e6 | auc_by_budget[2500] | 0.7333 | L498 | 0.1167 ± 0.1766 | 10 | SHIFT > 2 SD |
| e6 | min_budget_full_recovery | — | L501 | None, None, None, None, None, None, None, None, None, None | 10 |  |
| e6 | n_multi_outlet_events | 2941 | L500 | 2925.0000 ± 0.0000 | 10 | SHIFT > 2 SD |
| e3 | auc_dedup_on | 0.0000 | L192 | 0.0000 ± 0.0000 | 1 |  |
| e3 | auc_dedup_off | 0.0000 | L198 | 0.0000 ± 0.0000 | 1 |  |
| e3 | real_rank_dedup_on | 7 | L193 | 7.0000 ± 0.0000 | 1 |  |
| e3 | mean_reliability_dedup_on | 0.6504 | L194 | 0.5941 ± 0.0000 | 1 | SHIFT > 2 SD |
| e3 | inversion_flag | False | L195 | 0.0000 ± 0.0000 | 1 |  |
| e3 | n_events_used | 2941 | L196 | 2925.0000 ± 0.0000 | 1 | SHIFT > 2 SD |
| e3 | n_outlets | 7 | L197 | 7.0000 ± 0.0000 | 1 |  |
