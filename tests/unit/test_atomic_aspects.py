from stapled.analyze.aspects import assign_aspect


def test_aspect_assignment_is_closed_and_deterministic():
    assert assign_aspect("Court files lawsuit against agency").aspect == "legal_action"
    assert assign_aspect("Court files lawsuit against agency") == assign_aspect(
        "Court files lawsuit against agency"
    )


def test_multi_aspect_and_unrecognized_headlines_abstain():
    result = assign_aspect("President announces plan and appoints minister")
    assert (result.aspect, result.reason) == ("unknown_aspect", "multi_aspect")
    assert assign_aspect("A curious development unfolds").reason == "unsupported_aspect"
