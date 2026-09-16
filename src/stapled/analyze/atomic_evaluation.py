"""Held-out gates for atomic evaluation; never fabricate missing measurements."""

from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationReport:
    status: str
    metrics: dict
    pilot_actual: int
    heldout_actual: int
    adjudicated_actual: int


def validate_split(pilot: set, heldout: set) -> None:
    if pilot.intersection(heldout):
        raise ValueError("pilot and heldout overlap")


def evaluate_annotations(pilot_actual: int, heldout_actual: int, adjudicated_actual: int, metrics: dict) -> EvaluationReport:
    if pilot_actual < 20 or heldout_actual < 80 or adjudicated_actual < 80:
        return EvaluationReport("inconclusive", metrics, pilot_actual, heldout_actual, adjudicated_actual)
    required = {"atom_precision": .90, "match_precision": .95, "conflict_precision": .95}
    status = "pass" if all(metrics.get(key, 0) >= threshold for key, threshold in required.items()) else "fail"
    return EvaluationReport(status, metrics, pilot_actual, heldout_actual, adjudicated_actual)
