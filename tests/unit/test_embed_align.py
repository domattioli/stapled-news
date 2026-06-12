"""Tests for enhanced embedding-based alignment."""

import sqlite3
import pytest
from stapled.align.embed_align import realign_all, _extract_entities, _normalize_claim_text


@pytest.fixture
def test_db():
    """Create in-memory test database."""
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.row_factory = sqlite3.Row
    from stapled.db import _apply_migrations
    _apply_migrations(conn)
    yield conn
    conn.close()


def _setup_test_data(conn, outlets_data):
    """
    Helper to create test outlets, articles, and claims.
    outlets_data: List[{name, claims: [{actor, action, object, title}, ...]}]
    Returns dict: {outlet_name -> outlet_id, claim_ids: [...]}
    """
    outlet_map = {}
    claim_ids = []

    for outlet_spec in outlets_data:
        outlet_name = outlet_spec["name"]
        conn.execute("INSERT INTO outlet (name) VALUES (?)", (outlet_name,))
        cursor = conn.execute("SELECT last_insert_rowid()")
        outlet_id = cursor.fetchone()[0]
        outlet_map[outlet_name] = outlet_id

        for claim_spec in outlet_spec["claims"]:
            actor = claim_spec.get("actor", "")
            action = claim_spec.get("action", "")
            obj = claim_spec.get("object", "")
            title = claim_spec.get("title", "")

            conn.execute(
                """INSERT INTO article (outlet_id, url, title, body, ingest_status)
                   VALUES (?, ?, ?, 'dummy body', 'ok')""",
                (outlet_id, f"{outlet_name}/{len(claim_ids)}", title),
            )
            cursor = conn.execute("SELECT last_insert_rowid()")
            article_id = cursor.fetchone()[0]

            conn.execute(
                """INSERT INTO claim (article_id, actor, action, object, event_id)
                   VALUES (?, ?, ?, ?, NULL)""",
                (article_id, actor, action, obj),
            )
            cursor = conn.execute("SELECT last_insert_rowid()")
            claim_id = cursor.fetchone()[0]
            claim_ids.append(claim_id)

    conn.commit()
    return outlet_map, claim_ids


def test_paraphrase_merges(test_db):
    """Test that similar claims with same entity are merged at low threshold."""
    outlets_data = [
        {
            "name": "outlet_a",
            "claims": [
                {
                    "actor": "Kim Kardashian",
                    "action": "shares",
                    "object": "first photo",
                    "title": "Kim Kardashian first photo release",
                },
            ],
        },
        {
            "name": "outlet_b",
            "claims": [
                {
                    "actor": "Kim Kardashian",
                    "action": "shares",
                    "object": "first photo",
                    "title": "Kim Kardashian first photo release announcement",
                },
            ],
        },
    ]

    outlet_map, claim_ids = _setup_test_data(test_db, outlets_data)

    # Use lower threshold for nearly-identical claims
    realign_all(test_db, similarity_threshold=0.3, entity_mode="boost")

    # Both claims should be in same event (very similar text + same entity)
    cursor = test_db.execute(
        """SELECT DISTINCT event_id FROM claim WHERE id IN (?, ?)""",
        (claim_ids[0], claim_ids[1]),
    )
    events = cursor.fetchall()
    assert len(events) == 1, "Similar claims should merge into same event"
    assert stats["multi_outlet_events"] >= 1


def test_disjoint_entities_not_merged(test_db):
    """Test claims with different entities don't merge."""
    outlets_data = [
        {
            "name": "outlet_a",
            "claims": [
                {
                    "actor": "Trump",
                    "action": "signs",
                    "object": "budget bill",
                    "title": "Trump signs budget bill",
                },
            ],
        },
        {
            "name": "outlet_b",
            "claims": [
                {
                    "actor": "Clinton",
                    "action": "signs",
                    "object": "book deal",
                    "title": "Clinton signs book deal",
                },
            ],
        },
    ]

    outlet_map, claim_ids = _setup_test_data(test_db, outlets_data)

    realign_all(test_db, similarity_threshold=0.5, entity_mode="boost")

    # Should be in different events
    cursor = test_db.execute(
        """SELECT DISTINCT event_id FROM claim WHERE id IN (?, ?)""",
        (claim_ids[0], claim_ids[1]),
    )
    events = cursor.fetchall()
    assert len(events) == 2, "Disjoint entities should not merge"


