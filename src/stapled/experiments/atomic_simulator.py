"""Seeded stress simulator separating candidate discovery from conditional support."""

import random


def run_scenario(config: dict) -> dict:
    n = int(config["n"])
    rng = random.Random(int(config["seed"]))
    found = [rng.random() < float(config["candidate_discovery_rate"]) for _ in range(n)]
    supports = [rng.random() < float(config["support_rate"]) for item in found if item]
    return {
        "n": n,
        "n_found": sum(found),
        "candidate_discovery": sum(found) / n if n else 0.0,
        "conditional_support": sum(supports) / len(supports) if supports else None,
    }


def sweep(config: dict, dimensions: list[str]) -> dict[str, dict]:
    """Run deterministic labelled stress scenarios; dimensions remain metadata, not results claims."""
    return {dimension: run_scenario({**config, "seed": int(config["seed"]) + index}) for index, dimension in enumerate(dimensions)}
