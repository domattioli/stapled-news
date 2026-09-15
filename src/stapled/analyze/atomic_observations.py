"""Separate eligible-group SCU observations; masked states never become votes."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AtomicSCUObservation:
    group_id: str
    state: str
    support_ids: tuple[str, ...]
    conflict_ids: tuple[str, ...]


def build_scu_observations(rows: list[dict]) -> list[AtomicSCUObservation]:
    result = []
    for row in sorted(rows, key=lambda item: str(item["group_id"])):
        support = tuple(sorted(row.get("support_ids", [])))
        conflict = tuple(sorted(row.get("conflict_ids", [])))
        if row.get("coverage") != "eligible":
            state = "masked"
        elif support:
            state = "support"
        elif conflict:
            state = "explicit_contradiction"
        else:
            state = "eligible_omission"
        result.append(AtomicSCUObservation(str(row["group_id"]), state, support, conflict))
    return result
