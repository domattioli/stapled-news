from stapled.extract.atomic import extract_headline


def test_extracts_declarative_headline_with_exact_span_and_fields():
    atom = extract_headline("Government announces policy in Texas on Monday")[0]
    assert (atom.subject, atom.predicate, atom.object) == ("Government", "announces", "policy")
    assert atom.location == "Texas"
    assert atom.time == "Monday"
    assert atom.span == (0, 46)
    assert atom.text == "Government announces policy in Texas on Monday"


def test_attribution_and_coordination_abstain_without_unqualified_claim():
    alleged = extract_headline("Senator alleges company broke law")[0]
    assert alleged.attribution == "Senator"
    assert alleged.modality == "alleged"
    abstention = extract_headline("Government announces policy and appoints minister")[0]
    assert abstention.abstention_reason == "coordination"


def test_normalizes_versioned_aliases_and_preserves_negation_and_attribution():
    atom = extract_headline("US government does not approve plan")[0]
    assert (atom.subject, atom.predicate, atom.polarity) == ("Government", "approves", "negated")
    attributed = extract_headline("Reuters reports Government approves plan")[0]
    assert (attributed.attribution, attributed.modality) == ("Reuters", "asserted_attributed")
