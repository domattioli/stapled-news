"""Built-in, abstention-first atomic-grammar-v1 headline extractor."""

import hashlib
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Atom:
    occurrence_id: str
    span: tuple[int, int]
    subject: str | None
    predicate: str | None
    object: str | None
    polarity: str
    modality: str
    attribution: str | None
    quantity: str | None
    time: str | None
    location: str | None
    abstention_reason: str | None
    text: str = ""
    event_id: str | int | None = None
    aspect: str | None = None


_PATTERN = re.compile(r"^(?P<subject>[A-Z][A-Za-z ]*?)\s+(?P<negation>does not |did not |not )?(?P<predicate>announces|appoints|alleges|files|signs|approves|approve)\s+(?P<object>[a-z][A-Za-z ]*?)(?:\s+in\s+(?P<location>[A-Z][A-Za-z ]*?))?(?:\s+on\s+(?P<time>[A-Z][A-Za-z ]*))?$")
_ATTRIBUTED = re.compile(r"^(?P<source>[A-Z][A-Za-z ]*?)\s+(?:reports|says)\s+(?P<claim>.+)$")
_ALIASES = {"us government": "Government", "u.s. government": "Government"}


def _normalize_subject(subject: str) -> str:
    return _ALIASES.get(subject.casefold(), subject)


def extract_headline(headline: str) -> list[Atom]:
    text = headline.strip()
    occurrence_id = f"atom-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"
    if re.search(r"\s+(and|or)\s+", text, re.IGNORECASE):
        return [Atom(occurrence_id, (0, len(text)), None, None, None, "uncertain", "asserted", None, None, None, None, "coordination", text)]
    attribution = None
    modality = "asserted"
    attributed = _ATTRIBUTED.match(text)
    candidate = text
    if attributed:
        attribution = attributed.group("source")
        modality = "asserted_attributed"
        candidate = attributed.group("claim")
    match = _PATTERN.match(candidate)
    if not match:
        return [Atom(occurrence_id, (0, len(text)), None, None, None, "uncertain", "asserted", None, None, None, None, "unsupported_grammar", text)]
    fields = match.groupdict()
    predicate = {"approve": "approves"}.get(fields["predicate"], fields["predicate"])
    attribution = attribution or (fields["subject"] if predicate == "alleges" else None)
    modality = "alleged" if predicate == "alleges" else modality
    return [Atom(occurrence_id, (0, len(text)), _normalize_subject(fields["subject"]), predicate, fields["object"].strip(), "negated" if fields["negation"] else "affirmed", modality, attribution, None, fields["time"], fields["location"], None, text)]
