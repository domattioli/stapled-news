from stapled.analyze.atomic_profiles import leave_family_reference, outlet_profile
from stapled.export.atomic import profile_export


def test_profile_leaves_out_outlet_and_family_without_quality_score():
    profile = outlet_profile("A", "family-a", {"s": "support", "u": "eligible_omission", "c": "explicit_contradiction"}, {"s": "shared core", "u": "unique detail", "c": "partial coverage"})
    assert profile.states == {"s": "shared", "u": "omission", "c": "conflict"}
    assert not hasattr(profile, "quality")


def test_leave_family_reference_recomputes_without_outlet_and_exports_typed_states():
    reference = leave_family_reference("family-a", {"family-a": {"s"}, "family-b": {"s", "u"}})
    assert reference == {"s": "shared", "u": "shared"}
    assert profile_export(outlet_profile("A", "family-a", {"s": "support"}, reference))["leave_out"] == ["A", "family-a"]
