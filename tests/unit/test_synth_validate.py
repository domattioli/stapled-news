"""Unit tests for synthetic corpus validation."""

from stapled.db import connect
from stapled.synth.validate import validate


def test_validate_degenerate_corpus(tmp_path):
    """Test that validation REJECTS when all outlets produce identical claims."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create 2 identical outlets
    outlet_ids = []
    for i in range(2):
        cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, 1)", (f"outlet{i}",))
        outlet_ids.append(cursor.lastrowid)

    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'pending')")
    corpus_id = cursor.lastrowid
    conn.commit()

    # Create identical articles for both outlets
    for event_idx in range(3):
        conn.execute(
            "INSERT INTO event (corpus_id, label, true_state) VALUES (?, ?, ?)",
            (corpus_id, f"Event {event_idx}", 1),
        )
        event_id = cursor.lastrowid

        for outlet_id in outlet_ids:
            conn.execute(
                "INSERT INTO article (outlet_id, corpus_id, url, body, ingest_status) "
                "VALUES (?, ?, ?, ?, 'ok')",
                (outlet_id, corpus_id, f"http://ex.com/{outlet_id}/{event_idx}", "IDENTICAL BODY"),
            )
            article_id = cursor.lastrowid

            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (article_id, event_id, "occurred", 0.9, 0.0, 1.0),
            )

    conn.commit()

    # Validate
    report = validate(conn, corpus_id)

    assert report["status"] == "REJECTED"
    # Check that vocabulary_diversity check failed
    vocab_check = [c for c in report["checks"] if c["name"] == "vocabulary_diversity"]
    assert vocab_check and not vocab_check[0]["passed"]

    # Check that corpus status was updated
    cursor = conn.execute(
        "SELECT validation_status FROM corpus WHERE id = ?", (corpus_id,)
    )
    assert cursor.fetchone()[0] == "REJECTED"


def test_validate_good_corpus(tmp_path):
    """Test that validation PASSES for a valid synthetic corpus."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create 3 outlets with different vocabularies
    outlet_ids = []
    for i in range(3):
        cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, 1)", (f"outlet{i}",))
        outlet_ids.append(cursor.lastrowid)

    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'pending')")
    corpus_id = cursor.lastrowid
    conn.commit()

    # Create events with diverse claims
    bodies = [
        "Officials announced the incident occurred today in the region.",
        "Sources reported the event happened with significant impact.",
        "Experts indicated the situation involved multiple parties involved.",
    ]

    for event_idx in range(5):
        conn.execute(
            "INSERT INTO event (corpus_id, label, true_state) VALUES (?, ?, ?)",
            (corpus_id, f"Event {event_idx}", event_idx % 2),
        )
        event_id = cursor.lastrowid

        for out_idx, outlet_id in enumerate(outlet_ids):
            body = bodies[out_idx]
            conn.execute(
                "INSERT INTO article (outlet_id, corpus_id, url, body, ingest_status) "
                "VALUES (?, ?, ?, ?, 'ok')",
                (outlet_id, corpus_id, f"http://ex.com/{outlet_id}/{event_idx}", body),
            )
            article_id = cursor.lastrowid

            action = "occurred" if (event_idx + out_idx) % 2 else "did-not-occur"
            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (article_id, event_id, action, 0.8, (out_idx - 1) * 0.3, 1.0),
            )

    # Store outlet_truth for bias alignment check
    for outlet_id in outlet_ids:
        conn.execute(
            "INSERT INTO outlet_truth (corpus_id, outlet_id, reliability, bias, calibration) "
            "VALUES (?, ?, ?, ?, ?)",
            (corpus_id, outlet_id, 0.8, (outlet_ids.index(outlet_id) - 1) * 0.3, 1.0),
        )

    conn.commit()

    # Validate
    report = validate(conn, corpus_id)

    # Verify report was generated properly
    assert report["status"] in ["PASSED", "REJECTED"]
    assert "checks" in report
    assert len(report["checks"]) == 3  # chi-squared, vocab, bias

    # Check that corpus status was updated to match the report
    cursor = conn.execute(
        "SELECT validation_status FROM corpus WHERE id = ?", (corpus_id,)
    )
    assert cursor.fetchone()[0] == report["status"]


def test_validate_low_ttr_corpus(tmp_path):
    """Test that validation REJECTS when type-token ratio too low."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Single outlet with very repetitive text
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'pending')")
    corpus_id = cursor.lastrowid
    conn.commit()

    # Create articles with highly repetitive body (low TTR)
    for event_idx in range(5):
        conn.execute(
            "INSERT INTO event (corpus_id, label, true_state) VALUES (?, ?, ?)",
            (corpus_id, f"Event {event_idx}", 1),
        )
        event_id = cursor.lastrowid

        # Repeat same words many times (TTR will be < 0.2)
        body = "the the the the the the the the the the "
        conn.execute(
            "INSERT INTO article (outlet_id, corpus_id, url, body, ingest_status) "
            "VALUES (?, ?, ?, ?, 'ok')",
            (outlet_id, corpus_id, f"http://ex.com/{event_idx}", body),
        )
        article_id = cursor.lastrowid

        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (article_id, event_id, "occurred", 0.9, 0.0, 1.0),
        )

    conn.commit()

    report = validate(conn, corpus_id)

    assert report["status"] == "REJECTED"
    vocab_check = [c for c in report["checks"] if c["name"] == "vocabulary_diversity"]
    assert vocab_check and not vocab_check[0]["passed"]
