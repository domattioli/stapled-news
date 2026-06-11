"""Tests for fractional dedup-aware voting in OnlineEM."""

import numpy as np
from stapled.db import connect
from stapled.infer.online_em import OnlineEM


def test_weight_singleton(tmp_path):
    """Event with all NULL dedup_cluster_id behaves identically to dedup_voting=False."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create test outlets
    outlet_ids = []
    for i in range(2):
        cursor = conn.execute(
            "INSERT INTO outlet (name, is_synthetic) VALUES (?, 1)", (f"outlet{i}",)
        )
        outlet_ids.append(cursor.lastrowid)
    conn.commit()

    # Create event
    cursor = conn.execute(
        "INSERT INTO event (corpus_id, label, true_state) VALUES (NULL, 'test', 1)"
    )
    event_id = cursor.lastrowid

    # Create 2 articles with NULL dedup_cluster_id
    article_ids = []
    for i, outlet_id in enumerate(outlet_ids):
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, corpus_id, url, ingest_status, dedup_cluster_id) "
            "VALUES (?, NULL, ?, 'ok', NULL)",
            (outlet_id, f"http://ex.com/{i}"),
        )
        article_ids.append(cursor.lastrowid)

    # Create claims
    for article_id in article_ids:
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
            "VALUES (?, ?, 'occurred', 0.8, 0.0, 1.0)",
            (article_id, event_id),
        )
    conn.commit()

    # Run E-step with dedup_voting=True
    em_dedup = OnlineEM(outlet_ids, conn=conn, dedup_voting=True)
    result_dedup = em_dedup._e_step_from_ids([event_id])
    posterior_dedup = result_dedup["posteriors"][event_id]

    # Run E-step with dedup_voting=False
    em_no_dedup = OnlineEM(outlet_ids, conn=conn, dedup_voting=False)
    result_no_dedup = em_no_dedup._e_step_from_ids([event_id])
    posterior_no_dedup = result_no_dedup["posteriors"][event_id]

    # Should be nearly identical (within numerical precision)
    assert np.allclose(posterior_dedup, posterior_no_dedup, atol=1e-8), \
        f"Posteriors differ: dedup={posterior_dedup}, no_dedup={posterior_no_dedup}"


def test_weight_cluster_split(tmp_path):
    """Event with 3 articles sharing dedup_cluster_id gets each 1/3 weight."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create test outlets
    outlet_ids = []
    for i in range(4):
        cursor = conn.execute(
            "INSERT INTO outlet (name, is_synthetic) VALUES (?, 1)", (f"outlet{i}",)
        )
        outlet_ids.append(cursor.lastrowid)
    conn.commit()

    # Create event
    cursor = conn.execute(
        "INSERT INTO event (corpus_id, label, true_state) VALUES (NULL, 'test', 1)"
    )
    event_id = cursor.lastrowid

    # Create 3 articles with dedup_cluster_id=1, plus 1 independent article
    article_ids = []
    for i, outlet_id in enumerate(outlet_ids):
        dedup_cluster = 1 if i < 3 else None
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, corpus_id, url, ingest_status, dedup_cluster_id) "
            "VALUES (?, NULL, ?, 'ok', ?)",
            (outlet_id, f"http://ex.com/{i}", dedup_cluster),
        )
        article_ids.append(cursor.lastrowid)

    # Create claims (all say observation=1)
    for article_id in article_ids:
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
            "VALUES (?, ?, 'occurred', 0.8, 0.0, 1.0)",
            (article_id, event_id),
        )
    conn.commit()

    # Run E-step with dedup_voting=True (cluster claims get 1/3 weight each)
    em_dedup = OnlineEM(outlet_ids, conn=conn, dedup_voting=True)
    result_dedup = em_dedup._e_step_from_ids([event_id])
    posterior_dedup = result_dedup["posteriors"][event_id]

    # Create the same event data as dicts with explicit weights for comparison
    # The 3 clustered outlets get weight 1/3, the independent outlet gets weight 1.0
    events_dicts = [{
        "event_id": event_id,
        "claims": [
            {"outlet_id": outlet_ids[0], "observation": 1, "certainty": 0.8, "weight": 1.0/3},
            {"outlet_id": outlet_ids[1], "observation": 1, "certainty": 0.8, "weight": 1.0/3},
            {"outlet_id": outlet_ids[2], "observation": 1, "certainty": 0.8, "weight": 1.0/3},
            {"outlet_id": outlet_ids[3], "observation": 1, "certainty": 0.8, "weight": 1.0},
        ]
    }]

    em_dict = OnlineEM(outlet_ids, conn=conn, dedup_voting=False)
    posterior_dict = em_dict._e_step_from_dicts(events_dicts)[event_id]

    # Should match
    assert np.allclose(posterior_dedup, posterior_dict, atol=1e-8), \
        f"Posteriors differ: dedup={posterior_dedup}, dict={posterior_dict}"


