from stapled.analyze.atomic_run import AtomicRun, canonical_json, semantic_hash, stable_scu_id


def test_canonical_json_is_order_stable_and_ignores_runtime_timestamps():
    left = {"generated_at": "2026-01-01T00:00:00Z", "b": [2, 1], "a": {"z": 1}}
    right = {"a": {"z": 1}, "b": [2, 1], "generated_at": "2030-01-01T00:00:00Z"}
    assert canonical_json(left) == '{"a":{"z":1},"b":[2,1]}'
    assert semantic_hash(left) == semantic_hash(right)


def test_semantic_hash_includes_cutoff_and_stable_id_is_deterministic():
    assert semantic_hash({"cutoff_at": "a"}) != semantic_hash({"cutoff_at": "b"})
    assert stable_scu_id("event-1", "decision", "government|announce|policy") == (
        "scu-8e254e587523175e"
    )


def test_run_metadata_is_immutable_and_requires_all_semantic_versions():
    run = AtomicRun.create("r1", "development", "a" * 40, "2026-09-15T00:00:00Z", {"parser": "v1", "rules": "v1", "aliases": "v1", "taxonomy": "v1", "panel": "v1"})
    assert run.semantic_hash == semantic_hash(run.semantic_payload())
