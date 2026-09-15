"""Immutable, deterministic metadata helpers for Atomic Consensus runs."""

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

_RUNTIME_FIELDS = {"generated_at", "runtime_at", "created_at", "canonical"}


def _semantic(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _semantic(item) for key, item in value.items() if key not in _RUNTIME_FIELDS}
    if isinstance(value, (list, tuple)):
        return [_semantic(item) for item in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize semantic data to stable UTF-8 JSON without runtime fields."""
    return json.dumps(_semantic(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def semantic_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def stable_scu_id(event_id: str | int, aspect: str, canonical_key: str) -> str:
    payload = f"{event_id}|{aspect}|{canonical_key}".encode()
    return f"scu-{hashlib.sha256(payload).hexdigest()[:16]}"


@dataclass(frozen=True)
class AtomicRun:
    """Semantic, immutable run identity; generated timestamps are deliberately absent."""

    run_id: str
    corpus_ref: str
    corpus_git_rev: str
    cutoff_at: str
    versions: tuple[tuple[str, str], ...]
    semantic_hash: str

    @classmethod
    def create(cls, run_id: str, corpus_ref: str, corpus_git_rev: str, cutoff_at: str, versions: dict[str, str]):
        required = {"parser", "rules", "aliases", "taxonomy", "panel"}
        missing = required - versions.keys()
        if missing:
            raise ValueError(f"missing run versions: {sorted(missing)}")
        items = tuple(sorted(versions.items()))
        payload = {"run_id": run_id, "corpus": {"ref": corpus_ref, "git_rev": corpus_git_rev}, "cutoff_at": cutoff_at, "versions": dict(items)}
        return cls(run_id, corpus_ref, corpus_git_rev, cutoff_at, items, semantic_hash(payload))

    def semantic_payload(self) -> dict:
        return {"run_id": self.run_id, "corpus": {"ref": self.corpus_ref, "git_rev": self.corpus_git_rev}, "cutoff_at": self.cutoff_at, "versions": dict(self.versions)}
