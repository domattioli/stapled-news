from stapled.analyze.atomic_match import match_atoms
from stapled.extract.atomic import Atom


def atom(**changes):
    value = Atom("x", (0, 1), "Government", "announces", "policy", "affirmed", "asserted", None, None, None, None, None)
    return value.__class__(**{**value.__dict__, **changes})


def test_matching_is_scoped_order_stable_and_conflicts_are_explicit():
    atoms = [atom(occurrence_id="b"), atom(occurrence_id="a"), atom(occurrence_id="c", polarity="negated")]
    result = match_atoms(atoms, event_id="e1", aspect="decision")
    assert [(r.left_id, r.right_id, r.relation, r.rule) for r in result] == [
        ("a", "b", "equivalence", "exact_scope_v1"),
        ("a", "c", "contradiction", "exclusive_polarity_v1"),
        ("b", "c", "contradiction", "exclusive_polarity_v1"),
    ]


def test_incompatible_time_is_possible_conflict_not_contradiction():
    result = match_atoms([atom(occurrence_id="a", time="Monday"), atom(occurrence_id="b", time="Tuesday")], "e", "decision")
    assert result[0].relation == "possible_conflict"


def test_matching_rejects_other_event_or_aspect_and_matches_aliases():
    atoms = [
        atom(occurrence_id="a", subject="US government", event_id="e", aspect="decision"),
        atom(occurrence_id="b", subject="Government", event_id="e", aspect="decision"),
        atom(occurrence_id="c", event_id="other", aspect="decision"),
        atom(occurrence_id="d", event_id="e", aspect="statement"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert [(item.left_id, item.right_id) for item in result] == [("a", "b")]
