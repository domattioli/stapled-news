"""Conservative categorical likelihood primitives; publication is separately gated."""

from collections import defaultdict

_OBSERVED = {"support", "contradiction", "eligible_omission"}


def fit_categorical(observations, anchors: dict[int, bool] | None = None) -> dict:
    """Masked states are excluded. Alpha=1 smoothing, deterministic source ordering."""
    counts = defaultdict(lambda: defaultdict(float))
    accepted = 0
    for source, state, _ in observations:
        if state not in _OBSERVED:
            continue
        counts[source][state] += 1.0
        accepted += 1
    theta = {source: {state: (values[state] + 1.0) / (sum(values.values()) + 3.0) for state in sorted(_OBSERVED)} for source, values in sorted(counts.items())}
    return {"observations": accepted, "theta_source": theta, "anchors": dict(sorted((anchors or {}).items())), "alpha": 1, "shrinkage": 10, "max_iterations": 200, "convergence_streak": 3}


def publication_gate(primary_improvement: float, control_deltas: list[float], heldout_adjudicated: int) -> str:
    if heldout_adjudicated < 80:
        return "withheld"
    return "published" if primary_improvement > 0 and all(delta >= 0 for delta in control_deltas) else "withheld"
