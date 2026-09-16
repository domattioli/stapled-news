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


def test_event_id_scoping_required_for_match():
    atoms = [
        atom(occurrence_id="a", event_id="e1", aspect="decision"),
        atom(occurrence_id="b", event_id="e2", aspect="decision"),
    ]
    result = match_atoms(atoms, event_id="e1", aspect="decision")
    assert len(result) == 0


def test_aspect_scoping_required_for_match():
    atoms = [
        atom(occurrence_id="a", event_id="e", aspect="decision"),
        atom(occurrence_id="b", event_id="e", aspect="statement"),
    ]
    result = match_atoms(atoms, event_id="e", aspect="decision")
    assert len(result) == 0


def test_unscoped_atoms_match_any_event_id_and_aspect():
    atoms = [
        atom(occurrence_id="a", event_id=None, aspect=None),
        atom(occurrence_id="b", event_id=None, aspect=None),
    ]
    result = match_atoms(atoms, event_id="e", aspect="decision")
    assert len(result) == 1
    assert result[0].relation == "equivalence"


def test_alias_normalization_us_government():
    atoms = [
        atom(occurrence_id="a", subject="US government"),
        atom(occurrence_id="b", subject="Government"),
    ]
    result = match_atoms(atoms, event_id="e", aspect="decision")
    assert len(result) == 1
    assert result[0].relation == "equivalence"


def test_alias_normalization_u_s_government():
    atoms = [
        atom(occurrence_id="a", subject="U.S. government"),
        atom(occurrence_id="b", subject="Government"),
    ]
    result = match_atoms(atoms, event_id="e", aspect="decision")
    assert len(result) == 1


def test_order_stability_same_result_regardless_of_input_order():
    atoms_forward = [
        atom(occurrence_id="a"),
        atom(occurrence_id="b"),
        atom(occurrence_id="c"),
    ]
    atoms_reverse = list(reversed(atoms_forward))
    result_forward = match_atoms(atoms_forward, "e", "decision")
    result_reverse = match_atoms(atoms_reverse, "e", "decision")
    assert [(r.left_id, r.right_id, r.relation) for r in result_forward] == [(r.left_id, r.right_id, r.relation) for r in result_reverse]


def test_temporal_update_same_subject_predicate_different_time():
    atoms = [
        atom(occurrence_id="a", time="Monday"),
        atom(occurrence_id="b", time="Tuesday"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert result[0].relation == "possible_conflict"
    assert result[0].rule == "scope_update_v1"


def test_numeric_update_same_subject_predicate_different_quantity():
    atoms = [
        atom(occurrence_id="a", quantity="$5 million"),
        atom(occurrence_id="b", quantity="$10 million"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert result[0].relation == "possible_conflict"
    assert result[0].rule == "scope_update_v1"


def test_polarity_conflict_affirmed_vs_negated():
    atoms = [
        atom(occurrence_id="a", polarity="affirmed"),
        atom(occurrence_id="b", polarity="negated"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert result[0].relation == "contradiction"
    assert result[0].rule == "exclusive_polarity_v1"


def test_governing_rule_exact_scope_on_equivalence():
    atoms = [
        atom(occurrence_id="a"),
        atom(occurrence_id="b"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert result[0].rule == "exact_scope_v1"


def test_governing_rule_exclusive_polarity_on_contradiction():
    atoms = [
        atom(occurrence_id="a", polarity="affirmed"),
        atom(occurrence_id="b", polarity="negated"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert result[0].rule == "exclusive_polarity_v1"


def test_governing_rule_scope_update_on_time_difference():
    atoms = [
        atom(occurrence_id="a", time="Monday"),
        atom(occurrence_id="b", time="Tuesday"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert result[0].rule == "scope_update_v1"


def test_predicate_must_match_for_relation():
    atoms = [
        atom(occurrence_id="a", predicate="announces"),
        atom(occurrence_id="b", predicate="appoints"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert len(result) == 0


def test_object_must_match_for_relation():
    atoms = [
        atom(occurrence_id="a", object="policy"),
        atom(occurrence_id="b", object="plan"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert len(result) == 0


def test_attribution_must_match_for_relation():
    atoms = [
        atom(occurrence_id="a", attribution="Reuters"),
        atom(occurrence_id="b", attribution="AP"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert len(result) == 0


def test_modality_must_match_for_relation():
    atoms = [
        atom(occurrence_id="a", modality="asserted"),
        atom(occurrence_id="b", modality="alleged"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert len(result) == 0


def test_time_and_quantity_can_differ_without_matching():
    atoms = [
        atom(occurrence_id="a", time="Monday", quantity="$5 million"),
        atom(occurrence_id="b", time="Tuesday", quantity="$10 million"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert len(result) == 1
    assert result[0].relation == "possible_conflict"


def test_location_difference_ignored_in_matching():
    atoms = [
        atom(occurrence_id="a", location="Texas"),
        atom(occurrence_id="b", location="Florida"),
    ]
    result = match_atoms(atoms, "e", "decision")
    assert len(result) == 1
    assert result[0].relation == "equivalence"
