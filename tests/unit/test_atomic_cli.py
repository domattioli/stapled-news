import json

from stapled.analyze.atomic_cli import (
    extraction_payload,
    matching_payload,
    profile_payload,
    summary_payload,
)


def test_atomic_extract_payload_outputs_atoms_and_refuses_unknown_grammar():
    atom = json.loads(extraction_payload("Government approves plan"))["atoms"][0]
    assert atom["predicate"] == "approves"
    assert "unsupported_grammar" in extraction_payload("a fragment")


def test_atomic_stages_match_and_summarize_refuse_incomplete_scopes():
    atoms = json.loads(extraction_payload("Government approves plan"))["atoms"]
    atoms[0]["event_id"] = "e"
    atoms[0]["aspect"] = "decision"
    atoms.append({**atoms[0], "occurrence_id": "atom-b", "polarity": "negated"})
    matched = json.loads(matching_payload(atoms, "e", "decision"))
    assert matched["relations"][0]["relation"] == "contradiction"
    assert len(json.loads(summary_payload(atoms))["scus"]) == 1


def test_profile_report_payload_is_descriptive_only():
    report = json.loads(profile_payload("Outlet", "family", {"s": "support"}, {"s": "shared core"}))
    assert report["states"] == {"s": "shared"}
    assert "quality" not in report
