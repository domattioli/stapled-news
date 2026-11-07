"""Build results/rerun_m1/COMPARE.md: committed manifest values vs. the 10-seed rerun.

Old value = the last entry for the experiment in results/manifest.json, cited by the
line number of the metric key. New = mean +- SD (ddof=1) over seeds. Flags: sign flip
of the mean, and significance change (e3b: p < 0.05 per seed; e4/e4_uci: bootstrap
95% CI excluding 0 per seed; reported as the share of seeds that are significant).
"""

import csv
import json
from pathlib import Path

import numpy as np

OLD = Path("results/manifest.json")
NEW = Path("results/rerun_m1")


def old_entries():
    lines = OLD.read_text().splitlines()
    data = json.loads(OLD.read_text())
    starts = [i + 1 for i, ln in enumerate(lines) if ln.strip().startswith('"experiment":')]
    last = {}
    for entry, start in zip(data, starts):
        last[entry["experiment"]] = (entry, start)
    return lines, last


def find_line(lines, start, path):
    """1-based line of the nested key path, searching forward from the entry start."""
    i = start - 1
    for key in path:
        while i < len(lines) and not lines[i].strip().startswith(f'"{key}":'):
            i += 1
    return i + 1 if i < len(lines) else None


def new_entries(name):
    out = []
    for p in sorted((NEW / name).glob("**/manifest.json")):
        out.extend(json.loads(p.read_text()))
    return out


def get(d, path):
    for k in path:
        d = d[k]
    return d


def fmt(x):
    return "—" if x is None else f"{x:.4f}" if isinstance(x, float) else str(x)


def mean_sd(vals):
    a = np.asarray(vals, dtype=float)
    sd = float(a.std(ddof=1)) if len(a) > 1 else 0.0
    return float(a.mean()), sd


def sign(x):
    return 0 if abs(x) < 1e-12 else (1 if x > 0 else -1)


