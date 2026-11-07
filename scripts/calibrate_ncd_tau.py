"""Calibrate the NCD dedup threshold tau on E2 perturbed syndication copies.

Per seed: build an E2 synthetic corpus (stapled.synth.generator.generate),
replace article bodies with long, topic-structured documents of varied length
(E2's own template bodies are ~110 bytes, below the 200-byte NCD floor), inject
perturbed copies of the wire outlet with e2_syndication._inject_syndication
(5% word edits via _perturb_text), then score pairs.

Positives: all pairs inside one syndication group (original + its copies).
Negatives: MinHash-blocked pairs across groups; if blocking yields fewer than
--min-neg, random cross-group pairs pad the set (counts are reported).

Usage: .venv/bin/python scripts/calibrate_ncd_tau.py --seeds 10
"""

import argparse
import json
import platform
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import yaml

from stapled.db import connect
from stapled.experiments import e2_syndication as e2
from stapled.ingest import ncd_dedup as nd
from stapled.ingest.dedup import _hamming_distance, _normalize_text, _simhash
from stapled.synth.generator import generate

TAUS = np.round(np.arange(0.20, 0.7001, 0.01), 2)
BINS = [("<200", 0, 200), ("200-1000", 200, 1000), (">1000", 1000, 10**9)]
FPR_CAP = 0.01
N_EVENTS = 80
MULTIPLICITY = 5
N_TOPICS = 8


def _vocab(rng, size=3000):
    syl = ["ka", "to", "ri", "mel", "san", "dor", "vi", "pen", "lu", "gar", "no", "bel", "tis", "ex", "ha"]
    words = set()
    while len(words) < size:
        words.add("".join(rng.choice(syl, size=int(rng.integers(2, 5)))))
    return sorted(words)


def _long_doc(rng, vocab, topics, n_words):
    topic = topics[int(rng.integers(0, len(topics)))]
    out = []
    for _ in range(n_words):
        if rng.random() < 0.7:
            out.append(topic[int(rng.integers(0, len(topic)))])
        else:
            out.append(vocab[min(int(rng.zipf(1.3)) - 1, len(vocab) - 1)])
    return " ".join(out).capitalize() + "."


