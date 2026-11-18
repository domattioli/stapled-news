from stapled.analyze.atomic_sensitivity import leave_one_out_ranges
from stapled.analyze.panel import balanced_support


def test_missing_stratum_is_bounds_not_zero_support_and_duplicate_invariance():
    result = balanced_support({"left": (1, 1), "right": None}, {"left": .5, "right": .5})
    assert result.bounds == (.5, 1.0)
    assert leave_one_out_ranges({"wire": (.5, "left")}) == (.5, .5)