def main():
    lines, last = old_entries()
    rows = []

    def add(exp, label, path, new_vals, old_exp=None, sig=None, old_path=None):
        old_exp = old_exp or exp
        old_val, line = None, None
        if old_exp in last:
            entry, start = last[old_exp]
            try:
                old_val = get(entry["metrics"], old_path or path)
                line = find_line(lines, start, ["metrics", *(old_path or path)])
            except (KeyError, TypeError):
                pass
        m, sd = mean_sd(new_vals)
        flags = []
        if isinstance(old_val, (int, float)) and not isinstance(old_val, bool):
            if sign(old_val) * sign(m) < 0:
                flags.append("SIGN FLIP")
            if abs(m - old_val) > 0.05 and abs(m - old_val) > 2 * sd:
                flags.append("SHIFT > 2 SD")
        if sig:
            flags.append(sig)
        rows.append((exp, label, fmt(old_val), f"L{line}" if line else "—",
                     f"{m:.4f} ± {sd:.4f}", len(new_vals), "; ".join(flags)))

    # e3b, e4, e4_uci: scalar metrics per seed
    for exp, keys in (
        ("e3b", ["spearman_rho", "spearman_pval", "auc_mostly_fake", "n_outlets_scored",
                 "n_events_used"]),
        ("e4", ["spearman_fact", "spearman_bias_abs", "n_outlets_joined", "n_events_used"]),
        ("e4_uci", ["spearman_fact", "spearman_bias_abs", "n_outlets_joined", "n_events_used"]),
    ):
        ents = new_entries(exp)
        if not ents:
            continue
        old = last.get(exp, ({}, 0))[0].get("metrics", {})
        for k in keys:
            sig = None
            if exp == "e3b" and k == "spearman_rho":
                n_sig = sum(e["metrics"]["spearman_pval"] < 0.05 for e in ents)
                was = old.get("spearman_pval", 1) < 0.05
                now = n_sig > len(ents) / 2
                sig = f"p<0.05 in {n_sig}/{len(ents)} seeds (old: {'sig' if was else 'n.s.'})"
                if was != now:
                    sig = "SIGNIFICANCE CHANGE: " + sig
            if exp in ("e4", "e4_uci") and k in ("spearman_fact", "spearman_bias_abs"):
                lo, hi = f"{k}_ci_lower", f"{k}_ci_upper"
                n_sig = sum(e["metrics"][lo] > 0 or e["metrics"][hi] < 0 for e in ents)
                was = (old.get(lo, 0) > 0 or old.get(hi, 0) < 0) if lo in old else None
                now = n_sig > len(ents) / 2
                sig = (f"95% CI excludes 0 in {n_sig}/{len(ents)} seeds "
                       f"(old: {'yes' if was else 'no' if was is not None else '—'})")
                if was is not None and was != now:
                    sig = "SIGNIFICANCE CHANGE: " + sig
            add(exp, k, [k], [e["metrics"][k] for e in ents], sig=sig)

    # e2: per-seed rho from the CSV (inner seeds), simhash and ncd arms
    for exp in ("e2", "e2_ncd"):
        csvs = list((NEW / exp).glob("**/e2_syndication.csv"))
        if not csvs:
            continue
        with open(csvs[0]) as f:
            data = list(csv.DictReader(f))
        for mode in ("exact", "perturbed"):
            for dd in ("True", "False"):
                for m in ("1", "2", "5", "10", "20"):
                    vals = [float(r["rho"]) for r in data
                            if r["mode"] == mode and r["dedup"] == dd and r["multiplicity"] == m]
                    key = "dedup_on" if dd == "True" else "dedup_off"
                    old_path = ["mean_rho_by_m", key, m] if mode == "exact" else ["__none__"]
                    add(exp, f"{mode} {key} m={m}", old_path, vals, old_exp="e2",
                        old_path=old_path)
            on = {r["seed"]: float(r["rho"]) for r in data
                  if r["mode"] == mode and r["dedup"] == "True" and r["multiplicity"] == "20"}
            off = {r["seed"]: float(r["rho"]) for r in data
                   if r["mode"] == mode and r["dedup"] == "False" and r["multiplicity"] == "20"}
            add(exp, f"{mode} distortion_at_max_m",
                ["distortion_at_max_m"] if mode == "exact" else ["__none__"],
                [off[s] - on[s] for s in on], old_exp="e2")

    # e6: AUC by budget over outer seeds
    ents = new_entries("e6")
    if ents:
        for b in sorted(ents[0]["metrics"]["auc_by_budget"], key=int):
            add("e6", f"auc_by_budget[{b}]", ["auc_by_budget", b],
                [e["metrics"]["auc_by_budget"][b] for e in ents])
        mins = [e["metrics"]["min_budget_full_recovery"] for e in ents]
        rows.append(("e6", "min_budget_full_recovery",
                     fmt(last["e6"][0]["metrics"].get("min_budget_full_recovery")),
                     f"L{find_line(lines, last['e6'][1], ['metrics', 'min_budget_full_recovery'])}",
                     ", ".join(str(x) for x in mins), len(mins), ""))
        add("e6", "n_multi_outlet_events", ["n_multi_outlet_events"],
            [e["metrics"]["n_multi_outlet_events"] for e in ents])

    # e3: refreshed once
    ents = new_entries("e3")
    if ents:
        for k in ("auc_dedup_on", "auc_dedup_off", "real_rank_dedup_on",
                  "mean_reliability_dedup_on", "inversion_flag", "n_events_used", "n_outlets"):
            vals = [float(e["metrics"][k]) for e in ents]
            add("e3", k, [k], vals)

    out = ["# Rerun M1 vs committed results", "",
           ("Old = last entry per experiment in `results/manifest.json` (line of the metric key). "
            "New = mean ± SD (ddof=1) over seeds; `n` = seed count. "
            "See `README.md` in this folder for DBs, configs and caveats."), "",
           "| exp | metric | old | manifest line | new mean ± SD | n | flags |",
           "|---|---|---|---|---|---|---|"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    (NEW / "COMPARE.md").write_text("\n".join(out) + "\n")
    print("\n".join(out))


if __name__ == "__main__":
    main()
