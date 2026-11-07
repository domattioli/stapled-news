"""Omission test: does the E5 omission score recover an outlet's main UCI topic?

For each outlet, predict its main topic as the category (b, t, e, m) with the lowest
omission score (omission = 1 - coverage_rate, the E5 definition: share of the
well-corroborated events of that category in which the outlet has an article).
Truth = category with the largest share of the outlet's articles.

Held-out design (not circular): per seed, each outlet's articles are split 50/50
at random. Omission is computed from half A only (audit events = events with
>= min_outlets distinct outlets in half A; event category = majority article label
in half A; coverage from half A). Truth comes from half B. Baseline = argmax of the
outlet's raw half-A article counts per category, scored against the same half-B truth.

Usage: .venv/bin/python scripts/omission_test.py --db ../dbs/uci.db
Writes results/omission_test/{per_seed.csv,predictions_seed42.csv,spearman.csv,
summary.json,REPORT_SECTION.md,e5_logic_check.json}.
"""

import argparse
import csv
import json
import sqlite3
from pathlib import Path

import numpy as np
from scipy.stats import spearmanr

from stapled.experiments import e5_omission

CATS = e5_omission.CATEGORY_KEYS  # ["uci_b", "uci_t", "uci_e", "uci_m"]
SEEDS = list(range(42, 52))
TOPS = (30, 100)
OUT = Path("results/omission_test")


def load(db):
    conn = sqlite3.connect(db)
    rows = conn.execute(
        "SELECT a.id, a.outlet_id, c.event_id, l.dataset FROM article a "
        "JOIN claim c ON c.article_id = a.id "
        "JOIN article_label l ON l.article_id = a.id "
        "WHERE c.event_id IS NOT NULL AND l.dataset IN ('uci_b','uci_t','uci_e','uci_m') "
        "ORDER BY a.id"
    ).fetchall()
    names = dict(conn.execute("SELECT id, name FROM outlet").fetchall())
    conn.close()
    art, outl, ev, cat = (np.array(x) for x in zip(*rows))
    cat = np.array([CATS.index(c) for c in cat])
    return art, outl, ev, cat, names


def omission_matrix(outl, ev, cat, min_outlets):
    """E5 coverage logic, vectorised. Returns {outlet_id: np.array(4) omission}."""
    # Distinct (outlet, event) pairs
    pairs = np.unique(np.stack([ev, outl], 1), axis=0)
    ev_u, n_out = np.unique(pairs[:, 0], return_counts=True)
    audit = set(ev_u[n_out >= min_outlets].tolist())
    # Event category = majority label among the event's articles (ties: E5's max() picks
    # the first-seen label; here ties go to the lowest CATS index, which is deterministic)
    votes = {}
    for e, c in zip(ev.tolist(), cat.tolist()):
        if e in audit:
            v = votes.setdefault(e, [0, 0, 0, 0])
            v[c] += 1
    ecat = {e: int(np.argmax(v)) for e, v in votes.items()}
    denom = np.zeros(4)
    for c in ecat.values():
        denom[c] += 1
    cov = {}
    for e, o in pairs.tolist():
        if e in ecat:
            cov.setdefault(o, np.zeros(4))[ecat[e]] += 1
    out = {}
    for o in np.unique(outl).tolist():
        c = cov.get(o, np.zeros(4))
        rate = np.divide(c, denom, out=np.zeros(4), where=denom > 0)
        out[o] = 1.0 - rate
    return out, denom, ecat


def counts_by_cat(outl, cat):
    out = {}
    for o, c in zip(outl.tolist(), cat.tolist()):
        out.setdefault(o, np.zeros(4))[c] += 1
    return out


