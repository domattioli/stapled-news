"""Minimum-claims (min_obs) cutoff sweep for e3b, e4 (FNN), e4_uci and e6.

Configs are those of scripts/rerun_m1.py (dedup voting on, 10 seeds 42..51), with
min_obs overridden. min_obs is a post-EM scoring filter in all four experiments,
so the EM fit for a given seed is the same at every cutoff; only the outlet set
that is scored changes.

  run:        .venv/bin/python scripts/cutoff_sweep.py run --db-dir ../dbs --work ../sweep_runs
  summarize:  .venv/bin/python scripts/cutoff_sweep.py summarize --work ../sweep_runs

Per-run folders (CSV/PNG/manifest) go to --work and are not committed; summarize
writes results/cutoff_sweep/{sweep.csv,summary.csv,summary.md,rho_vs_min_obs.png,
runs.jsonl,compare_rerun_m1.md}.
"""

import argparse
import csv
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np
from scipy import stats

sys.path.insert(0, str(Path(__file__).resolve().parent))
from rerun_m1 import plan as rerun_plan

EXPS = ["e3b", "e4", "e4_uci", "e6"]
CUTOFFS = [1, 2, 3, 5]
SEEDS = list(range(42, 52))
N_BOOT = 1000
OUT = Path("results/cutoff_sweep")


def _job(name, min_obs, seed, db_dir, work):
    from stapled.experiments.runner import run_experiment

    module, config, _ = rerun_plan(Path(db_dir))[name]
    config = dict(config, min_obs=min_obs)
    out_dir = Path(work) / name / f"min_obs_{min_obs}" / f"seed_{seed}"
    if (out_dir / "manifest.json").exists():
        return name, min_obs, seed, "cached"
    run_experiment(name, module.run, config, seed, out_dir=str(out_dir))
    return name, min_obs, seed, "ok"


def cmd_run(a):
    exps = a.only.split(",") if a.only else EXPS
    jobs = [(e, k, s) for e in exps for k in CUTOFFS for s in SEEDS]
    with ProcessPoolExecutor(max_workers=a.workers) as ex:
        futs = [ex.submit(_job, e, k, s, a.db_dir, a.work) for e, k, s in jobs]
        for f in as_completed(futs):
            print(*f.result(), flush=True)


def _spearman_p(rho, n):
    """Two-sided p for Spearman rho via the t approximation (what scipy.spearmanr uses)."""
    if rho is None or n is None or n < 3:
        return None
    if abs(rho) >= 1:
        return 0.0
    t = rho * math.sqrt((n - 2) / (1 - rho * rho))
    return float(2 * stats.t.sf(abs(t), n - 2))


def _boot_ci_e3b(csv_path, seed):
    """Bootstrap 95% CI over outlets for e3b rho(reliability, 1 - fake_share)."""
    rel, real = [], []
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            rel.append(float(r["reliability"]))
            real.append(1.0 - float(r["fake_share"]))
    rel, real = np.array(rel), np.array(real)
    n = len(rel)
    if n < 3:
        return None, None
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(N_BOOT):
        i = rng.integers(0, n, size=n)
        r, _ = stats.spearmanr(rel[i], real[i])
        if not np.isnan(r):
            boots.append(r)
    return float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5))


def _row(name, min_obs, seed, run_dir):
    m = json.loads((run_dir / "manifest.json").read_text())[-1]
    met = m["metrics"]
    row = {"experiment": name, "min_obs": min_obs, "seed": seed, "db_sha256": m["db_sha256"]}
    if name == "e3b":
        n = met["n_outlets_scored"]
        lo, hi = _boot_ci_e3b(run_dir / "e3b_fnn.csv", seed)
        row.update(rho=met["spearman_rho"], p=met["spearman_pval"], ci_lo=lo, ci_hi=hi,
                   auc=met["auc_mostly_fake"], n_outlets=n, n_events=met["n_events_used"])
    elif name in ("e4", "e4_uci"):
        n = met["n_outlets_joined"]
        row.update(rho=met["spearman_fact"], p=_spearman_p(met["spearman_fact"], n),
                   ci_lo=met.get("spearman_fact_ci_lower"),
                   ci_hi=met.get("spearman_fact_ci_upper"),
                   auc=None, n_outlets=n, n_events=met["n_events_used"],
                   rho_bias_abs=met.get("spearman_bias_abs"))
    else:  # e6: no rank correlation; AUC (reuters vs fake:*) at the largest budget
        abb = met["auc_by_budget"]
        top = max(abb, key=int)
        row.update(rho=None, p=None, ci_lo=None, ci_hi=None, auc=abb[top],
                   n_outlets=met["n_outlets_scored"], n_events=met["n_multi_outlet_events"],
                   auc_by_budget=json.dumps(abb))
    return row, m


