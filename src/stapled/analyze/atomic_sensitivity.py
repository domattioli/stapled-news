"""Deterministic descriptive sensitivity ranges."""


def leave_one_out_ranges(values: dict[str, tuple[float, str]]) -> tuple[float | None, float | None]:
    if not values:
        return (None, None)
    scores = [value[0] for _, value in sorted(values.items())]
    return (min(scores), max(scores))


def owner_sensitivity(families: dict[str, list[str]]) -> dict[str, tuple[str, ...]]:
    """Return all declared home-stratum alternatives; no ownership collapse is implied."""
    return {family: tuple(sorted(set(stratum_list))) for family, stratum_list in sorted(families.items())}


def effective_n(weights: list[float]) -> float:
    return sum(weights) ** 2 / sum(weight * weight for weight in weights) if weights else 0.0


def sensitivity_ranges(values: dict[str, tuple[float, str, str]]) -> dict[str, tuple[float | None, float | None]]:
    """Expose leave-group, leave-stratum, and owner alternatives without collapsing ownership."""
    def interval(items):
        scores = [item[0] for item in items]
        return (min(scores), max(scores)) if scores else (None, None)
    all_values = list(values.values())
    by_stratum = {name: [item for item in all_values if item[1] != name] for name in {item[1] for item in all_values}}
    by_owner = {name: [item for item in all_values if item[2] != name] for name in {item[2] for item in all_values}}
    return {"leave_group": interval(all_values), "leave_stratum": interval([score for group in by_stratum.values() for score in group]), "owner": interval([score for group in by_owner.values() for score in group])}