def split_half(outl, rng):
    """Per-outlet 50/50 split of articles. Returns boolean mask for half A."""
    mask = np.zeros(len(outl), bool)
    order = np.argsort(outl, kind="stable")
    so = outl[order]
    starts = np.r_[0, np.flatnonzero(np.diff(so)) + 1]
    ends = np.r_[starts[1:], len(so)]
    for s, e in zip(starts, ends):
        idx = order[s:e]
        perm = rng.permutation(len(idx))
        mask[idx[perm[: len(idx) // 2 + (rng.random() < 0.5 if len(idx) % 2 else 0)]]] = True
    return mask


def e5_logic_check(db, min_outlets):
    """Check the vectorised omission matrix against E5's own _compute_coverage_matrix."""
    conn = sqlite3.connect(db)
    outlet_ids = [r[0] for r in conn.execute("SELECT id FROM outlet ORDER BY id")]
    event_ids = [r[0] for r in conn.execute(
        "SELECT c.event_id FROM claim c JOIN article a ON c.article_id = a.id "
        "WHERE c.event_id IS NOT NULL GROUP BY c.event_id "
        "HAVING COUNT(DISTINCT a.outlet_id) >= ? ORDER BY c.event_id", (min_outlets,))]
    ref = e5_omission._compute_coverage_matrix(conn, outlet_ids, None, event_ids, min_outlets)
    act = e5_omission._compute_outlet_activity(conn, outlet_ids, None, event_ids)
    conn.close()
    return ref, act, event_ids


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--min-outlets", type=int, default=3)
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)

    _art, outl, ev, cat, names = load(a.db)
    total = counts_by_cat(outl, cat)
    ranked = sorted(total, key=lambda o: (-total[o].sum(), names[o]))
    tops = {n: ranked[:n] for n in TOPS}

    # --- E5 logic check (full data, no split) ---
    full_om, full_denom, _ = omission_matrix(outl, ev, cat, a.min_outlets)
    ref, _act, audit_events = e5_logic_check(a.db, a.min_outlets)
    max_diff = max(abs((1 - ref[(o, c)]["coverage_rate"]) - full_om[o][i])
                   for o in full_om for i, c in enumerate(CATS))
    # Committed results/e5_omission.csv: argmin omission vs full-data article-share truth
    committed = {}
    with open("results/e5_omission.csv") as f:
        for r in csv.DictReader(f):
            committed.setdefault(r["outlet"], {})[r["category"]] = float(r["omission_score"])
    id_by_name = {v: k for k, v in names.items()}
    c_hits, c_n = 0, 0
    for name, d in committed.items():
        o = id_by_name.get(name)
        if o is None or o not in total:
            continue
        pred = min(CATS, key=lambda c: (d[c], CATS.index(c)))
        c_hits += int(CATS.index(pred) == int(np.argmax(total[o])))
        c_n += 1
    # In-sample (circular) accuracy on full data, for reference
    insample = {n: float(np.mean([int(np.argmin(full_om[o]) == np.argmax(total[o]))
                                  for o in tops[n]])) for n in TOPS}
    check = {"max_abs_diff_vs_e5_compute_coverage_matrix": max_diff,
             "n_audit_events_full": len(audit_events),
             "audit_events_per_category_full": dict(zip(CATS, full_denom.tolist())),
             "committed_e5_csv_outlets_matched": c_n,
             "committed_e5_csv_argmin_accuracy_vs_full_share": (c_hits / c_n) if c_n else None,
             "insample_accuracy_full_data": insample}
    (OUT / "e5_logic_check.json").write_text(json.dumps(check, indent=2) + "\n")

    # --- Held-out test ---
    per_seed, sp_rows = [], []
    for seed in SEEDS:
        rng = np.random.default_rng(seed)
        A = split_half(outl, rng)
        om, denom, _ = omission_matrix(outl[A], ev[A], cat[A], a.min_outlets)
        cntA = counts_by_cat(outl[A], cat[A])
        cntB = counts_by_cat(outl[~A], cat[~A])
        rec = {"seed": seed, "n_audit_events_A": int(denom.sum())}
        for n in TOPS:
            ids = tops[n]
            truth = [int(np.argmax(cntB.get(o, np.zeros(4)))) for o in ids]
            pred = [int(np.argmin(om.get(o, np.ones(4)))) for o in ids]
            base = [int(np.argmax(cntA.get(o, np.zeros(4)))) for o in ids]
            rec[f"acc_top{n}"] = float(np.mean(np.equal(pred, truth)))
            rec[f"baseline_top{n}"] = float(np.mean(np.equal(base, truth)))
            for ci, c in enumerate(CATS):
                x = [om.get(o, np.ones(4))[ci] for o in ids]
                y = [cntB[o][ci] / cntB[o].sum() if o in cntB and cntB[o].sum() else 0.0
                     for o in ids]
                r, p = spearmanr(x, y)
                sp_rows.append({"seed": seed, "top": n, "category": c, "rho": float(r),
                                "p": float(p)})
            if seed == SEEDS[0] and n == 100:
                with open(OUT / "predictions_seed42.csv", "w", newline="") as f:
                    w = csv.writer(f)
                    w.writerow(["rank", "outlet", "n_articles", "truth_B", "pred_omission_A",
                                "pred_baseline_A"] + [f"omission_A_{c}" for c in CATS]
                               + [f"share_B_{c}" for c in CATS])
                    for i, o in enumerate(ids):
                        sb = cntB[o] / cntB[o].sum()
                        w.writerow([i + 1, names[o], int(total[o].sum()), CATS[truth[i]],
                                    CATS[pred[i]], CATS[base[i]]]
                                   + [f"{v:.6f}" for v in om.get(o, np.ones(4))]
                                   + [f"{v:.6f}" for v in sb])
        per_seed.append(rec)

    with open(OUT / "per_seed.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(per_seed[0]))
        w.writeheader()
        w.writerows(per_seed)
    with open(OUT / "spearman.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["seed", "top", "category", "rho", "p"])
        w.writeheader()
        w.writerows(sp_rows)

    def ms(xs):
        return float(np.mean(xs)), float(np.std(xs, ddof=1))

    summ = {"chance": 0.25, "n_seeds": len(SEEDS), "min_outlets": a.min_outlets}
    for n in TOPS:
        summ[f"acc_top{n}"] = ms([r[f"acc_top{n}"] for r in per_seed])
        summ[f"baseline_top{n}"] = ms([r[f"baseline_top{n}"] for r in per_seed])
        summ[f"spearman_top{n}"] = {
            c: ms([r["rho"] for r in sp_rows if r["top"] == n and r["category"] == c])
            for c in CATS}
        summ[f"truth_dist_top{n}_full"] = {
            c: sum(1 for o in tops[n] if int(np.argmax(total[o])) == i)
            for i, c in enumerate(CATS)}
    acc, base = summ["acc_top100"][0], summ["baseline_top100"][0]
    rho_ok = {c: abs(summ["spearman_top100"][c][0]) >= 0.6 for c in CATS}
    crit = {"top100_acc_ge_0.80": acc >= 0.80, "beats_baseline_by_ge_0.05": acc - base >= 0.05,
            "abs_rho_ge_0.6_all_4": all(rho_ok.values()), "abs_rho_ge_0.6_by_cat": rho_ok}
    summ["criteria"] = crit
    summ["verdict"] = "PASS" if (crit["top100_acc_ge_0.80"] and crit["beats_baseline_by_ge_0.05"]
                                 and crit["abs_rho_ge_0.6_all_4"]) else "FAIL"
    summ["e5_logic_check"] = check
    (OUT / "summary.json").write_text(json.dumps(summ, indent=2) + "\n")
    print(json.dumps(summ, indent=2))


if __name__ == "__main__":
    main()
