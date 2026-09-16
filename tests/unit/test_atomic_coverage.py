from stapled.analyze.coverage import coverage_observation, scu_observation


def test_coverage_and_scu_observations_are_separate_and_mask_noneligible_states():
    unavailable = coverage_observation("g1", "collector_unavailable", "feed timeout")
    assert unavailable.eligible is False
    assert unavailable.reason == "feed timeout"
    assert scu_observation(unavailable, mentioned=False).state == "masked"

    eligible = coverage_observation("g1", "eligible")
    assert scu_observation(eligible, mentioned=False).state == "eligible_omission"
    assert scu_observation(eligible, mentioned=True, contradicted=True).state == "explicit_contradiction"
