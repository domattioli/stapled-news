"""Tests for the Fool-the-crowd golden fixture exporter."""

import json
from pathlib import Path

import pytest
import yaml

from stapled.baselines import _batch_ds
from stapled.export import ftc_golden as fg

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def fixture(tmp_path_factory):
    out = tmp_path_factory.mktemp("ftc") / "golden.json"
    fg.write_fixture(out, str(REPO / "configs/synth-baseline.yml"),
                     str(REPO / "results/e1_recovery.csv"))
    return json.loads(out.read_text())


def test_schema_and_case_count(fixture):
    assert fixture["schema"] == 1
    assert len(fixture["cases"]) == 55
    kinds = [c["kind"] for c in fixture["cases"]]
    assert kinds.count("world") == 35 and kinds.count("copy") == 20
    assert [c["m"] for c in fixture["cases"] if c["kind"] == "copy"] == list(range(1, 21))


def test_case_shape(fixture):
    for c in fixture["cases"]:
        for method in ("majority", "batch_ds"):
            exp = c["expected"][method]
            assert set(exp) == {"posteriors", "outlet_params", "rho"}
            assert set(exp["posteriors"]) == {str(e["event_id"]) for e in c["events"]}
            for p in exp["outlet_params"].values():
                assert 0.0 <= p["sens"] <= 1.0 and 0.0 <= p["spec"] <= 1.0


def test_world_rho_matches_e1_csv(fixture):
    worlds = [c for c in fixture["cases"] if "e1_csv_rho" in c]
    assert len(worlds) == 30
    for c in worlds:
        for method, rho in c["e1_csv_rho"].items():
            assert c["expected"][method]["rho"] == pytest.approx(rho, abs=1e-6)


def test_copies_repeat_source_and_are_unplanted(fixture):
    case = next(c for c in fixture["cases"] if c["id"] == "copy-m05")
    src = case["copy_source"]
    n_orig = len(case["planted"])
    for e in case["events"]:
        assert len(e["claims"]) == n_orig + 4
        s = next(c for c in e["claims"] if c["outlet_id"] == src)
        for c in e["claims"][n_orig:]:
            assert (c["observation"], c["certainty"]) == (s["observation"], s["certainty"])
            assert str(c["outlet_id"]) not in case["planted"]


def test_copy_m1_equals_base_world(fixture):
    world = next(c for c in fixture["cases"] if c["id"] == "world-s00")
    copy1 = next(c for c in fixture["cases"] if c["id"] == "copy-m01")
    assert copy1["events"] == world["events"]
    assert copy1["expected"] == world["expected"]


def test_expected_is_reproducible(fixture):
    with open(REPO / "configs/synth-baseline.yml") as f:
        cfg = yaml.safe_load(f)
    events, _ = fg.seeded_world(cfg, 42 + 3)
    res = _batch_ds(events)
    want = next(c for c in fixture["cases"] if c["id"] == "world-s03")["expected"]["batch_ds"]
    for k, v in res["posteriors"].items():
        assert want["posteriors"][str(k)] == pytest.approx(v, abs=1e-12)
