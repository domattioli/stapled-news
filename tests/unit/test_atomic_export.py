import json
from pathlib import Path

import pytest

from stapled.export.atomic import build_export, validate_export


def minimal_analysis():
    return {
        "run_id": "run-1", "status": "draft", "corpus": {"ref": "development", "git_rev": "a" * 40},
        "cutoff_at": "2026-09-15T00:00:00Z",
        "versions": {key: "v1" for key in ("parser", "rules", "aliases", "taxonomy", "panel")},
        "hashes": {key: "b" * 64 for key in ("code", "config", "environment", "canonical")},
        "panel": {"roster": [], "strata": ["left", "center", "right"], "weights": {"left": 1/3, "center": 1/3, "right": 1/3}, "unrated_policy": "descriptive-excluded-primary"},
        "estimator": {"mode": "balanced_descriptive", "status": "not_run"},
        "evaluation": {"pilot_events": 20, "heldout_events": 80, "status": "pending"},
    }


def test_export_includes_exact_evidence_and_is_canonical():
    payload = build_export(minimal_analysis(), [])
    assert payload["schema_version"] == "1.0"
    assert payload["analysis"]["hashes"]["artifact_digests"]["atomic_consensus.json"]
    validate_export(payload)


def test_export_refuses_malformed_or_overclaiming_estimator_status():
    invalid = build_export(minimal_analysis(), [])
    invalid["analysis"]["estimator"] = {"mode": "categorical_em", "status": "published"}
    with pytest.raises(ValueError, match="evaluation pass"):
        validate_export(invalid)


def test_contract_declares_pending_evaluation_and_nullable_modeled_score():
    contract = json.loads((Path(__file__).parents[2] / "specs/005-atomic-consensus/contracts/atomic-consensus.schema.json").read_text())
    assert "pending" in contract["$defs"]["evaluation"]["properties"]["status"]["enum"]
    assert "null" in contract["$defs"]["fact"]["properties"]["modeled_core_membership"]["type"]


def test_export_sorts_events_and_validates_exact_evidence_contract():
    evidence = {"article_id": "a", "outlet": "Example", "url": "https://example.test/a", "headline": "Government approves plan", "occurrence_id": "atom-a", "reporting_group_id": "rg-a", "span": [0, 24], "span_convention": "utf8-codepoint-halfopen", "scope": {"event_id": "e", "aspect": "decision"}, "relation": "support", "rule": "exact_scope_v1"}
    fact = {"scu_id": "scu-a", "display": "Government approves plan", "classification": "partial coverage", "has_dispute": False, "support": {"raw_outlet": 1.0, "raw_group": 1.0, "raw_outlet_numerator": 1, "raw_outlet_denominator": 1, "raw_group_numerator": 1, "raw_group_denominator": 1, "balanced": 1.0, "represented_mass": 1.0, "missing_mass_bounds": [1.0, 1.0], "independent_groups": 1, "effective_n": 1.0}, "evidence": [evidence]}
    event = {"event_id": "e", "as_of": "2026-09-15T00:00:00Z", "facts": [fact], "profiles": [], "coverage": {"raw_sources": 1, "independent_groups": 1, "represented_target_mass": 1.0, "missing_strata": [], "missing_reasons": []}}
    payload = build_export(minimal_analysis(), [event])
    validate_export(payload)


def test_export_defaults_missing_reasons_and_modeled_score_to_explicit_null():
    event = {"event_id": "e", "as_of": "2026-09-15T00:00:00Z", "facts": [{"scu_id": "x"}], "profiles": [], "coverage": {"raw_sources": 0, "independent_groups": 0, "represented_target_mass": 0, "missing_strata": []}}
    payload = build_export(minimal_analysis(), [event])
    assert payload["events"][0]["facts"][0]["modeled_core_membership"] is None
    assert payload["events"][0]["coverage"]["missing_reasons"] == []
