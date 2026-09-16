from stapled.analyze.atomic_observations import build_scu_observations


def test_observations_preserve_same_group_support_and_conflict_and_mask_unavailable():
    rows = build_scu_observations([
        {"group_id": "g", "coverage": "eligible", "support_ids": ["a"], "conflict_ids": ["b"]},
        {"group_id": "x", "coverage": "collector_unavailable"},
    ])
    assert rows[0].state == "support"
    assert rows[0].conflict_ids == ("b",)
    assert rows[1].state == "masked"
