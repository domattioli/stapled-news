from stapled.analyze.atomic_run import semantic_hash


def test_semantic_hash_excludes_runtime_only_but_includes_cutoff_and_source_times():
    base = {"cutoff_at": "a", "source_seen_at": "b", "generated_at": "x"}
    assert semantic_hash(base) == semantic_hash({**base, "generated_at": "y"})
    assert semantic_hash(base) != semantic_hash({**base, "source_seen_at": "c"})
