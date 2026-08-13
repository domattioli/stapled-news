"""Lightweight rule-based claim extraction (no spaCy)."""

import re
import sqlite3
from typing import List, Optional, Dict, Tuple

from stapled.db import insert_and_get_id


# Curated verb lexicon
VERB_LEXICON = [
    # Political / hard-news (past tense)
    "said", "announced", "voted", "passed", "signed", "killed", "won",
    "banned", "approved", "rejected", "claimed", "denied", "arrested",
    "fired", "resigned", "met", "attacked", "proposed", "opposed",
    "urged", "warned", "demanded", "called", "declared", "ruled",
    "accused", "admitted", "confirmed", "revealed", "released", "launched",
    "filed", "sued", "died", "blamed", "praised", "criticized", "slammed",
    # Present-tense headline forms (headlines favor simple present)
    "says", "announces", "votes", "passes", "signs", "kills", "wins",
    "bans", "approves", "rejects", "claims", "denies", "arrests",
    "fires", "resigns", "meets", "attacks", "proposes", "opposes",
    "urges", "warns", "demands", "calls", "declares", "rules",
    "accuses", "admits", "confirms", "reveals", "releases", "launches",
    "files", "sues", "dies", "blames", "praises", "criticizes", "slams",
    # Entertainment / lifestyle coverage
    "shares", "shared", "posts", "posted", "debuts", "debuted",
    "welcomes", "welcomed", "marries", "married", "splits", "split",
    "dating", "engaged", "expecting", "spotted", "responds", "responded",
    "celebrates", "celebrated", "joins", "joined", "leaves", "left",
    "quits", "quit", "drops", "dropped", "hosts", "hosted",
    "opens", "opened", "breaks", "broke", "returns", "returned",
    "shows", "showed", "talks", "talked", "speaks", "spoke",
]

# Month names for date regex
MONTHS = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
WEEKDAYS = r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|Mon|Tue|Wed|Thu|Fri|Sat|Sun)"

# Known countries/cities (simplified list)
LOCATIONS = {
    "united states": "USA",
    "u.s.": "USA",
    "us": "USA",
    "washington": "Washington, DC",
    "new york": "New York",
    "london": "London",
    "paris": "Paris",
    "china": "China",
    "russia": "Russia",
    "iran": "Iran",
    "israel": "Israel",
}

# Magnitude units
MAGNITUDE_UNITS = [
    "percent", "percentage", "%",
    "million", "billion", "trillion",
    "dollars", "pounds", "euros",
    "people", "troops", "soldiers",
    "votes", "seats", "points",
]


def extract_claims_from_article(
    conn: sqlite3.Connection,
    article_id: int,
    title: str,
    body: str,
) -> Dict[str, int]:
    """
    Extract claims from article. Returns {claims_created: int}.
    """
    # Extract sentences from title + first 3 sentences of body
    text_to_process = title + " " + _get_first_n_sentences(body, 3)

    # Split into sentences
    sentences = _split_sentences(text_to_process)

    counts = {"claims_created": 0}

    for sentence in sentences:
        if len(sentence.strip()) < 10:
            continue

        claim = _extract_claim_from_sentence(sentence, body)
        if claim and claim.get("action"):  # Must have at least action
            insertion_count = _insert_claim(conn, article_id, claim)
            counts["claims_created"] += insertion_count

    conn.commit()
    return counts


def extract_all_unextracted(
    conn: sqlite3.Connection,
    article_ids: Optional[List[int]] = None,
) -> Dict[str, int]:
    """Extract claims from articles without claims. Returns summary counts.

    Pass article_ids to scope extraction to a known batch (mirrors
    update_all_framing) so callers that loop per-batch (train_stream) don't
    silently extract claims for out-of-batch articles that framing and
    alignment never see.
    """
    if article_ids is not None:
        if not article_ids:
            return {"articles_processed": 0, "claims_created": 0}
        placeholders = ",".join("?" * len(article_ids))
        cursor = conn.execute(
            f"""
            SELECT DISTINCT a.id, a.title, a.body
            FROM article a
            LEFT JOIN claim c ON a.id = c.article_id
            WHERE c.id IS NULL AND a.id IN ({placeholders})
            ORDER BY a.id
        """,
            article_ids,
        )
    else:
        cursor = conn.execute(
            """
        SELECT DISTINCT a.id, a.title, a.body
        FROM article a
        LEFT JOIN claim c ON a.id = c.article_id
        WHERE c.id IS NULL
        ORDER BY a.id
    """
        )

    rows = cursor.fetchall()
    total_counts = {"articles_processed": 0, "claims_created": 0}

    for article_id, title, body in rows:
        if not title or not body:
            continue
        counts = extract_claims_from_article(conn, article_id, title, body)
        total_counts["claims_created"] += counts["claims_created"]
        total_counts["articles_processed"] += 1

    return total_counts


def _get_first_n_sentences(text: str, n: int) -> str:
    """Extract first n sentences from text."""
    sentences = _split_sentences(text)
    return " ".join(sentences[:n])


def _split_sentences(text: str) -> List[str]:
    """Simple sentence splitting on . ! ?"""
    # Split on sentence-ending punctuation
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return [s.strip() for s in sentences if s.strip()]