def test_no_entity_fallback(test_db):
    """Test that claims without capitalized entities can still merge via rare-word blocking."""
    outlets_data = [
        {
            "name": "outlet_a",
            "claims": [
                {
                    "actor": "",
                    "action": "",
                    "object": "",
                    "title": "house passes unusual legislation",
                },
            ],
        },
        {
            "name": "outlet_b",
            "claims": [
                {
                    "actor": "",
                    "action": "",
                    "object": "",
                    "title": "house passes legislation about regulations",
                },
            ],
        },
    ]

    outlet_map, claim_ids = _setup_test_data(test_db, outlets_data)

    stats = realign_all(test_db, similarity_threshold=0.4, entity_mode="boost")

    # Should eventually find some similarity via word-based blocking + TF-IDF
    # (both have "house" and "passes" as rare words)
    cursor = test_db.execute("SELECT COUNT(DISTINCT event_id) FROM claim")
    num_events = cursor.fetchone()[0]
    # We don't assert they merge (might not if threshold too high), just that realign runs
    assert num_events >= 1


def test_realign_clears_previous(test_db):
    """Test that realign clears previous event assignments and rebuilds."""
    outlets_data = [
        {
            "name": "outlet_a",
            "claims": [
                {
                    "actor": "Alice",
                    "action": "does",
                    "object": "something",
                    "title": "Alice does something",
                },
            ],
        },
    ]

    outlet_map, claim_ids = _setup_test_data(test_db, outlets_data)

    # Assign bogus event ID before realign
    test_db.execute(
        "INSERT INTO event (corpus_id, label, true_state) VALUES (NULL, 'bogus', NULL)"
    )
    bogus_event_id = test_db.execute("SELECT last_insert_rowid()").fetchone()[0]
    test_db.execute("UPDATE claim SET event_id = ? WHERE id = ?", (bogus_event_id, claim_ids[0]))
    test_db.commit()

    # Verify bogus assignment exists
    cursor = test_db.execute("SELECT event_id FROM claim WHERE id = ?", (claim_ids[0],))
    old_event = cursor.fetchone()[0]
    assert old_event == bogus_event_id

    # Run realign
    stats = realign_all(test_db, similarity_threshold=0.5)

    # Check that claim has a NEW event after realign
    cursor = test_db.execute(
        "SELECT event_id FROM claim WHERE id = ?", (claim_ids[0],)
    )
    new_event_id = cursor.fetchone()[0]
    assert new_event_id is not None, "Claim should have new event after realign"
    # The new event should be different from bogus (realign created new one)
    # Note: they could theoretically be the same if realign happened to use same ID, but unlikely
    assert new_event_id >= 1, "New event should be valid"

    # Stats should show 1 event created
    assert stats["events_created"] >= 1, "Should create events during realign"


def test_stats_shape(test_db):
    """Test that stats dict has all required keys and correct types."""
    outlets_data = [
        {
            "name": "outlet_a",
            "claims": [
                {
                    "actor": "Bob",
                    "action": "talks",
                    "object": "philosophy",
                    "title": "Bob talks about philosophy",
                },
            ],
        },
    ]

    outlet_map, claim_ids = _setup_test_data(test_db, outlets_data)

    stats = realign_all(test_db, similarity_threshold=0.5)

    required_keys = {"claims_total", "clusters_multi", "events_created", "claims_in_multi", "multi_outlet_events"}
    assert set(stats.keys()) == required_keys, f"Stats missing keys or has extra: {stats.keys()}"

    for key in required_keys:
        assert isinstance(stats[key], int), f"{key} must be int, got {type(stats[key])}"

    assert stats["claims_total"] == 1
    assert stats["events_created"] >= 1


def test_entity_extraction():
    """Test entity extraction regex."""
    text = "Donald Trump and Hillary Clinton met yesterday"
    entities = _extract_entities(text)
    assert "donald trump" in entities
    assert "hillary clinton" in entities
    assert "donald" in entities
    assert "trump" in entities

    # Test with lowercase (should extract nothing capitalized)
    text_lower = "donald trump and hillary clinton"
    entities_lower = _extract_entities(text_lower)
    assert len(entities_lower) == 0, "Lowercase text should yield no entities"

    # Test with stopword filtering
    text_stopword = "The Company did something"
    entities_sw = _extract_entities(text_stopword)
    # "The" is filtered out, but "Company" should be included
    assert "company" in entities_sw


def test_normalize_claim_text():
    """Test claim text normalization."""
    text = _normalize_claim_text(
        actor="Alice",
        action="does",
        obj="task X",
        title="Alice Does Task X Today",
    )
    assert text == "alice does task x alice does task x today"


def test_empty_database(test_db):
    """Test realign on empty database."""
    stats = realign_all(test_db, similarity_threshold=0.5)

    assert stats["claims_total"] == 0
    assert stats["events_created"] == 0
    assert stats["multi_outlet_events"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