def test_off_mode_identity(tmp_path):
    """dedup_voting=False on clustered fixture equals explicit weights=1.0."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create test outlets
    outlet_ids = []
    for i in range(3):
        cursor = conn.execute(
            "INSERT INTO outlet (name, is_synthetic) VALUES (?, 1)", (f"outlet{i}",)
        )
        outlet_ids.append(cursor.lastrowid)
    conn.commit()

    # Create event
    cursor = conn.execute(
        "INSERT INTO event (corpus_id, label, true_state) VALUES (NULL, 'test', 1)"
    )
    event_id = cursor.lastrowid

    # Create articles with dedup clustering
    article_ids = []
    for i, outlet_id in enumerate(outlet_ids):
        dedup_cluster = 5 if i < 2 else None
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, corpus_id, url, ingest_status, dedup_cluster_id) "
            "VALUES (?, NULL, ?, 'ok', ?)",
            (outlet_id, f"http://ex.com/{i}", dedup_cluster),
        )
        article_ids.append(cursor.lastrowid)

    # Create claims (all say observation=1, true_state=1)
    for article_id in article_ids:
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
            "VALUES (?, ?, 'occurred', 0.7, 0.0, 1.0)",
            (article_id, event_id),
        )
    conn.commit()

    # Run E-step with dedup_voting=False
    em_no_dedup = OnlineEM(outlet_ids, conn=conn, dedup_voting=False)
    result_no_dedup = em_no_dedup._e_step_from_ids([event_id])
    posterior_no_dedup = result_no_dedup["posteriors"][event_id]

    # Create dict version with all weights=1.0
    events_dicts = [{
        "event_id": event_id,
        "claims": [
            {"outlet_id": outlet_ids[0], "observation": 1, "certainty": 0.7, "weight": 1.0},
            {"outlet_id": outlet_ids[1], "observation": 1, "certainty": 0.7, "weight": 1.0},
            {"outlet_id": outlet_ids[2], "observation": 1, "certainty": 0.7, "weight": 1.0},
        ]
    }]

    em_dict = OnlineEM(outlet_ids, conn=conn, dedup_voting=False)
    posterior_dict = em_dict._e_step_from_dicts(events_dicts)[event_id]

    # Should match
    assert np.allclose(posterior_no_dedup, posterior_dict, atol=1e-8), \
        f"Posteriors differ: no_dedup={posterior_no_dedup}, dict={posterior_dict}"


def test_suffstats_fractional(tmp_path):
    """Suffstats reflect fractional weights correctly."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create test outlets
    outlet_ids = []
    for i in range(3):
        cursor = conn.execute(
            "INSERT INTO outlet (name, is_synthetic) VALUES (?, 1)", (f"outlet{i}",)
        )
        outlet_ids.append(cursor.lastrowid)
    conn.commit()

    # Create event
    cursor = conn.execute(
        "INSERT INTO event (corpus_id, label, true_state) VALUES (NULL, 'test', 1)"
    )
    event_id = cursor.lastrowid

    # Create 3 articles with same dedup_cluster_id
    article_ids = []
    for i, outlet_id in enumerate(outlet_ids):
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, corpus_id, url, ingest_status, dedup_cluster_id) "
            "VALUES (?, NULL, ?, 'ok', ?)",
            (outlet_id, f"http://ex.com/{i}", 10),  # All in cluster 10
        )
        article_ids.append(cursor.lastrowid)

    # Create claims (all say observation=1, which matches true_state=1)
    for article_id in article_ids:
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
            "VALUES (?, ?, 'occurred', 0.9, 0.0, 1.0)",
            (article_id, event_id),
        )
    conn.commit()

    # Run E-step with dedup_voting=True
    em_dedup = OnlineEM(outlet_ids, conn=conn, dedup_voting=True)
    result_dedup = em_dedup._e_step_from_ids([event_id])
    batch_stats = result_dedup["batch_stats"]

    # Each outlet should have fractional n_obs: since all 3 claims are clustered,
    # each gets weight 1/3. The sum of n_obs contributions should be roughly one article's worth.
    total_n_obs = sum(batch_stats[oid]["n_obs"] for oid in outlet_ids)

    # With 3 clustered claims, each weight=1/3, they should sum to ~1 effective observation
    # (accounting for the posterior probability p_s1)
    assert total_n_obs > 0, "n_obs should be positive"
    # Each outlet gets p_s1 * cert * (1/3) ≈ p_s1 * 0.9 * (1/3)
    # Total ≈ 3 * p_s1 * 0.9 * (1/3) = p_s1 * 0.9
    # With high p_s1 (observation matches true state), this should be < 1
    assert total_n_obs < 1.5, f"Total n_obs {total_n_obs} should be fractional (~0.3-0.9)"

    # Verify individual outlet n_obs is small (1/3 of one article's contribution)
    for oid in outlet_ids:
        assert batch_stats[oid]["n_obs"] < 0.5, \
            f"Outlet {oid} n_obs {batch_stats[oid]['n_obs']} should be < 0.5 (fractional)"
