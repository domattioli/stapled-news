"""Unit tests for stage gates."""

import pytest
from stapled.db import connect
from stapled.gates import GateError, assert_corpus_passed, assert_recovery_passed, corroboration_label


def test_assert_corpus_passed_valid(tmp_path):
    """Test that assert_corpus_passed passes on PASSED corpus."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'PASSED')")
    corpus_id = cursor.lastrowid
    conn.commit()

    # Should not raise
    assert_corpus_passed(conn, corpus_id)


def test_assert_corpus_passed_pending(tmp_path):
    """Test that assert_corpus_passed raises on pending corpus."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'pending')")
    corpus_id = cursor.lastrowid
    conn.commit()

    with pytest.raises(GateError):
        assert_corpus_passed(conn, corpus_id)


def test_assert_corpus_passed_rejected(tmp_path):
    """Test that assert_corpus_passed raises on REJECTED corpus."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'REJECTED')")
    corpus_id = cursor.lastrowid
    conn.commit()

    with pytest.raises(GateError):
        assert_corpus_passed(conn, corpus_id)


def test_assert_corpus_passed_not_found(tmp_path):
    """Test that assert_corpus_passed raises when corpus doesn't exist."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    with pytest.raises(GateError):
        assert_corpus_passed(conn, 999)


def test_assert_recovery_passed_valid(tmp_path):
    """Test that assert_recovery_passed passes with PASS verdict."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'PASSED')")
    corpus_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO inference_run (created_at, corpus_id, status) VALUES (?, ?, 'converged')",
        ("2024-01-01", corpus_id),
    )
    run_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO recovery_report (run_id, corpus_id, verdict) VALUES (?, ?, 'PASS')",
        (run_id, corpus_id),
    )
    conn.commit()

    # Should not raise
    assert_recovery_passed(conn)


def test_assert_recovery_passed_no_report(tmp_path):
    """Test that assert_recovery_passed raises without any report."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    with pytest.raises(GateError):
        assert_recovery_passed(conn)


def test_assert_recovery_passed_fail_verdict(tmp_path):
    """Test that assert_recovery_passed raises on FAIL verdict."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    cursor = conn.execute("INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'PASSED')")
    corpus_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO inference_run (created_at, corpus_id, status) VALUES (?, ?, 'converged')",
        ("2024-01-01", corpus_id),
    )
    run_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO recovery_report (run_id, corpus_id, verdict) VALUES (?, ?, 'FAIL')",
        (run_id, corpus_id),
    )
    conn.commit()

    with pytest.raises(GateError):
        assert_recovery_passed(conn)


def test_corroboration_label_triangulated(tmp_path):
    """Test corroboration_label returns 'triangulated' for 2+ outlets."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create outlets
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet1_id = cursor.lastrowid
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet2', 1)")
    outlet2_id = cursor.lastrowid

    # Create articles
    cursor = conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status) VALUES (?, ?, 'ok')",
        (outlet1_id, "http://ex.com/1"),
    )
    article1_id = cursor.lastrowid
    cursor = conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status) VALUES (?, ?, 'ok')",
        (outlet2_id, "http://ex.com/2"),
    )
    article2_id = cursor.lastrowid

    # Create event
    cursor = conn.execute("INSERT INTO event (label) VALUES (?)", ("test",))
    event_id = cursor.lastrowid

    # Create claims
    cursor = conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.0, 0.9)",
        (article1_id, event_id),
    )
    cursor = conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.0, 0.9)",
        (article2_id, event_id),
    )
    conn.commit()

    label = corroboration_label(conn, event_id)
    assert label == "triangulated"


def test_corroboration_label_uncorroborated(tmp_path):
    """Test corroboration_label returns 'uncorroborated' for single outlet."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create outlet
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid

    # Create article
    conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status) VALUES (?, ?, 'ok')",
        (outlet_id, "http://ex.com/1"),
    )
    article_id = cursor.lastrowid

    # Create event
    cursor = conn.execute("INSERT INTO event (label) VALUES (?)", ("test",))
    event_id = cursor.lastrowid

    # Create claim
    cursor = conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.0, 0.9)",
        (article_id, event_id),
    )
    conn.commit()

    label = corroboration_label(conn, event_id)
    assert label == "uncorroborated"


def test_corroboration_label_dedup_clusters(tmp_path):
    """Test corroboration_label uses dedup_cluster_id when available."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create single outlet
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet_id = cursor.lastrowid

    # Create two articles with same dedup_cluster_id
    conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status, dedup_cluster_id) VALUES (?, ?, 'ok', 1)",
        (outlet_id, "http://ex.com/1"),
    )
    article1_id = cursor.lastrowid
    conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status, dedup_cluster_id) VALUES (?, ?, 'ok', 1)",
        (outlet_id, "http://ex.com/2"),
    )
    article2_id = cursor.lastrowid

    # Create event
    cursor = conn.execute("INSERT INTO event (label) VALUES (?)", ("test",))
    event_id = cursor.lastrowid

    # Create claims
    cursor = conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.0, 0.9)",
        (article1_id, event_id),
    )
    cursor = conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.0, 0.9)",
        (article2_id, event_id),
    )
    conn.commit()

    # Should be uncorroborated because both articles in same dedup_cluster
    label = corroboration_label(conn, event_id)
    assert label == "uncorroborated"


def test_corroboration_label_two_outlets_shared_wire_copy(tmp_path):
    """Two DIFFERENT outlets whose only articles share one dedup_cluster_id
    (a verbatim wire copy) must not count as independent corroboration."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet1_id = cursor.lastrowid
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet2', 1)")
    outlet2_id = cursor.lastrowid

    # Same dedup_cluster_id (7) across the two outlets: one shared wire copy.
    cursor = conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status, dedup_cluster_id) VALUES (?, ?, 'ok', 7)",
        (outlet1_id, "http://ex.com/a"),
    )
    article1_id = cursor.lastrowid
    cursor = conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status, dedup_cluster_id) VALUES (?, ?, 'ok', 7)",
        (outlet2_id, "http://ex.com/b"),
    )
    article2_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO event (label) VALUES (?)", ("test",))
    event_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.0, 0.9)",
        (article1_id, event_id),
    )
    conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.0, 0.9)",
        (article2_id, event_id),
    )
    conn.commit()

    # 2 distinct outlets but only 1 distinct dedup-collapsed source -> not triangulated.
    label = corroboration_label(conn, event_id)
    assert label == "uncorroborated"


def test_corroboration_label_two_outlets_two_clusters(tmp_path):
    """Two different outlets with two distinct dedup clusters ARE independent
    corroboration."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet1', 1)")
    outlet1_id = cursor.lastrowid
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES ('outlet2', 1)")
    outlet2_id = cursor.lastrowid

    cursor = conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status, dedup_cluster_id) VALUES (?, ?, 'ok', 7)",
        (outlet1_id, "http://ex.com/a"),
    )
    article1_id = cursor.lastrowid
    cursor = conn.execute(
        "INSERT INTO article (outlet_id, url, ingest_status, dedup_cluster_id) VALUES (?, ?, 'ok', 8)",
        (outlet2_id, "http://ex.com/b"),
    )
    article2_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO event (label) VALUES (?)", ("test",))
    event_id = cursor.lastrowid

    conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.0, 0.9)",
        (article1_id, event_id),
    )
    conn.execute(
        "INSERT INTO claim (article_id, event_id, certainty, valence, extraction_score) "
        "VALUES (?, ?, 0.5, 0.0, 0.9)",
        (article2_id, event_id),
    )
    conn.commit()

    label = corroboration_label(conn, event_id)
    assert label == "triangulated"
