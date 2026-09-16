"""Canonical Atomic Consensus export with conservative publication gates."""

from copy import deepcopy
from dataclasses import asdict

from stapled.analyze.atomic_run import semantic_hash


def build_export(analysis: dict, events: list[dict]) -> dict:
    """Build schema v1 payload and attach a digest of its semantic contents."""
    normalized_events = deepcopy(events)
    for event in normalized_events:
        event.setdefault("coverage", {}).setdefault("missing_reasons", [])
        for fact in event.get("facts", []):
            fact.setdefault("missing_reasons", [])
            fact.setdefault("modeled_core_membership", None)
    output = {
        "schema_version": "1.0",
        "analysis": deepcopy(analysis),
        "events": sorted(normalized_events, key=lambda event: str(event.get("event_id", ""))),
    }
    hashes = output["analysis"].setdefault("hashes", {})
    hashes["artifact_digests"] = {"atomic_consensus.json": semantic_hash(output)}
    return output


def validate_export(payload: dict) -> None:
    """Validate essential contract invariants without making a publication claim."""
    if payload.get("schema_version") != "1.0":
        raise ValueError("unsupported atomic export schema")
    analysis = payload.get("analysis")
    if not isinstance(analysis, dict):
        raise TypeError("analysis is required")
    required = {"run_id", "status", "corpus", "cutoff_at", "versions", "hashes", "panel", "estimator", "evaluation"}
    missing = required - analysis.keys()
    if missing:
        raise ValueError(f"analysis missing required fields: {sorted(missing)}")
    estimator = analysis["estimator"]
    if estimator.get("status") == "published" and analysis["evaluation"].get("status") != "pass":
        raise ValueError("published estimator requires evaluation pass")
    if estimator.get("mode") == "categorical_em" and estimator.get("status") == "published":
        counts = analysis.get("annotation_counts", {})
        if counts.get("heldout_actual", 0) < 80 or counts.get("adjudicated_actual", 0) < 80:
            raise ValueError("published estimator requires completed held-out adjudication")
    if analysis["panel"].get("unrated_policy") != "descriptive-excluded-primary":
        raise ValueError("primary panel must exclude unrated sources")
    for event in payload.get("events", []):
        _validate_event(event)


def _validate_event(event: dict) -> None:
    required = {"event_id", "as_of", "facts", "profiles", "coverage"}
    missing = required - event.keys()
    if missing:
        raise ValueError(f"event missing required fields: {sorted(missing)}")
    for fact in event["facts"]:
        for evidence in fact.get("evidence", []) + fact.get("conflicts", []):
            _validate_evidence(evidence, event["event_id"])


def _validate_evidence(evidence: dict, event_id: str | int) -> None:
    required = {"article_id", "outlet", "url", "headline", "occurrence_id", "reporting_group_id", "span", "span_convention", "scope", "relation", "rule"}
    missing = required - evidence.keys()
    if missing:
        raise ValueError(f"evidence missing required fields: {sorted(missing)}")
    start, end = evidence["span"]
    if evidence["span_convention"] != "utf8-codepoint-halfopen" or start < 0 or end < start:
        raise ValueError("invalid exact evidence span")
    if evidence["scope"].get("event_id") != event_id:
        raise ValueError("evidence event scope differs from event")
    if not evidence["url"].startswith(("https://", "http://")):
        raise ValueError("evidence URL must be absolute")


def profile_export(profile) -> dict:
    """Typed profile serializer excluding any global or scalar outlet judgement."""
    data = asdict(profile)
    data["leave_out"] = list(data["leave_out"])
    return data
