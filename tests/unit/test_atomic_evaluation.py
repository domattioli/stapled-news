import pytest

from stapled.analyze.atomic_evaluation import evaluate_annotations, validate_split


def test_annotation_split_is_disjoint_and_insufficient_counts_are_inconclusive():
    validate_split(set(range(20)), set(range(20, 100)))
    report = evaluate_annotations(20, 79, 79, {"atom_precision": .99})
    assert report.status == "inconclusive"
    with pytest.raises(ValueError, match="overlap"):
        validate_split({1}, {1})


def test_heldout_metrics_are_reported_only_when_input_exists():
    report = evaluate_annotations(20, 80, 80, {"atom_precision": .91, "match_precision": .96, "conflict_precision": .96})
    assert report.status == "pass"