def _ms(xs):
    xs = [x for x in xs if x is not None]
    if not xs:
        return None, None
    return float(np.mean(xs)), (float(np.std(xs, ddof=1)) if len(xs) > 1 else 0.0)


def _tci(xs):
    xs = [x for x in xs if x is not None]
    if len(xs) < 2:
        return None, None
    mu, sd = np.mean(xs), np.std(xs, ddof=1)
    h = stats.t.ppf(0.975, len(xs) - 1) * sd / math.sqrt(len(xs))
    return float(mu - h), float(mu + h)


def _f(x, d=4):
    return "—" if x is None else f"{x:.{d}f}"


def summarize(rows):
    out = []
    for e in EXPS:
        prev_n = None
        for k in CUTOFFS:
            rs = [r for r in rows if r["experiment"] == e and r["min_obs"] == k]
            if not rs:
                continue
            rho_m, rho_sd = _ms([r["rho"] for r in rs])
            auc_m, auc_sd = _ms([r["auc"] for r in rs])
            n_m, _ = _ms([r["n_outlets"] for r in rs])
            slo, shi = _tci([r["rho"] for r in rs])
            blo, _ = _ms([r["ci_lo"] for r in rs])
            bhi, _ = _ms([r["ci_hi"] for r in rs])
            n_sig = sum(1 for r in rs if r["p"] is not None and r["p"] < 0.05)
            n_ci_excl = sum(1 for r in rs if r["ci_lo"] is not None
                            and (r["ci_lo"] > 0 or r["ci_hi"] < 0))
            out.append({
                "experiment": e, "min_obs": k, "n_seeds": len(rs),
                "rho_mean": rho_m, "rho_sd": rho_sd,
                "rho_seed_ci_lo": slo, "rho_seed_ci_hi": shi,
                "rho_boot_ci_lo_mean": blo, "rho_boot_ci_hi_mean": bhi,
                "seeds_p_lt_05": n_sig if rho_m is not None else None,
                "seeds_boot_ci_excl_0": n_ci_excl if rho_m is not None else None,
                "auc_mean": auc_m, "auc_sd": auc_sd,
                "n_outlets_mean": n_m,
                "outlets_dropped_vs_prev": (None if prev_n is None else prev_n - n_m),
            })
            prev_n = n_m
    return out


def verdict_e3b(summ):
    s = {r["min_obs"]: r for r in summ if r["experiment"] == "e3b"}
    signs = {k: np.sign(r["rho_mean"]) for k, r in s.items()}
    sign_stable = len(set(signs.values())) == 1

    def excl(r, kind):
        lo, hi = ((r["rho_boot_ci_lo_mean"], r["rho_boot_ci_hi_mean"]) if kind == "boot"
                  else (r["rho_seed_ci_lo"], r["rho_seed_ci_hi"]))
        return lo > 0 or hi < 0

    def sig(r):  # majority of seeds p < 0.05
        return r["seeds_p_lt_05"] > r["n_seeds"] / 2

    res = {}
    for kind in ("boot", "seed"):
        real = sign_stable and all(
            s[k]["rho_mean"] <= -0.15 and excl(s[k], kind) for k in s if k >= 3)
        sig_k = [k for k in s if sig(s[k])]
        artifact = bool(sig_k) and all(k <= 2 for k in sig_k)
        under = all(not excl(s[k], kind) for k in s)
        if real:
            v = "REAL"
        elif artifact:
            v = "FILTER ARTIFACT"
        elif under:
            v = "UNDERPOWERED"
        else:
            v = "NONE OF THE THREE (rule set not exhaustive)"
        res[kind] = {"verdict": v, "sign_stable": sign_stable, "sig_cutoffs": sig_k,
                     "ci_excludes_0": {k: excl(s[k], kind) for k in s}}
    return res


