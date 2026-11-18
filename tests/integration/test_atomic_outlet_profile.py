from stapled.analyze.atomic_observations import build_scu_observations
from stapled.analyze.atomic_profiles import outlet_profile


def test_duplicate_failure_omission_and_allegation_states_remain_distinct():
    states = {item.group_id: item.state for item in build_scu_observations([
        {"group_id": "wire", "coverage": "eligible", "support_ids": ["duplicate-a", "duplicate-b"]},
        {"group_id": "failed", "coverage": "collector_unavailable"},
        {"group_id": "omit", "coverage": "eligible"},
    ])}
    profile = outlet_profile("A", "wire", states, {"wire": "shared core", "failed": "partial coverage", "omit": "partial coverage"})
    assert states == {"failed": "masked", "omit": "eligible_omission", "wire": "support"}
    assert profile.states["omit"] == "omission"
