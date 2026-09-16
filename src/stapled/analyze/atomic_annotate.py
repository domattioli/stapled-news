"""Offline LLM annotation harness: builds prompts, ingests pasted-back replies as model-generated."""

import csv
import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from stapled.extract.atomic import GRAMMAR_VERSION

DEFAULT_ANNOTATOR_MODEL = "fable"
ANNOTATOR_VERSION = "atomic-annotate-v1"
SOURCE_TAG = "model-generated"
DEFAULT_BATCH_SIZE = 20

ABSTENTION_CODES = ("coordination", "unsupported_grammar", "ambiguous_reference", "no_clear_predicate")
POLARITIES = ("affirmed", "negated", "uncertain")
MODALITIES = ("asserted", "asserted_attributed", "alleged")
ATOM_FIELDS = ("subject", "predicate", "object", "polarity", "modality", "attribution", "quantity", "time", "location", "abstention_reason")

SYSTEM_PROMPT = """You annotate English news headlines under atomic-grammar-v1. Return one atom per headline.

Fields (all required, use null when absent): subject, predicate, object, polarity, modality, attribution, quantity, time, location, abstention_reason.

polarity: affirmed | negated | uncertain. modality: asserted | asserted_attributed | alleged.
Polarity and modality are orthogonal: negation is a property of the claim, attribution is a property of who states it. Never encode negation as a modality or attribution as a polarity.
asserted_attributed: an outlet or named source reports the claim ("Reuters reports X"); attribution is that source.
alleged: the predicate itself is an accusation ("Senator alleges X"); attribution is the accuser.
Plain claims are asserted with attribution null.

Abstain instead of guessing. abstention_reason is null or exactly one of: coordination (two or more conjoined claims in one headline), unsupported_grammar (not a single subject-predicate-object clause), ambiguous_reference (subject or object cannot be resolved), no_clear_predicate (no assertable predicate). When abstaining, set subject, predicate and object to null and polarity to uncertain.

Output a JSON array only: one object per input id, same order, each object {"id": <input id>, plus the ten fields}. No prose, no markdown fences.

Examples.
Input: [{"id":1,"text":"Government announces policy in Texas on Monday"}]
Output: [{"id":1,"subject":"Government","predicate":"announces","object":"policy","polarity":"affirmed","modality":"asserted","attribution":null,"quantity":null,"time":"Monday","location":"Texas","abstention_reason":null}]
Input: [{"id":2,"text":"Reuters reports Government approves plan"}]
Output: [{"id":2,"subject":"Government","predicate":"approves","object":"plan","polarity":"affirmed","modality":"asserted_attributed","attribution":"Reuters","quantity":null,"time":null,"location":null,"abstention_reason":null}]
Input: [{"id":3,"text":"Government does not approve plan"}]
Output: [{"id":3,"subject":"Government","predicate":"approves","object":"plan","polarity":"negated","modality":"asserted","attribution":null,"quantity":null,"time":null,"location":null,"abstention_reason":null}]"""

BATCH_HEADER = "Annotate these headlines. JSON array only."


class AnnotationError(ValueError):
    """Raised when a reply cannot be ingested without fabricating an annotation."""


@dataclass(frozen=True)
class AnnotatedAtom:
    id: str | int
    text: str
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
    grammar_version: str
    source: str
    annotator_model: str
    annotator_version: str
    prompt_hash: str


def prompt_hash() -> str:
    return hashlib.sha256(SYSTEM_PROMPT.encode("utf-8")).hexdigest()


def build_batch_block(batch: Sequence[dict]) -> str:
    if not batch:
        raise AnnotationError("empty batch")
    return json.dumps([{"id": item["id"], "text": item["text"]} for item in batch], ensure_ascii=False)


def build_annotation_prompt(batch: Sequence[dict]) -> str:
    """Block A is byte-identical every call; only the trailing batch block varies."""
    return f"{SYSTEM_PROMPT}\n\n{BATCH_HEADER}\n{build_batch_block(batch)}\n"


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AnnotationError(message)


def _records(raw_json_text: str, batch: Sequence[dict]) -> list[dict]:
    try:
        records = json.loads(raw_json_text.strip())
    except json.JSONDecodeError as error:
        raise AnnotationError(f"reply is not JSON (markdown fences and prose are rejected): {error}") from error
    _require(isinstance(records, list), "reply is not a JSON array")
    _require(len(records) == len(batch), f"expected {len(batch)} records, got {len(records)}")
    return records


def parse_annotation_response(raw_json_text: str, batch: Sequence[dict], model_name: str = DEFAULT_ANNOTATOR_MODEL) -> list[AnnotatedAtom]:
    """Validate a Fable reply against the atom schema and tag it as model-generated."""
    digest = prompt_hash()
    annotated = []
    for record, item in zip(_records(raw_json_text, batch), batch):
        _require(isinstance(record, dict), "record is not an object")
        _require(record.get("id") == item["id"], f"record id mismatch: expected {item['id']}, got {record.get('id')}")
        missing = [field for field in ATOM_FIELDS if field not in record]
        _require(not missing, f"record {item['id']} missing fields: {', '.join(missing)}")
        _require(record["polarity"] in POLARITIES, f"record {item['id']} has invalid polarity {record['polarity']!r}")
        _require(record["modality"] in MODALITIES, f"record {item['id']} has invalid modality {record['modality']!r}")
        reason = record["abstention_reason"]
        _require(reason is None or reason in ABSTENTION_CODES, f"record {item['id']} has invalid abstention_reason {reason!r}")
        if reason is not None:
            _require(
                record["subject"] is None and record["predicate"] is None and record["object"] is None and record["polarity"] == "uncertain",
                f"record {item['id']} abstains but carries a parse",
            )
        text = item["text"]
        annotated.append(AnnotatedAtom(
            id=item["id"],
            text=text,
            occurrence_id=f"atom-{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}",
            span=(0, len(text)),
            **{field: record[field] for field in ATOM_FIELDS},
            grammar_version=GRAMMAR_VERSION,
            source=SOURCE_TAG,
            annotator_model=model_name,
            annotator_version=ANNOTATOR_VERSION,
            prompt_hash=digest,
        ))
    return annotated


def batches(items: Sequence[dict], size: int = DEFAULT_BATCH_SIZE) -> Iterable[Sequence[dict]]:
    _require(size > 0, "batch size must be positive")
    for start in range(0, len(items), size):
        yield items[start:start + size]


def load_items(path: str | Path) -> list[dict]:
    """Read {id, text} records from JSONL or CSV; headline column may be `text` or `headline`."""
    source = Path(path)
    if source.suffix == ".csv":
        with source.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
    else:
        rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
    items = []
    for index, row in enumerate(rows):
        text = row.get("text") or row.get("headline")
        _require(bool(text), f"row {index} has no text/headline field")
        items.append({"id": row.get("id", index), "text": text})
    return items
