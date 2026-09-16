import json
from pathlib import Path


def test_contract_fixture_has_required_v1_analysis_and_evidence_shapes():
    contract = json.loads((Path(__file__).parents[2] / "specs/005-atomic-consensus/contracts/atomic-consensus.schema.json").read_text())
    assert contract["properties"]["schema_version"]["const"] == "1.0"
    assert {"run_id", "status", "corpus", "hashes"} <= set(contract["$defs"]["analysis"]["required"])
    assert {"span", "span_convention", "rule"} <= set(contract["$defs"]["evidence"]["required"])
