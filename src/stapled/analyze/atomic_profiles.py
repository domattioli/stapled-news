"""Event-specific descriptive outlet profiles; never global quality scores."""

from dataclasses import dataclass


@dataclass(frozen=True)
class OutletEventProfile:
    outlet: str
    leave_out: tuple[str, ...]
    states: dict[str, str]


def leave_family_reference(family: str, family_support: dict[str, set[str]]) -> dict[str, str]:
    """Recompute reference from non-family signals; one remaining family is still descriptive."""
    remaining = [scus for name, scus in sorted(family_support.items()) if name != family]
    counts = {}
    for scus in remaining:
        for scu in scus:
            counts[scu] = counts.get(scu, 0) + 1
    return {scu: "shared" for scu, count in sorted(counts.items()) if count >= 1}


def outlet_profile(outlet: str, reporting_family: str, observations: dict[str, str], classifications: dict[str, str]) -> OutletEventProfile:
    states = {}
    for scu_id, observation in sorted(observations.items()):
        if observation == "explicit_contradiction":
            states[scu_id] = "conflict"
        elif observation == "eligible_omission":
            states[scu_id] = "omission"
        elif observation == "support" and classifications.get(scu_id) == "shared core":
            states[scu_id] = "shared"
        elif observation == "support":
            states[scu_id] = "unique"
        elif observation == "masked":
            states[scu_id] = "collector_unavailable"
        else:
            states[scu_id] = "unknown_relevance"
    return OutletEventProfile(outlet, tuple(sorted({outlet, reporting_family})), states)
