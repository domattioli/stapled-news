import json

import pytest

from stapled.analyze.atomic_annotate import (
    ANNOTATOR_VERSION,
    ATOM_FIELDS,
    SOURCE_TAG,
    SYSTEM_PROMPT,
    AnnotationError,
    batches,
    build_annotation_prompt,
    load_items,
    parse_annotation_response,
    prompt_hash,
)

BATCH = [{"id": 1, "text": "Government approves plan"}, {"id": 2, "text": "Reuters reports Government approves plan"}]


def _record(item_id, **overrides):
    base = {"id": item_id, "subject": "Government", "predicate": "approves", "object": "plan", "polarity": "affirmed", "modality": "asserted", "attribution": None, "quantity": None, "time": None, "location": None, "abstention_reason": None}
    return {**base, **overrides}


def _reply(*records):
    return json.dumps(list(records))


def test_prompt_puts_frozen_block_first_and_batch_last():
    prompt = build_annotation_prompt(BATCH)
    assert prompt.startswith(SYSTEM_PROMPT)
    assert prompt.rstrip().endswith(json.dumps([{"id": 1, "text": BATCH[0]["text"]}, {"id": 2, "text": BATCH[1]["text"]}]))
    assert build_annotation_prompt(BATCH[:1]).startswith(SYSTEM_PROMPT)


def test_prompt_block_a_is_byte_identical_across_batches():
    first = build_annotation_prompt(BATCH)
    second = build_annotation_prompt([{"id": 9, "text": "Senator alleges company broke law"}])
    assert first[:len(SYSTEM_PROMPT)] == second[:len(SYSTEM_PROMPT)]
    assert prompt_hash() == prompt_hash()


def test_empty_batch_is_refused():
    with pytest.raises(AnnotationError):
        build_annotation_prompt([])


def test_valid_reply_is_tagged_with_provenance_and_local_span():
    atoms = parse_annotation_response(_reply(_record(1), _record(2, modality="asserted_attributed", attribution="Reuters")), BATCH)
    assert [atom.id for atom in atoms] == [1, 2]
    assert atoms[0].span == (0, len(BATCH[0]["text"]))
    assert atoms[0].occurrence_id.startswith("atom-")
    assert (atoms[0].source, atoms[0].annotator_model, atoms[0].annotator_version) == (SOURCE_TAG, "fable", ANNOTATOR_VERSION)
    assert atoms[0].prompt_hash == prompt_hash()
    assert atoms[1].attribution == "Reuters"


def test_model_name_is_recorded_verbatim():
    atoms = parse_annotation_response(_reply(_record(1)), BATCH[:1], model_name="claude-fable-5-1")
    assert atoms[0].annotator_model == "claude-fable-5-1"


@pytest.mark.parametrize("raw", [
    "```json\n[]\n```",
    "Here are the atoms: []",
    json.dumps({"id": 1}),
])
def test_non_array_replies_are_refused(raw):
    with pytest.raises(AnnotationError):
        parse_annotation_response(raw, BATCH[:1])


def test_wrong_count_and_mismatched_id_are_refused():
    with pytest.raises(AnnotationError, match="expected 2 records"):
        parse_annotation_response(_reply(_record(1)), BATCH)
    with pytest.raises(AnnotationError, match="id mismatch"):
        parse_annotation_response(_reply(_record(7)), BATCH[:1])


def test_missing_field_is_named_in_the_error():
    partial = _record(1)
    del partial["quantity"]
    with pytest.raises(AnnotationError, match="quantity"):
        parse_annotation_response(_reply(partial), BATCH[:1])


def test_enum_violations_are_refused():
    with pytest.raises(AnnotationError, match="polarity"):
        parse_annotation_response(_reply(_record(1, polarity="false")), BATCH[:1])
    with pytest.raises(AnnotationError, match="modality"):
        parse_annotation_response(_reply(_record(1, modality="rumored")), BATCH[:1])
    with pytest.raises(AnnotationError, match="abstention_reason"):
        parse_annotation_response(_reply(_record(1, abstention_reason="too_hard")), BATCH[:1])


def test_abstention_must_not_carry_a_parse():
    with pytest.raises(AnnotationError, match="abstains but carries a parse"):
        parse_annotation_response(_reply(_record(1, abstention_reason="coordination")), BATCH[:1])
    clean = _record(1, abstention_reason="coordination", subject=None, predicate=None, object=None, polarity="uncertain")
    atom = parse_annotation_response(_reply(clean), BATCH[:1])[0]
    assert (atom.abstention_reason, atom.polarity, atom.subject) == ("coordination", "uncertain", None)


def test_atom_fields_match_the_deterministic_extractor_schema():
    from stapled.extract.atomic import Atom

    assert set(ATOM_FIELDS) <= set(Atom.__dataclass_fields__)
    assert "occurrence_id" not in ATOM_FIELDS and "span" not in ATOM_FIELDS


def test_batches_split_by_size_and_reject_non_positive():
    assert [len(group) for group in batches([{"id": i, "text": "x"} for i in range(5)], 2)] == [2, 2, 1]
    with pytest.raises(AnnotationError):
        list(batches(BATCH, 0))


def test_load_items_reads_jsonl_and_csv(tmp_path):
    jsonl = tmp_path / "in.jsonl"
    jsonl.write_text('{"id": "a", "text": "Government approves plan"}\n', encoding="utf-8")
    assert load_items(jsonl) == [{"id": "a", "text": "Government approves plan"}]
    csv_path = tmp_path / "in.csv"
    csv_path.write_text("id,headline\n7,Government signs deal\n", encoding="utf-8")
    assert load_items(csv_path) == [{"id": "7", "text": "Government signs deal"}]


def test_load_items_refuses_rows_without_text(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"id": 1}\n', encoding="utf-8")
    with pytest.raises(AnnotationError):
        load_items(bad)
