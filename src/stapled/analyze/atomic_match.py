"""Order-stable, scope-aware atomic matching."""

from dataclasses import dataclass
from itertools import combinations


def _normalize_subject(subject):
    return {"us government": "government", "u.s. government": "government"}.get(
        str(subject).casefold(), str(subject).casefold()
    )


@dataclass(frozen=True)
class AtomRelation:
    left_id: str
    right_id: str
    relation: str
    rule: str


def match_atoms(atoms, event_id: str | int, aspect: str) -> list[AtomRelation]:
    relations = []
    scoped = [atom for atom in atoms if atom.event_id in (None, event_id) and atom.aspect in (None, aspect)]
    for left, right in combinations(sorted(scoped, key=lambda atom: atom.occurrence_id), 2):
        base_left = (_normalize_subject(left.subject), left.predicate, left.object, left.attribution, left.modality)
        base_right = (_normalize_subject(right.subject), right.predicate, right.object, right.attribution, right.modality)
        if base_left != base_right:
            continue
        if left.time != right.time or left.quantity != right.quantity:
            relations.append(AtomRelation(left.occurrence_id, right.occurrence_id, "possible_conflict", "scope_update_v1"))
        elif left.polarity != right.polarity:
            relations.append(AtomRelation(left.occurrence_id, right.occurrence_id, "contradiction", "exclusive_polarity_v1"))
        else:
            relations.append(AtomRelation(left.occurrence_id, right.occurrence_id, "equivalence", "exact_scope_v1"))
    return relations
