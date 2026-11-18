from stapled.analyze.panel import FrozenPanel, balanced_support


def test_balanced_support_retains_missing_mass_and_excludes_unrated():
    result = balanced_support(
        {"left": (2, 4), "center": (1, 2), "right": None, "unrated": (9, 9)},
        {"left": 1 / 3, "center": 1 / 3, "right": 1 / 3},
    )
    assert result.balanced == 0.5
    assert result.represented_mass == 2 / 3
    assert result.bounds == (1 / 3, 2 / 3)
    assert result.effective_n == 16 / 3


def test_balanced_support_zero_data_is_explicitly_undefined():
    result = balanced_support({"left": None}, {"left": 1.0})
    assert (result.balanced, result.bounds, result.effective_n) == (None, (0.0, 1.0), 0.0)


def test_frozen_panel_requires_primary_weights_and_excludes_unrated():
    panel = FrozenPanel.create(["a"], {"left": 1/3, "center": 1/3, "right": 1/3}, provenance={"roster_sha": "a" * 64})
    assert panel.unrated_policy == "descriptive-excluded-primary"
    assert panel.provenance["roster_sha"] == "a" * 64