def build_corpus(seed, synth_config):
    """Return (db_path, conn, docs) with docs=[(id, group, body)]."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = tmp.name
    conn = connect(db_path)
    cfg = dict(synth_config, n_events=N_EVENTS)
    corpus_id = generate(conn, cfg, seed=seed)
    rng = np.random.default_rng(seed + 7)
    vocab = _vocab(np.random.default_rng(12345))
    topics = [list(rng.choice(vocab, size=300, replace=False)) for _ in range(N_TOPICS)]
    for (aid,) in conn.execute("SELECT id FROM article ORDER BY id").fetchall():
        n_words = int(np.exp(rng.uniform(np.log(12), np.log(400))))  # ~80B .. ~2.5KB
        conn.execute("UPDATE article SET body = ? WHERE id = ?",
                     (_long_doc(rng, vocab, topics, n_words), aid))
    conn.commit()
    planted = dict(conn.execute(
        "SELECT outlet_id, reliability FROM outlet_truth WHERE corpus_id = ?", (corpus_id,)))
    wire = min(planted, key=lambda o: planted[o])
    others = [r[0] for r in conn.execute(
        "SELECT id FROM outlet WHERE is_synthetic = 1 ORDER BY id") if r[0] != wire]
    e2._inject_syndication(conn, wire, others, MULTIPLICITY, "perturbed",
                           np.random.default_rng(seed + 1000))
    docs = [(i, u.split("?dup=")[0], b) for i, u, b in conn.execute(
        "SELECT id, url, body FROM article ORDER BY id")]
    return db_path, conn, docs


def score_pairs(docs, seed, min_neg, compressor, level):
    rng = np.random.default_rng(seed + 99)
    bodies = [d[2] for d in docs]
    norm = [_normalize_text(b).encode() for b in bodies]
    group = [d[1] for d in docs]
    cand = nd.candidate_pairs(bodies)
    cand_set = set(cand)
    by_group = {}
    for i, g in enumerate(group):
        by_group.setdefault(g, []).append(i)
    pos = [(a, b) for m in by_group.values() for k, a in enumerate(m) for b in m[k + 1:]]
    neg_blocked = [p for p in cand if group[p[0]] != group[p[1]]]
    neg = list(neg_blocked)
    n_random = 0
    seen = set(neg)
    while len(neg) < min_neg:
        i, j = sorted(rng.choice(len(docs), size=2, replace=False).tolist())
        if group[i] != group[j] and (i, j) not in seen:
            seen.add((i, j))
            neg.append((i, j))
            n_random += 1
    cache = [nd._clen(x, compressor, level) for x in norm]
    sh = [_simhash(b) for b in bodies]

    def row(p, label):
        i, j = p
        return (label, min(len(norm[i]), len(norm[j])),
                nd.ncd(norm[i], norm[j], compressor=compressor, level=level,
                       ca=cache[i], cb=cache[j]),
                _hamming_distance(sh[i], sh[j]) <= 6)

    t0 = time.perf_counter()
    rows = [row(p, 1) for p in pos] + [row(p, 0) for p in neg]
    ncd_time = time.perf_counter() - t0
    return {
        "rows": rows,
        "n_pos": len(pos),
        "n_neg": len(neg),
        "n_neg_blocked": len(neg_blocked),
        "n_neg_random": n_random,
        "blocking_recall": sum(p in cand_set for p in pos) / max(1, len(pos)),
        "ncd_time": ncd_time,
    }


def _rates(label, d, flag):
    pos = label == 1
    tp = int((flag & pos).sum())
    fp = int((flag & ~pos).sum())
    return (tp / max(1, int(pos.sum())), fp / max(1, int((~pos).sum())),
            int(pos.sum()), int((~pos).sum()))


def pick_tau(label, length, d):
    """Max-recall tau with FPR <= 1% over NCD-eligible pairs (min len >= 200)."""
    m = length >= 200
    best = None
    for tau in TAUS:
        rec, fpr, _, _ = _rates(label[m], d[m], d[m] <= tau)
        if fpr <= FPR_CAP and (best is None or rec > best[1]):
            best = (float(tau), rec, fpr)
    return best


def report(label, length, d, hd, tau):
    out = {}
    for name, lo, hi in BINS:
        m = (length >= lo) & (length < hi)
        if not m.any():
            continue
        rec, fpr, np_, nn = _rates(label[m], d[m], d[m] <= tau)
        brec, bfpr, _, _ = _rates(label[m], d[m], hd[m])
        out[name] = {"n_pos": np_, "n_neg": nn, "ncd_recall": rec, "ncd_fpr": fpr,
                     "simhash_recall": brec, "simhash_fpr": bfpr}
    m = length >= 200
    rec, fpr, np_, nn = _rates(label[m], d[m], d[m] <= tau)
    brec, bfpr, _, _ = _rates(label[m], d[m], hd[m])
    out["eligible(>=200)"] = {"n_pos": np_, "n_neg": nn, "ncd_recall": rec, "ncd_fpr": fpr,
                              "simhash_recall": brec, "simhash_fpr": bfpr}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=10)
    ap.add_argument("--synth-config", default="configs/synth-baseline.yml")
    ap.add_argument("--out", default="results/ncd_calibration.json")
    ap.add_argument("--min-neg", type=int, default=2000)
    ap.add_argument("--compressor", default="zstd")
    ap.add_argument("--level", type=int, default=3)
    a = ap.parse_args()

    synth_config = yaml.safe_load(open(a.synth_config))
    per_seed, all_rows = [], []
    runtimes, n_docs, ncd_time, ncd_pairs = [], [], 0.0, 0
    tot = {"n_neg_blocked": 0, "n_neg_random": 0}
    block_rec = []
    for s in range(a.seeds):
        db_path, conn, docs = build_corpus(s, synth_config)
        sc = score_pairs(docs, s, a.min_neg, a.compressor, a.level)
        rows = np.array(sc["rows"], dtype=float)
        pk = pick_tau(rows[:, 0], rows[:, 1], rows[:, 2])
        per_seed.append(pk[0] if pk else None)
        all_rows.append(rows)
        ncd_time += sc["ncd_time"]
        ncd_pairs += len(rows)
        tot["n_neg_blocked"] += sc["n_neg_blocked"]
        tot["n_neg_random"] += sc["n_neg_random"]
        block_rec.append(sc["blocking_recall"])
        t0 = time.perf_counter()
        nd.ncd_dedup(conn, compressor=a.compressor, level=a.level)
        runtimes.append(time.perf_counter() - t0)
        n_docs.append(len(docs))
        conn.close()
        Path(db_path).unlink(missing_ok=True)

    rows = np.vstack(all_rows)
    label, length, d, hd = rows[:, 0], rows[:, 1], rows[:, 2], rows[:, 3].astype(bool)
    pooled = pick_tau(label, length, d)
    tau = round(pooled[0], 2)
    valid = [t for t in per_seed if t is not None]
    result = {
        "tau": tau,
        "tau_per_seed": per_seed,
        "tau_seed_mean": float(np.mean(valid)),
        "tau_seed_sd": float(np.std(valid, ddof=1)) if len(valid) > 1 else 0.0,
        "fpr": pooled[2],
        "recall": pooled[1],
        "fpr_cap": FPR_CAP,
        "per_bin": report(label, length, d, hd, tau),
        "baseline": "simhash Hamming<=6 on the same pairs (per-bin simhash_* fields)",
        "blocking_recall_mean": float(np.mean(block_rec)),
        "negatives": tot,
        "runtime_s": float(np.mean(runtimes)),
        "runtime_s_per_seed": runtimes,
        "us_per_pair": ncd_time / ncd_pairs * 1e6,
        "n_docs": int(np.mean(n_docs)),
        "n_pairs": int(ncd_pairs),
        "n_seeds": a.seeds,
        "compressor": nd.compressor_used(a.compressor),
        "level": a.level,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "corpus_note": ("E2 generator + injection; bodies replaced with synthetic topic-structured "
                        "long docs because E2 template bodies are <200 bytes. Zipf pseudo-words, "
                        "not real news text; random negatives are easier than real distinct "
                        "stories, so tau is optimistic."),
    }
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(result, indent=2) + "\n")
    print(f"tau pooled={tau}  seed mean={result['tau_seed_mean']:.3f} "
          f"sd={result['tau_seed_sd']:.3f}  recall={pooled[1]:.4f}  fpr={pooled[2]:.4f}")
    for k, v in result["per_bin"].items():
        print(f"  {k:16s} NCD rec={v['ncd_recall']:.3f} fpr={v['ncd_fpr']:.3f} | "
              f"simhash rec={v['simhash_recall']:.3f} fpr={v['simhash_fpr']:.3f} "
              f"(pos={v['n_pos']} neg={v['n_neg']})")
    print(f"  negatives {tot}  blocking_recall={result['blocking_recall_mean']:.3f}")
    print(f"  runtime_s={result['runtime_s']:.3f} us_per_pair={result['us_per_pair']:.1f} "
          f"n_docs={result['n_docs']} n_pairs={ncd_pairs} compressor={result['compressor']}")


if __name__ == "__main__":
    main()
