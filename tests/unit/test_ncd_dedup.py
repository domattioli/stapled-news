"""Unit tests for NCD near-duplicate detection."""

import numpy as np
import pytest

from stapled.db import connect
from stapled.experiments import e2_syndication
from stapled.experiments.e2_syndication import _perturb_text
from stapled.experiments.runner import run_experiment
from stapled.ingest import ncd_dedup as nd
from stapled.ingest.ncd_dedup import candidate_pairs, ncd, ncd_dedup


def _words(seed, n):
    rng = np.random.default_rng(seed)
    syl = ["ka", "to", "ri", "mel", "san", "dor", "vi", "pen", "lu", "gar"]
    vocab = ["".join(rng.choice(syl, size=3)) + str(k) for k in range(400)]
    return " ".join(vocab[int(i)] for i in rng.integers(0, 400, size=n))


def _db(tmp_path, bodies):
    conn = connect(str(tmp_path / "t.db"))
    conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('o', 1)")
    conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (1, '{}', 'pending')")
    for k, body in enumerate(bodies):
        conn.execute(
            "INSERT INTO article (outlet_id, corpus_id, url, title, body, published_at, ingest_status) "
            "VALUES (1, 1, ?, 't', ?, '2024-01-01', 'ok')",
            (f"u{k}", body),
        )
    conn.commit()
    return conn


def _clusters(conn):
    return [r[0] for r in conn.execute("SELECT dedup_cluster_id FROM article ORDER BY id")]


def test_identical_texts_ncd_near_zero():
    t = _words(1, 200).encode()
    assert ncd(t, t) < 0.1


def test_unrelated_long_texts_above_tau():
    a, b = _words(1, 200).encode(), _words(2, 200).encode()
    assert ncd(a, b) > nd.TAU_DEFAULT


def test_perturbed_copy_clusters(tmp_path):
    base = _words(3, 120)
    assert len(base.encode()) >= 200
    copy = _perturb_text(base, np.random.default_rng(0))
    conn = _db(tmp_path, [base, copy, _words(4, 120)])
    assert ncd_dedup(conn) == 1
    ids = _clusters(conn)
    assert ids[0] is not None and ids[0] == ids[1] and ids[2] is None


def test_short_texts_use_simhash_path(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("NCD must not run for short texts")

    monkeypatch.setattr(nd, "_clen", boom)
    short = "Officials confirmed that the matter occurred in the city today."
    assert len(short) < 200
    conn = _db(tmp_path, [short, short, "Totally different words appear here for contrast only now ok"])
    assert ncd_dedup(conn) == 1
    ids = _clusters(conn)
    assert ids[0] == ids[1] and ids[2] is None


def test_cluster_ids_do_not_collide(tmp_path):
    base = _words(5, 120)
    conn = _db(tmp_path, [base, base, _words(6, 120), _words(6, 120)])
    conn.execute("UPDATE article SET dedup_cluster_id = 7 WHERE id IN (1, 2)")
    conn.commit()
    assert ncd_dedup(conn) == 1
    ids = _clusters(conn)
    assert ids[:2] == [7, 7]
    assert ids[2] == ids[3] and ids[2] > 7


def test_minhash_candidates_deterministic():
    texts = [_words(7, 100), _words(7, 100) + " extra", _words(8, 100)]
    p1, p2 = candidate_pairs(texts), candidate_pairs(texts)
    assert p1 == p2 and (0, 1) in p1


def test_band_geometry_checked():
    with pytest.raises(ValueError):
        candidate_pairs(["a b c d e f"], num_perm=128, bands=30, rows=4)


def test_entity_blocker_not_implemented(tmp_path):
    with pytest.raises(NotImplementedError):
        ncd_dedup(_db(tmp_path, ["a", "b"]), blocker="entity")


def test_e2_ncd_arm_runs(tmp_path):
    synth = tmp_path / "synth.yml"
    synth.write_text(
        "outlets:\n"
        "  - {name: reliable, reliability: 0.9, bias: 0.0, calibration: 1.0}\n"
        "  - {name: moderate, reliability: 0.7, bias: 0.0, calibration: 1.0}\n"
        "  - {name: unreliable, reliability: 0.2, bias: 0.0, calibration: 1.0}\n"
        "n_events: 8\narticles_per_event_per_outlet: 1\n"
    )
    config = {"quick": True, "synth_config_path": str(synth), "perturb": False,
              "dedup_method": "ncd"}
    out = tmp_path / "out"
    run_experiment("e2", e2_syndication.run, config, seed=42, out_dir=str(out))
    assert len((out / "e2_syndication.csv").read_text().splitlines()) == 13
