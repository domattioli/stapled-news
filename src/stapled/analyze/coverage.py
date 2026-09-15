"""Coverage eligibility is independent of proposition mention."""

from dataclasses import dataclass

_COVERAGE_STATES = {"eligible", "non_coverage", "collector_unavailable", "unknown_relevance"}


@dataclass(frozen=True)
class CoverageObservation:
    group_id: str
    state: str
    reason: str | None
    eligible: bool


@dataclass(frozen=True)
class SCUObservation:
    state: str


def coverage_observation(group_id: str, state: str, reason: str | None = None) -> CoverageObservation:
    if state not in _COVERAGE_STATES:
        raise ValueError(f"unknown coverage state: {state}")
    return CoverageObservation(group_id, state, reason, state == "eligible")


def scu_observation(
    coverage: CoverageObservation, mentioned: bool, contradicted: bool = False
) -> SCUObservation:
    if not coverage.eligible:
        return SCUObservation("masked")
    if contradicted:
        return SCUObservation("explicit_contradiction")
    return SCUObservation("support" if mentioned else "eligible_omission")
