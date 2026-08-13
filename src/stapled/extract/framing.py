"""Framing metadata extraction: hedging, certainty, valence, attribution."""

import re
import sqlite3


# Hedging lexicon
STRONG_HEDGE = ["might", "could", "may", "appears", "seems"]
WEAK_HEDGE = ["allegedly", "reportedly", "claims"]
ATTRIBUTION_PHRASES = {
    "official": ["officials said", "spokesman", "statement", "confirmed"],
    "anonymous-source": ["sources said", "aides said", "according to sources"],
    "secondhand": ["according to", "per", "via"],
}

# Sentiment words
POSITIVE_WORDS = [
    "won", "victory", "triumph", "success", "approved", "supported",
    "passed", "agreed", "thriving", "growing", "improving",
]
NEGATIVE_WORDS = [
    "lost", "defeat", "failure", "rejected", "opposed", "killed",
    "arrested", "died", "attacked", "declining", "falling",
]


def update_framing_for_article(
    conn: sqlite3.Connection,
    article_id: int,
    body: str,
) -> dict[str, int]:
    """
    Update framing metadata (hedging, certainty, valence, attribution)
    for all claims from an article. Returns {claims_updated: int}.
    """
    cursor = conn.execute(
        "SELECT id, actor, action, object FROM claim WHERE article_id = ?",
        (article_id,),
    )
    claims = cursor.fetchall()

    count = 0
    for claim_id, actor, action, obj in claims:
        if not action:
            continue

        # Build claim text for analysis
        claim_text = f"{actor or ''} {action} {obj or ''}".strip()

        # Extract framing
        hedging, certainty = _extract_hedging_certainty(body, claim_text)
        valence = _extract_valence(claim_text)
        attribution = _extract_attribution(body, claim_text)

        # Update claim
        conn.execute(
            """UPDATE claim
               SET hedging = ?, certainty = ?, valence = ?, attribution = ?
               WHERE id = ?""",
            (hedging, certainty, valence, attribution, claim_id),
        )
        count += 1

    conn.commit()
    return {"claims_updated": count}


def update_all_framing(
    conn: sqlite3.Connection, article_ids: list[int] | None = None
) -> dict[str, int]:
    """
    Update framing for claims without checking article.

    The hedging='none' OR certainty=0.5 filter is meant to pick out
    not-yet-framed claims, but framing an unhedged claim also PRODUCES
    hedging='none' (certainty=1.0 doesn't match, but plenty of claims land
    at certainty=0.5 via one strong hedge) - so it re-matches its own
    output and callers that loop (train_stream, once per batch) would
    re-frame the whole accumulated corpus every call. Pass article_ids to
    scope the update to a known batch instead of relying on that filter.
    """
    if article_ids is not None:
        if not article_ids:
            return {"claims_updated": 0}
        placeholders = ",".join("?" * len(article_ids))
        cursor = conn.execute(
            f"""
            SELECT DISTINCT a.id, a.body
            FROM article a
            JOIN claim c ON a.id = c.article_id
            WHERE a.id IN ({placeholders})
            ORDER BY a.id
        """,
            article_ids,
        )
    else:
        cursor = conn.execute(
            """
            SELECT DISTINCT a.id, a.body
            FROM article a
            JOIN claim c ON a.id = c.article_id
            WHERE c.hedging = 'none' OR c.certainty = 0.5
            ORDER BY a.id
        """
        )

    total = {"claims_updated": 0}
    for article_id, body in cursor.fetchall():
        counts = update_framing_for_article(conn, article_id, body)
        total["claims_updated"] += counts["claims_updated"]

    return total


def _extract_hedging_certainty(
    text: str, claim_text: str
) -> tuple[str, float]:
    """
    Determine hedging level (none/weak/strong) and certainty [0.05, 1.0].
    Certainty: 1.0 - 0.25*weak_hits - 0.5*strong_hits, clipped to [0.05, 1.0].
    """
    claim_lower = claim_text.lower()

    strong_hits = sum(
        1 for h in STRONG_HEDGE if re.search(r"\b" + h + r"\b", claim_lower)
    )
    weak_hits = sum(
        1 for h in WEAK_HEDGE if re.search(r"\b" + h + r"\b", claim_lower)
    )

    # Determine hedging level
    if strong_hits > 0:
        hedging = "strong"
    elif weak_hits > 0:
        hedging = "weak"
    else:
        hedging = "none"

    # Compute certainty
    certainty = 1.0 - 0.25 * weak_hits - 0.5 * strong_hits
    certainty = max(0.05, min(1.0, certainty))

    return hedging, certainty


def _extract_valence(claim_text: str) -> float:
    """
    Extract valence from claim text: mean of positive/negative word occurrences.
    Returns float in [-1, 1].
    """
    claim_lower = claim_text.lower()

    positive_count = sum(
        1 for w in POSITIVE_WORDS if re.search(r"\b" + w + r"\b", claim_lower)
    )
    negative_count = sum(
        1 for w in NEGATIVE_WORDS if re.search(r"\b" + w + r"\b", claim_lower)
    )

    if positive_count + negative_count == 0:
        return 0.0

    valence = (positive_count - negative_count) / (positive_count + negative_count)
    return max(-1.0, min(1.0, valence))


def _extract_attribution(text: str, claim_text: str) -> str:
    """
    Determine attribution type: 'direct', 'official', 'anonymous-source', 'secondhand'.
    """
    text_lower = text.lower()

    # Check official
    for phrase in ATTRIBUTION_PHRASES["official"]:
        if re.search(r"\b" + phrase + r"\b", text_lower):
            return "official"

    # Check anonymous-source
    for phrase in ATTRIBUTION_PHRASES["anonymous-source"]:
        if re.search(r"\b" + phrase + r"\b", text_lower):
            return "anonymous-source"

    # Check secondhand
    for phrase in ATTRIBUTION_PHRASES["secondhand"]:
        if re.search(r"\b" + phrase + r"\b", text_lower):
            return "secondhand"

    return "direct"
