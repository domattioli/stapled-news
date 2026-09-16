"""Pure staged-command handlers, kept separate from Typer for deterministic tests."""

import json
from dataclasses import asdict

from stapled.analyze.atomic_evaluation import evaluate_annotations
from stapled.analyze.atomic_match import match_atoms
from stapled.analyze.atomic_profiles import outlet_profile
from stapled.analyze.atomic_summary import build_scus
from stapled.extract.atomic import Atom, extract_headline
from stapled.infer.atomic_em import publication_gate


def extraction_payload(headline: str) -> str:
    """Return deterministic extraction JSON; abstentions are data, never guesses."""
    return json.dumps({"atoms": [asdict(atom) for atom in extract_headline(headline)]}, sort_keys=True)


def _atoms(records: list[dict]) -> list[Atom]:
    """Decode previously emitted atom JSON only; malformed records are refused."""
    try:
        return [Atom(**{**record, "span": tuple(record["span"])}) for record in records]
    except (KeyError, TypeError) as error:
        raise ValueError(f"invalid atomic occurrence payload: {error}") from error


def matching_payload(records: list[dict], event_id: str | int, aspect: str) -> str:
    atoms = _atoms(records)
    return json.dumps({"relations": [asdict(relation) for relation in match_atoms(atoms, event_id, aspect)]}, sort_keys=True)


def summary_payload(records: list[dict]) -> str:
    atoms = _atoms(records)
    return json.dumps({"scus": [asdict(scu) for scu in build_scus(atoms)]}, sort_keys=True)


def profile_payload(outlet: str, family: str, observations: dict[str, str], classifications: dict[str, str]) -> str:
    return json.dumps(asdict(outlet_profile(outlet, family, observations, classifications)), sort_keys=True)


def evaluation_payload(pilot: int, heldout: int, adjudicated: int, metrics: dict) -> str:
    return json.dumps(asdict(evaluate_annotations(pilot, heldout, adjudicated, metrics)), sort_keys=True)


def estimator_status_payload(primary: float, controls: list[float], adjudicated: int) -> str:
    return json.dumps({"status": publication_gate(primary, controls, adjudicated)}, sort_keys=True)
