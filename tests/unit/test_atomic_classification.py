from stapled.analyze.atomic_summary import build_scus, classify_scu, summarize_support
from stapled.extract.atomic import Atom


def test_shared_core_requires_complete_panel_dependencies_and_two_strata():
    assert classify_scu(0.8, 0.9, {"left", "right"}, False, False) == "insufficient panel"
    assert classify_scu(0.8, 0.9, {"left"}, True, False) == "partial coverage"
    assert classify_scu(0.8, 0.9, {"left", "right"}, True, False) == "shared core"


def test_dispute_is_orthogonal_to_classification():
    result = classify_scu(0.8, 0.9, {"left", "right"}, True, True)
    assert result == "shared core"


def test_scu_grouping_uses_stable_id_and_retains_conflict_flag():
    atoms = [
        Atom("b", (0, 1), "Government", "approves", "plan", "affirmed", "asserted", None, None, None, None, None, event_id="e", aspect="decision"),
        Atom("a", (0, 1), "Government", "approves", "plan", "negated", "asserted", None, None, None, None, None, event_id="e", aspect="decision"),
    ]
    scus = build_scus(atoms)
    assert len(scus) == 1
    assert scus[0].occurrence_ids == ("a", "b")
    assert scus[0].has_dispute is True


def test_summary_reports_raw_and_balanced_without_reallocating_missing_panel():
    support = summarize_support({"left": (1, 2), "right": None}, {"left": .5, "right": .5}, raw_outlets=(2, 3))
    assert (support.raw_outlet, support.raw_group, support.balanced, support.bounds) == (2/3, .5, .5, (.25, .75))
