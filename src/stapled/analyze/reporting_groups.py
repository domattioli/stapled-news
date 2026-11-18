"""Conservative exact-headline reporting groups with retained provenance."""

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class ReportingGroup:
    group_id: str
    member_article_ids: tuple[str, ...]
    member_outlets: tuple[str, ...]
    method: str
    owner: str | None
    lineage_evidence: str | None = None
    owner_sensitivity: bool = False


def _normalized_headline(headline: str) -> str:
    return re.sub(r"\s+", " ", headline.strip().casefold())


def build_reporting_groups(rows: list[dict]) -> list[ReportingGroup]:
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        key = f"lineage:{row['lineage_id']}" if row.get("lineage_id") else f"headline:{_normalized_headline(str(row['headline']))}"
        grouped[key].append(row)
    result = []
    for key, members in sorted(grouped.items()):
        members = sorted(members, key=lambda member: str(member["article_id"]))
        owners = {member.get("owner") for member in members}
        owner_sensitivity = len(owners) == 1 and next(iter(owners)) is not None
        result.append(
            ReportingGroup(
                f"rg-{hashlib.sha256(key.encode()).hexdigest()[:16]}",
                tuple(str(member["article_id"]) for member in members),
                tuple(str(member["outlet"]) for member in members),
                "demonstrated_lineage" if members[0].get("lineage_id") else ("exact_headline" if len(members) > 1 else "singleton"),
                next(iter(owners)) if len(owners) == 1 else None,
                str(members[0]["lineage_id"]) if members[0].get("lineage_id") else None,
                owner_sensitivity,
            )
        )
    return sorted(result, key=lambda group: group.member_article_ids)
