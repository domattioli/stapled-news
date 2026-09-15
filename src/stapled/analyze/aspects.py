"""Closed, deterministic aspect assignment for headline analysis."""

from dataclasses import dataclass


@dataclass(frozen=True)
class AspectAssignment:
    aspect: str
    rule: str
    reason: str | None = None


_RULES = {
    "legal_action": ("lawsuit", "sues", "sue", "charges", "indicts", "files"),
    "appointment": ("appoints", "appointed", "names", "named"),
    "proposal": ("proposes", "proposal", "plan"),
    "decision": ("announces", "approves", "rejects", "signs", "votes"),
    "statement": ("says", "said", "alleges", "claims"),
    "casualty": ("killed", "dead", "dies", "injured"),
    "quantity": ("percent", "million", "billion"),
    "location": ("moves", "relocates"),
    "time_update": ("delays", "postpones", "reschedules"),
    "occurrence": ("wins", "opens", "closes", "begins"),
}


def assign_aspect(headline: str) -> AspectAssignment:
    words = set(headline.lower().replace(".", "").split())
    matches = [aspect for aspect, triggers in _RULES.items() if words.intersection(triggers)]
    if len(matches) == 1:
        return AspectAssignment(matches[0], f"keyword:{matches[0]}")
    if len(matches) > 1:
        return AspectAssignment("unknown_aspect", "abstain", "multi_aspect")
    return AspectAssignment("unknown_aspect", "abstain", "unsupported_aspect")
