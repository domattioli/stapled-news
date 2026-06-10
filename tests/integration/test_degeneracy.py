"""Integration test: degeneracy handling (SC-006)."""

from stapled.db import connect
from stapled.infer.em import run_em
from stapled.infer.model import RunConfig
from stapled.gates import corroboration_label


def test_degeneracy_single_outlet(tmp_path):
    """Test that EM flags degeneracy when only one outlet provides claims."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Single outlet only
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'PASSED')")
    corpus_id = cursor.lastrowid
    conn.commit()

    # Create events with only one outlet reporting
    for event_idx in range(5):
        conn.execute(
            "INSERT INTO event (corpus_id, label, true_state) VALUES (?, ?, ?)",
            (corpus_id, f"Event {event_idx}", event_idx % 2),
        )
        event_id = cursor.lastrowid

        conn.execute(
            "INSERT INTO article (outlet_id, corpus_id, url, ingest_status) "
            "VALUES (?, ?, ?, 'ok')",
            (outlet_id, corpus_id, f"http://ex.com/{event_idx}"),
        )
        article_id = cursor.lastrowid

        action = "occurred" if (event_idx % 2) else "did-not-occur"
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (article_id, event_id, action, 0.9, 0.0, 1.0),
        )

    conn.commit()

    # Run EM
    config = RunConfig(max_iter=50, restarts=1)
    run_id = run_em(conn, corpus_id, config)

    # Check: run should be flagged degenerate
    cursor = conn.execute(
        "SELECT status FROM inference_run WHERE id = ?", (run_id,)
    )
    status = cursor.fetchone()[0]
    assert status == "degenerate", f"Single-outlet run should be degenerate, got {status}"


def test_nonconvergence_handling(tmp_path):
    """Test that EM flags nonconvergence when max iterations reached."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create noisy setup that won't converge quickly
    outlet_ids = []
    for i in range(5):
        cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, 1)", (f"outlet{i}",))
        outlet_ids.append(cursor.lastrowid)

    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'PASSED')")
    corpus_id = cursor.lastrowid
    conn.commit()

    # Create many conflicting events
    for event_idx in range(10):
        conn.execute(
            "INSERT INTO event (corpus_id, label, true_state) VALUES (?, ?, ?)",
            (corpus_id, f"Event {event_idx}", 1),
        )
        event_id = cursor.lastrowid

        for out_idx, outlet_id in enumerate(outlet_ids):
            conn.execute(
                "INSERT INTO article (outlet_id, corpus_id, url, ingest_status) "
                "VALUES (?, ?, ?, 'ok')",
                (outlet_id, corpus_id, f"http://ex.com/{out_idx}/{event_idx}"),
            )
            article_id = cursor.lastrowid

            # Create conflicting claims
            action = "occurred" if (out_idx % 2) else "did-not-occur"
            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (article_id, event_id, action, 0.7, 0.0, 1.0),
            )

    conn.commit()

    # Run EM with very low max_iter to force nonconvergence
    config = RunConfig(max_iter=2, restarts=1)
    run_id = run_em(conn, corpus_id, config)

    cursor = conn.execute(
        "SELECT status FROM inference_run WHERE id = ?", (run_id,)
    )
    status = cursor.fetchone()[0]
    # May be nonconverged or degenerate, but not converged
    assert status in ["nonconverged", "degenerate"]


def test_single_source_event_uncorroborated(tmp_path):
    """Test that single-source event is labeled uncorroborated (FR-015)."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Single outlet
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid

    # Create event
    cursor = conn.execute("INSERT INTO event (label) VALUES (?)", ("test",))
    event_id = cursor.lastrowid

    # Create article + claim
    conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status) VALUES (?, ?, 'ok')",
        (outlet_id, "http://ex.com/1"),
    )
    article_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.0, 0.9)",
        (article_id, event_id),
    )
    conn.commit()

    label = corroboration_label(conn, event_id)
    assert label == "uncorroborated"


def test_score_fails_on_low_accuracy(tmp_path):
    """Test that score returns FAIL when accuracy < 0.85."""
    from stapled.recover.score import score

    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Setup: corpus with inversed ground truth
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'PASSED')")
    corpus_id = cursor.lastrowid
    conn.commit()

    # Create events where inference will be wrong
    for event_idx in range(10):
        true_state = 1
        conn.execute(
            "INSERT INTO event (corpus_id, label, true_state) VALUES (?, ?, ?)",
            (corpus_id, f"Event {event_idx}", true_state),
        )
        event_id = cursor.lastrowid

        conn.execute(
            "INSERT INTO article (outlet_id, corpus_id, url, ingest_status) "
            "VALUES (?, ?, ?, 'ok')",
            (outlet_id, corpus_id, f"http://ex.com/{event_idx}"),
        )
        article_id = cursor.lastrowid

        # Claim opposite of ground truth
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
            "VALUES (?, ?, 'did-not-occur', 0.9, 0.0, 1.0)",
            (article_id, event_id),
        )

    conn.commit()

    # Run EM (will infer wrong states)
    config = RunConfig(max_iter=50, restarts=1)
    run_id = run_em(conn, corpus_id, config)

    # Score
    result = score(conn, run_id)
    assert result["verdict"] == "FAIL"
    assert result["state_accuracy"] < 0.85