def compare_rerun_m1(rows):
    keymap = {"e3b": [("spearman_rho", "rho"), ("auc_mostly_fake", "auc"),
                      ("n_outlets_scored", "n_outlets")],
              "e4": [("spearman_fact", "rho"), ("n_outlets_joined", "n_outlets")],
              "e4_uci": [("spearman_fact", "rho"), ("n_outlets_joined", "n_outlets")],
              "e6": [("auc_by_budget", "auc_by_budget")]}
    lines, n_mis = [], 0
    for r in rows:
        if r["min_obs"] != 3:
            continue
        p = Path("results/rerun_m1") / r["experiment"] / f"seed_{r['seed']}" / "manifest.json"
        old = json.loads(p.read_text())[-1]
        for ok, nk in keymap[r["experiment"]]:
            ov = old["metrics"].get(ok)
            nv = json.loads(r[nk]) if nk == "auc_by_budget" else r[nk]
            same = (ov == nv) if not isinstance(ov, float) else (
                nv is not None and abs(ov - nv) < 1e-9)
            if not same:
                n_mis += 1
                lines.append(f"| {r['experiment']} | {r['seed']} | {ok} | {ov} | {nv} |")
        if old["db_sha256"] != r["db_sha256"]:
            lines.append(f"| {r['experiment']} | {r['seed']} | db_sha256 | "
                         f"{old['db_sha256'][:12]}… | {r['db_sha256'][:12]}… |")
    return n_mis, lines