def _extract_claim_from_sentence(sentence: str, article_body: str) -> Optional[Dict]:
    """Extract one claim from a sentence."""
    sentence = sentence.strip()

    # Extract actor
    actor = _extract_actor(sentence)

    # Extract action
    action = _extract_action(sentence)

    # Determine polarity (negation)
    negation = _has_negation(sentence)
    if negation and action:
        action = f"not-{action}"

    # Extract object (remainder clause, truncated)
    obj = _extract_object(sentence, actor, action)

    # Extract time reference
    time_ref = _extract_time_ref(sentence)

    # Extract location
    location = _extract_location(sentence, article_body)

    # Extract magnitude
    magnitude_value, magnitude_unit = _extract_magnitude(sentence)

    if not action:
        return None

    return {
        "actor": actor,
        "action": action,
        "object": obj,
        "time_ref": time_ref,
        "location": location,
        "magnitude_value": magnitude_value,
        "magnitude_unit": magnitude_unit,
    }


def _extract_actor(sentence: str) -> Optional[str]:
    """Extract leading capitalized span or known entity."""
    # Look for consecutive capitalized words at sentence start
    match = re.match(r"^([A-Z][a-zA-Z\s&]+?)(?:\s+(?:said|announced|voted|denied|claimed|warned))", sentence)
    if match:
        return match.group(1).strip()

    # Look for acronyms
    match = re.match(r"^([A-Z]{2,})\s+", sentence)
    if match:
        return match.group(1)

    # Default: first capitalized word
    match = re.match(r"^([A-Z][a-zA-Z]+)", sentence)
    if match:
        return match.group(1)

    return None


def _extract_action(sentence: str) -> Optional[str]:
    """Extract first verb from lexicon."""
    sentence_lower = sentence.lower()
    for verb in VERB_LEXICON:
        if re.search(r"\b" + verb + r"\b", sentence_lower):
            return verb
    return None


def _extract_object(sentence: str, actor: Optional[str], action: Optional[str]) -> Optional[str]:
    """Extract object: clause following action, truncated to 80 chars."""
    if not action:
        return None

    # Find action in sentence
    action_base = action.replace("not-", "")
    match = re.search(r"\b" + action_base + r"\b\s+(.+)", sentence, re.IGNORECASE)
    if match:
        obj = match.group(1).strip()
        if len(obj) > 80:
            obj = obj[:77] + "..."
        return obj

    return None


def _extract_time_ref(sentence: str) -> Optional[str]:
    """Extract time reference: month names, weekdays, or 'on <Month> <d>'."""
    # Try month patterns
    for month in ["January", "February", "March", "April", "May", "June",
                   "July", "August", "September", "October", "November", "December",
                   "Jan", "Feb", "Mar", "Apr", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]:
        if month in sentence:
            return month

    # Try weekday patterns
    for weekday in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
        if weekday in sentence:
            return weekday

    # Try "on <Month> <d>" pattern
    match = re.search(rf"on\s+{MONTHS}\s+(\d{{1,2}})", sentence, re.IGNORECASE)
    if match:
        return f"on {match.group(1)} {match.group(2)}"

    # Try year
    match = re.search(r"\b(20\d{2})\b", sentence)
    if match:
        return match.group(1)

    return None


def _extract_location(sentence: str, article_body: str) -> Optional[str]:
    """Extract location: try known list, else dateline city from body."""
    # Try known locations
    for location_key, location_name in LOCATIONS.items():
        if re.search(r"\b" + location_key + r"\b", sentence, re.IGNORECASE):
            return location_name

    # Try dateline from article body
    match = re.match(r"^([A-Z][A-Za-z\s,]+?)\s*\(", article_body)
    if match:
        city = match.group(1).strip()
        if "," not in city and len(city) < 50:
            return city

    return None


def _extract_magnitude(sentence: str) -> Tuple[Optional[float], Optional[str]]:
    """Extract magnitude: number + unit from MAGNITUDE_UNITS."""
    for unit in MAGNITUDE_UNITS:
        # Look for <number> <unit> pattern
        pattern = rf"([\d,.]+)\s*{unit}"
        match = re.search(pattern, sentence, re.IGNORECASE)
        if match:
            try:
                value = float(match.group(1).replace(",", ""))
                return value, unit
            except ValueError:
                pass

    return None, None


def _has_negation(sentence: str) -> bool:
    """Check for negation patterns: 'did not', 'denied', 'refused', etc."""
    negation_patterns = [
        r"\b(did\s+)?not\b",
        r"\bdenied\b",
        r"\brefused\b",
        r"\bfailed\s+to\b",
        r"\bno\s+",
    ]
    return any(re.search(p, sentence, re.IGNORECASE) for p in negation_patterns)


def _insert_claim(conn: sqlite3.Connection, article_id: int, claim: Dict) -> int:
    """Insert claim into database."""
    insert_and_get_id(
        conn,
        """INSERT INTO claim
           (article_id, event_id, actor, action, object, time_ref, location,
            magnitude_value, magnitude_unit, hedging, certainty, valence,
            attribution, extraction_score)
           VALUES (?, NULL, ?, ?, ?, ?, ?, ?, ?, 'none', 0.5, 0.0, 'direct', 0.5)""",
        (
            article_id,
            claim.get("actor"),
            claim.get("action"),
            claim.get("object"),
            claim.get("time_ref"),
            claim.get("location"),
            claim.get("magnitude_value"),
            claim.get("magnitude_unit"),
        ),
    )
    return 1
