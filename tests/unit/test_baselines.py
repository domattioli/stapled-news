"""Unit tests for baseline implementations."""

import numpy as np
import pytest
from stapled.baselines import run_baseline


class TestMajorityVote:
    """Majority vote baseline tests."""

    def test_majority_simple(self):
        """1 event, 3 claims obs [1,1,0] → posterior 2/3."""
        events = [
            {
                "event_id": 1,
                "claims": [
                    {"outlet_id": 10, "observation": 1, "certainty": 0.5},
                    {"outlet_id": 11, "observation": 1, "certainty": 0.5},
                    {"outlet_id": 12, "observation": 0, "certainty": 0.5},
                ],
            }
        ]

        result = run_baseline("majority", events)
        posteriors = result["posteriors"]
        outlet_params = result["outlet_params"]

        # Posterior should be 2/3
        assert abs(posteriors[1] - 2.0 / 3.0) < 1e-6

        # Majority label is 1 (since 2/3 > 0.5)
        # Against true state = 1:
        # - outlet 10: obs=1, state=1 → TP=1, FN=0 → sens=1.0, spec=0.5 (no TN/FP)
        # - outlet 11: obs=1, state=1 → TP=1, FN=0 → sens=1.0, spec=0.5 (no TN/FP)
        # - outlet 12: obs=0, state=1 → FN=1, TP=0 → sens=0.0, spec=0.5 (no TN/FP)

        assert abs(outlet_params[10]["sens"] - 1.0) < 1e-6
        assert abs(outlet_params[11]["sens"] - 1.0) < 1e-6
        assert abs(outlet_params[12]["sens"] - 0.0) < 1e-6
        assert abs(outlet_params[10]["spec"] - 0.5) < 1e-6

    def test_majority_tie(self):
        """obs [1,0] → posterior 0.5."""
        events = [
            {
                "event_id": 1,
                "claims": [
                    {"outlet_id": 10, "observation": 1, "certainty": 0.5},
                    {"outlet_id": 11, "observation": 0, "certainty": 0.5},
                ],
            }
        ]

        result = run_baseline("majority", events)
        posteriors = result["posteriors"]

        assert abs(posteriors[1] - 0.5) < 1e-6


class TestWeightedMajorityVote:
    """Weighted majority vote baseline tests."""

    def test_weighted_majority(self):
        """obs [1,0] certainties [0.9, 0.1] → posterior 0.9."""
        events = [
            {
                "event_id": 1,
                "claims": [
                    {"outlet_id": 10, "observation": 1, "certainty": 0.9},
                    {"outlet_id": 11, "observation": 0, "certainty": 0.1},
                ],
            }
        ]

        result = run_baseline("weighted_majority", events)
        posteriors = result["posteriors"]

        # weighted_ones = 0.9, total_weight = 1.0, posterior = 0.9
        assert abs(posteriors[1] - 0.9) < 1e-6


class TestBatchDS:
    """Batch Dawid-Skene baseline tests."""

    def test_batch_ds_recovers_reliable_majority(self):
        """
        20 events, 4 outlets.
        Outlets 1-3 report true state with 90% accuracy.
        Outlet 4 reports with 30% accuracy (unreliable).
        After batch_ds, sens/spec of outlets 1-3 > outlet 4.
        Posteriors correlate with planted states (>80% agreement).
        """
        seed = 7
        rng = np.random.default_rng(seed)

        # Plant 20 true states
        n_events = 20
        true_states = rng.integers(0, 2, size=n_events)

        # Generate observations
        events = []
        for event_idx in range(n_events):
            true_state = true_states[event_idx]
            claims = []

            # Outlets 1-3: 90% accuracy
            for outlet_id in [1, 2, 3]:
                if rng.random() < 0.9:
                    obs = true_state
                else:
                    obs = 1 - true_state
                claims.append(
                    {
                        "outlet_id": outlet_id,
                        "observation": int(obs),
                        "certainty": 0.5,
                    }
                )

            # Outlet 4: 30% accuracy
            if rng.random() < 0.3:
                obs = true_state
            else:
                obs = 1 - true_state
            claims.append(
                {
                    "outlet_id": 4,
                    "observation": int(obs),
                    "certainty": 0.5,
                }
            )

            events.append({"event_id": event_idx, "claims": claims})

        result = run_baseline("batch_ds", events)
        posteriors = result["posteriors"]
        outlet_params = result["outlet_params"]

        # Check: outlets 1-3 should have sens/spec > 0.5, outlet 4 closer to random
        reliable_outlets = [1, 2, 3]
        unreliable_outlet = 4

        for oid in reliable_outlets:
            sens = outlet_params[oid]["sens"]
            spec = outlet_params[oid]["spec"]
            # High accuracy → both sens and spec should be higher
            assert sens > 0.5, f"Outlet {oid} sens={sens} should be > 0.5"
            assert spec > 0.5, f"Outlet {oid} spec={spec} should be > 0.5"

        # Outlet 4 should be less reliable
        unreliable_sens = outlet_params[unreliable_outlet]["sens"]
        unreliable_spec = outlet_params[unreliable_outlet]["spec"]
        # Lower accuracy → sens and spec closer to random or lower
        assert (
            unreliable_sens < 0.7 or unreliable_spec < 0.7
        ), f"Outlet 4 should be less reliable: sens={unreliable_sens}, spec={unreliable_spec}"

        # Check: posteriors correlate with true states (>80% agreement)
        correct_count = 0
        for event_idx, true_state in enumerate(true_states):
            posterior = posteriors[event_idx]
            predicted_state = 1 if posterior > 0.5 else 0
            if predicted_state == true_state:
                correct_count += 1

        accuracy = correct_count / n_events
        assert (
            accuracy >= 0.8
        ), f"Batch DS accuracy {accuracy:.2f} should be >= 0.8, recovered states don't match planted"


class TestUnknownBaseline:
    """Test error handling for unknown baseline names."""

    def test_unknown_name_raises(self):
        """Unknown baseline name → ValueError."""
        events = [
            {
                "event_id": 1,
                "claims": [{"outlet_id": 1, "observation": 1, "certainty": 0.5}],
            }
        ]

        with pytest.raises(ValueError, match="Unknown baseline"):
            run_baseline("unknown_baseline", events)
