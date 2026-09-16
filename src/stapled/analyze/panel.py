"""Frozen primary-panel accounting; unrated data remains descriptive only."""

from dataclasses import dataclass


@dataclass(frozen=True)
class PanelSupport:
    balanced: float | None
    represented_mass: float
    bounds: tuple[float, float]
    effective_n: float


@dataclass(frozen=True)
class FrozenPanel:
    roster: tuple[str, ...]
    weights: tuple[tuple[str, float], ...]
    unrated_policy: str = "descriptive-excluded-primary"
    provenance: dict | None = None

    @classmethod
    def create(cls, roster: list[str], weights: dict[str, float], provenance: dict | None = None):
        required = {"left", "center", "right"}
        if set(weights) != required or abs(sum(weights.values()) - 1.0) > 1e-9:
            raise ValueError("primary panel requires normalized left/center/right weights")
        return cls(tuple(sorted(roster)), tuple(sorted(weights.items())), provenance=provenance or {})


def balanced_support(
    counts: dict[str, tuple[int, int] | None], weights: dict[str, float]
) -> PanelSupport:
    observed = {key: value for key, value in counts.items() if key in weights and value is not None}
    represented = sum(weights[key] for key in observed)
    if represented == 0:
        return PanelSupport(None, 0.0, (0.0, 1.0), 0.0)
    balanced = sum(weights[key] * (support / eligible) for key, (support, eligible) in observed.items()) / represented
    qs = [weights[key] / eligible for key, (_, eligible) in observed.items() for _ in range(eligible)]
    effective_n = sum(qs) ** 2 / sum(weight * weight for weight in qs)
    lower = represented * balanced
    return PanelSupport(balanced, represented, (lower, lower + 1 - represented), effective_n)
