from stapled.experiments.atomic_simulator import run_scenario, sweep


def test_simulator_reports_discovery_and_conditional_support_separately():
    result = run_scenario({"seed": 7, "candidate_discovery_rate": 0.5, "support_rate": 0.8, "n": 20})
    assert result["candidate_discovery"] != result["conditional_support"]
    assert result["n_found"] <= 20


def test_simulator_sweep_covers_declared_panel_stress_dimensions():
    results = sweep({"seed": 1, "n": 3, "candidate_discovery_rate": .5, "support_rate": .5}, ["panel_skew", "missingness", "syndication", "ownership", "minority_details", "contradictions", "updates", "outcome_missingness"])
    assert set(results) == {"panel_skew", "missingness", "syndication", "ownership", "minority_details", "contradictions", "updates", "outcome_missingness"}
