from stapled.extract.atomic import GRAMMAR_VERSION, extract_headline


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


def test_grammar_version_constant_exists():
    assert GRAMMAR_VERSION == "atomic-grammar-v1"


def test_extracts_monetary_quantity():
    atom = extract_headline("Government approves $5 million")[0]
    assert atom.quantity == "$5 million"
    assert atom.abstention_reason is None


def test_extracts_people_count_quantity():
    atom = extract_headline("Government appoints 200 people")[0]
    assert atom.quantity == "200 people"


def test_extracts_quantity_with_billions():
    atom = extract_headline("Government approves $2.5 billion")[0]
    assert atom.quantity == "$2.5 billion"


def test_extracts_quantity_abbreviated_million():
    atom = extract_headline("Government announces $10 million")[0]
    assert atom.quantity == "$10 million"


def test_exact_span_matches_full_headline():
    text = "Senator announces plan in Texas"
    atom = extract_headline(text)[0]
    assert atom.span == (0, len(text))
    assert atom.text == text


def test_location_and_time_both_present():
    atom = extract_headline("Government approves plan in Florida on Tuesday")[0]
    assert atom.location == "Florida"
    assert atom.time == "Tuesday"


def test_location_without_time():
    atom = extract_headline("Government approves plan in Maine")[0]
    assert atom.location == "Maine"
    assert atom.time is None


def test_time_without_location():
    atom = extract_headline("Government approves plan on Friday")[0]
    assert atom.time == "Friday"
    assert atom.location is None


def test_affirmed_polarity_default():
    atom = extract_headline("Government approves plan")[0]
    assert atom.polarity == "affirmed"


def test_negated_polarity_with_does_not():
    atom = extract_headline("Government does not approve plan")[0]
    assert atom.polarity == "negated"


def test_negated_polarity_with_did_not():
    atom = extract_headline("Government did not approve plan")[0]
    assert atom.polarity == "negated"


def test_negated_polarity_with_not():
    atom = extract_headline("Government not approve plan")[0]
    assert atom.polarity == "negated"


def test_asserted_modality_default():
    atom = extract_headline("Government approves plan")[0]
    assert atom.modality == "asserted"


def test_alleged_modality_from_alleges_predicate():
    atom = extract_headline("Senator alleges company broke law")[0]
    assert atom.modality == "alleged"


def test_asserted_attributed_modality():
    atom = extract_headline("Reuters reports Government approves plan")[0]
    assert atom.modality == "asserted_attributed"


def test_attribution_source_extracted():
    atom = extract_headline("Bloomberg reports Government approves plan")[0]
    assert atom.attribution == "Bloomberg"


def test_attribution_says_variant():
    atom = extract_headline("Senator says Government approves plan")[0]
    assert atom.attribution == "Senator"


def test_allegation_sets_attribution_from_subject():
    atom = extract_headline("Senator alleges company broke law")[0]
    assert atom.attribution == "Senator"


def test_coordination_and_abstains():
    atom = extract_headline("Government announces policy and appoints minister")[0]
    assert atom.abstention_reason == "coordination"
    assert atom.polarity == "uncertain"


def test_coordination_or_abstains():
    atom = extract_headline("Government approves plan or appoints officer")[0]
    assert atom.abstention_reason == "coordination"


def test_unsupported_grammar_abstains():
    atom = extract_headline("Invalid headline format")[0]
    assert atom.abstention_reason == "unsupported_grammar"
    assert atom.subject is None


def test_normalized_aliases_in_subject():
    tests = [
        ("US government approves plan", "Government"),
        ("U.S. government approves plan", "Government"),
        ("The government approves plan", "Government"),
        ("Administration approves plan", "Government"),
    ]
    for headline, expected_subject in tests:
        atom = extract_headline(headline)[0]
        assert atom.subject == expected_subject


def test_span_correct_with_attribution():
    text = "Reuters reports Government approves plan"
    atom = extract_headline(text)[0]
    assert atom.span == (0, len(text))


def test_orthogonal_polarity_and_modality():
    tests = [
        ("Government announces plan", "affirmed", "asserted"),
        ("Government does not announce plan", "negated", "asserted"),
        ("Reuters reports Government announces plan", "affirmed", "asserted_attributed"),
        ("Reuters reports Government does not announce plan", "negated", "asserted_attributed"),
        ("Senator alleges company broke law", "affirmed", "alleged"),
        ("Senator does not allege company broke law", "negated", "alleged"),
    ]
    for headline, expected_polarity, expected_modality in tests:
        atom = extract_headline(headline)[0]
        assert atom.polarity == expected_polarity, f"Failed for {headline}"
        assert atom.modality == expected_modality, f"Failed for {headline}"
