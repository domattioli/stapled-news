"""Built-in, abstention-first atomic-grammar-v1 headline extractor."""

import hashlib
import re
from dataclasses import dataclass

GRAMMAR_VERSION = "atomic-grammar-v1"

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


_PATTERN = re.compile(r"^(?P<subject>\S+(?:\s+\S+)*?)\s+(?P<negation>does not |did not |not )?(?P<predicate>announce|announces|appoint|appoints|allege|alleges|file|files|sign|signs|approve|approves)\s+(?P<object_and_rest>.+?)$")
_ATTRIBUTED = re.compile(r"^(?P<source>[A-Z][A-Za-z ]*?)\s+(?:reports|says)\s+(?P<claim>.+)$")
_QUANTITY = re.compile(r"\$[\d,]+(?:\.\d+)?\s*(?:million|billion|thousand|k)?|\d+\s+(?:people|staff|employees|officials|agents|troops|soldiers|dollars)")
_LOCATION_TIME = re.compile(r"(?:\s+in\s+(?P<location>[A-Z][A-Za-z ]*?))?(?:\s+on\s+(?P<time>[A-Z][A-Za-z ]*?))?$")
_ALIASES = {
    "us government": "Government",
    "u.s. government": "Government",
    "u.s.": "US",
    "the government": "Government",
    "administration": "Government",
    "federal government": "Government",
}


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
    predicate_raw = fields["predicate"]
    predicate = {"approve": "approves", "appoint": "appoints", "announce": "announces", "allege": "alleges", "file": "files", "sign": "signs"}.get(predicate_raw, predicate_raw)
    attribution = attribution or (fields["subject"] if predicate == "alleges" else None)
    modality = "alleged" if predicate == "alleges" else modality

    rest = fields["object_and_rest"].strip()
    quantity = None
    location = None
    time = None
    quantity_match = _QUANTITY.search(rest)
    if quantity_match:
        quantity = quantity_match.group(0)
        before_qty = rest[:quantity_match.start()].strip()
        after_qty = rest[quantity_match.end():].strip()
        rest = before_qty + " " + after_qty if before_qty and after_qty else (before_qty or after_qty)

    location_time_match = _LOCATION_TIME.search(rest)
    if location_time_match:
        location = location_time_match.group("location")
        time = location_time_match.group("time")
        rest = rest[:location_time_match.start()].strip()

    obj = rest if rest else None
    return [Atom(occurrence_id, (0, len(text)), _normalize_subject(fields["subject"]), predicate, obj, "negated" if fields["negation"] else "affirmed", modality, attribution, quantity, time, location, None, text)]
