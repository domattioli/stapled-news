"""Downstream-only, non-truth classification for atomic propositions."""

from dataclasses import dataclass

from stapled.analyze.atomic_run import stable_scu_id
from stapled.analyze.panel import balanced_support


@dataclass(frozen=True)
class SummaryContentUnit:
    scu_id: str
    event_id: str | int
    aspect: str
    canonical_key: str
    occurrence_ids: tuple[str, ...]
    has_dispute: bool


@dataclass(frozen=True)
class SupportSummary:
    raw_outlet: float | None
    raw_group: float | None
    balanced: float | None
    represented_mass: float
    bounds: tuple[float, float]
    effective_n: float


def summarize_support(counts: dict, weights: dict, raw_outlets: tuple[int, int]) -> SupportSummary:
    panel = balanced_support(counts, weights)
    supported_groups = sum(value[0] for value in counts.values() if value is not None)
    eligible_groups = sum(value[1] for value in counts.values() if value is not None)
    numerator, denominator = raw_outlets
    return SupportSummary(
        numerator / denominator if denominator else None,
        supported_groups / eligible_groups if eligible_groups else None,
        panel.balanced,
        panel.represented_mass,
        panel.bounds,
        panel.effective_n,
    )


def build_scus(atoms) -> list[SummaryContentUnit]:
    """Group compatible affirmative/negative occurrences; polarity conflict is orthogonal."""
    grouped = {}
    for atom in atoms:
        if atom.abstention_reason or atom.event_id is None or atom.aspect is None:
            continue
        key = "|".join(str(value or "") for value in (atom.subject, atom.predicate, atom.object, atom.attribution, atom.modality, atom.time, atom.quantity))
        grouped.setdefault((atom.event_id, atom.aspect, key), []).append(atom)
    units = []
    for (event_id, aspect, key), members in sorted(grouped.items(), key=lambda item: tuple(map(str, item[0]))):
        polarities = {member.polarity for member in members}
        units.append(SummaryContentUnit(stable_scu_id(event_id, aspect, key), event_id, aspect, key, tuple(sorted(member.occurrence_id for member in members)), len(polarities) > 1))
    return units


def classify_scu(
    balanced: float | None,
    represented_mass: float,
    supporting_strata: set[str],
    dependencies_complete: bool,
    has_dispute: bool,
    threshold: float = 0.75,
    minimum_mass: float = 0.75,
) -> str:
    del has_dispute  # orthogonal field retained by callers, never collapsed into class.
    if not dependencies_complete or balanced is None:
        return "insufficient panel"
    if balanced >= threshold and represented_mass >= minimum_mass and len(supporting_strata) >= 2:
        return "shared core"
    return "partial coverage"
