from stapled.analyze.atomic_sensitivity import (
    effective_n,
    leave_one_out_ranges,
    owner_sensitivity,
    sensitivity_ranges,
)


def test_group_and_stratum_leave_out_ranges_are_deterministic():
    values = {"g2": (0.6, "right"), "g1": (0.8, "left")}
    assert leave_one_out_ranges(values) == (0.6, 0.8)


def test_owner_sensitivity_exposes_alternate_home_allocations():
    assert owner_sensitivity({"family": ["left", "right"]})["family"] == ("left", "right")


def test_effective_n_duplicate_and_all_leave_dimensions_are_explicit():
    assert effective_n([.5, .5]) == 2.0
    ranges = sensitivity_ranges({"g1": (.5, "left", "owner-a"), "g2": (.8, "right", "owner-b")})
    assert set(ranges) == {"leave_group", "leave_stratum", "owner"}