def plot(rows, summ, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ink, muted, grid, accent = "#1f2328", "#59636e", "#d0d7de", "#0b6bcb"
    fig, axes = plt.subplots(2, 2, figsize=(10, 7.5), sharex=True)
    titles = {"e3b": "e3b FNN: ρ(reliability, 1 − fake share)",
              "e4": "e4 FNN: ρ(reliability, MBFC fact)",
              "e4_uci": "e4 UCI: ρ(reliability, MBFC fact)",
              "e6": "e6 ISOT: AUC reuters vs fake:* (k=2500)"}
    for ax, e in zip(axes.flat, EXPS):
        s = [r for r in summ if r["experiment"] == e]
        ks = [r["min_obs"] for r in s]
        key = "auc" if e == "e6" else "rho"
        for k in ks:
            ys = [r[key] for r in rows if r["experiment"] == e and r["min_obs"] == k]
            ax.scatter([k] * len(ys), ys, s=10, color=muted, alpha=0.5, zorder=2,
                       linewidths=0)
        if e == "e6":
            mu = [r["auc_mean"] for r in s]
            ax.plot(ks, mu, color=accent, marker="o", lw=2, zorder=3, label="mean over seeds")
            ax.axhline(0.5, color=muted, ls="--", lw=1)
            ax.set_ylim(-0.05, 1.05)
            ax.set_ylabel("AUC")
        else:
            mu = [r["rho_mean"] for r in s]
            lo = [r["rho_boot_ci_lo_mean"] for r in s]
            hi = [r["rho_boot_ci_hi_mean"] for r in s]
            ax.fill_between(ks, lo, hi, color=accent, alpha=0.15, lw=0,
                            label="95% bootstrap CI over outlets (mean of seeds)")
            ax.errorbar(ks, mu, yerr=[np.array(mu) - np.array([r["rho_seed_ci_lo"] for r in s]),
                                      np.array([r["rho_seed_ci_hi"] for r in s]) - np.array(mu)],
                        color=accent, marker="o", lw=2, capsize=3, zorder=3,
                        label="mean ρ ± 95% CI over seeds")
            ax.axhline(0, color=muted, ls="--", lw=1)
            if e == "e3b":
                ax.axhline(-0.15, color="#c4432b", ls=":", lw=1.2, label="REAL threshold −0.15")
            ax.set_ylabel("Spearman ρ")
        for r in s:
            ax.annotate(f"n={r['n_outlets_mean']:.0f}", (r["min_obs"], ax.get_ylim()[0]),
                        xytext=(0, 4), textcoords="offset points", ha="center",
                        fontsize=8, color=muted)
        ax.set_title(titles[e], fontsize=10, color=ink, loc="left")
        ax.set_xticks(CUTOFFS)
        ax.grid(True, color=grid, lw=0.5)
        for sp in ("top", "right"):
            ax.spines[sp].set_visible(False)
        ax.tick_params(colors=muted, labelsize=8)
    for ax in axes[1]:
        ax.set_xlabel("min_obs (minimum hard claims per outlet)")
    axes[0, 0].legend(fontsize=7, frameon=False, loc="upper right")
    fig.suptitle("Outcome vs minimum-claims cutoff (10 seeds; grey = individual seeds)",
                 fontsize=11, color=ink)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def cmd_summarize(a):
    OUT.mkdir(parents=True, exist_ok=True)
    rows, manifests = [], []
    for e in EXPS:
        for k in CUTOFFS:
            for s in SEEDS:
                d = Path(a.work) / e / f"min_obs_{k}" / f"seed_{s}"
                if (d / "manifest.json").exists():
                    r, m = _row(e, k, s, d)
                    rows.append(r)
                    manifests.append(m)
    cols = ["experiment", "min_obs", "seed", "rho", "p", "ci_lo", "ci_hi", "auc", "n_outlets",
            "n_events", "rho_bias_abs", "auc_by_budget", "db_sha256"]
    with open(OUT / "sweep.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({c: ("" if r.get(c) is None else r.get(c)) for c in cols})
    with open(OUT / "runs.jsonl", "w") as f:
        for m in manifests:
            m = {k: v for k, v in m.items() if k != "outputs"}
            f.write(json.dumps(m) + "\n")

    summ = summarize(rows)
    scols = list(summ[0])
    with open(OUT / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=scols)
        w.writeheader()
        for r in summ:
            w.writerow({c: ("" if r[c] is None else r[c]) for c in scols})

    md = [("| exp | min_obs | seeds | ρ mean ± SD | 95% CI over seeds | 95% bootstrap CI "
           "(mean bounds) | seeds p<0.05 | AUC mean ± SD | outlets | dropped vs prev |"),
          "|---|---|---|---|---|---|---|---|---|---|"]
    for r in summ:
        rho = ("—" if r["rho_mean"] is None
               else f"{r['rho_mean']:.4f} ± {r['rho_sd']:.4f}")
        sci = ("—" if r["rho_seed_ci_lo"] is None
               else f"[{r['rho_seed_ci_lo']:.4f}, {r['rho_seed_ci_hi']:.4f}]")
        bci = ("—" if r["rho_boot_ci_lo_mean"] is None
               else f"[{r['rho_boot_ci_lo_mean']:.3f}, {r['rho_boot_ci_hi_mean']:.3f}]")
        auc = "—" if r["auc_mean"] is None else f"{r['auc_mean']:.4f} ± {r['auc_sd']:.4f}"
        sig = "—" if r["seeds_p_lt_05"] is None else f"{r['seeds_p_lt_05']}/{r['n_seeds']}"
        drop = "—" if r["outlets_dropped_vs_prev"] is None else f"{r['outlets_dropped_vs_prev']:.0f}"
        md.append(f"| {r['experiment']} | {r['min_obs']} | {r['n_seeds']} | {rho} | {sci} | "
                  f"{bci} | {sig} | {auc} | {r['n_outlets_mean']:.0f} | {drop} |")
    (OUT / "summary.md").write_text("\n".join(md) + "\n")

    v = verdict_e3b(summ) if any(r["experiment"] == "e3b" for r in summ) else None
    (OUT / "verdict_e3b.json").write_text(json.dumps(v, indent=2, default=str) + "\n")

    n_mis, lines = compare_rerun_m1(rows)
    cmp_md = ["# min_obs=3 cells vs results/rerun_m1 (per seed)\n",
              f"Metric mismatches: {n_mis}\n",
              "| exp | seed | field | rerun_m1 | sweep |", "|---|---|---|---|---|"] + lines
    (OUT / "compare_rerun_m1.md").write_text("\n".join(cmp_md) + "\n")

    plot(rows, summ, OUT / "rho_vs_min_obs.png")
    print("\n".join(md))
    print(json.dumps(v, indent=2, default=str))
    print(f"rerun_m1 metric mismatches at min_obs=3: {n_mis}")
    print("\n".join(lines[:40]))


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--db-dir", required=True)
    r.add_argument("--work", required=True)
    r.add_argument("--only", default=None)
    r.add_argument("--workers", type=int, default=4)
    s = sub.add_parser("summarize")
    s.add_argument("--work", required=True)
    a = ap.parse_args()
    cmd_run(a) if a.cmd == "run" else cmd_summarize(a)


if __name__ == "__main__":
    main()
