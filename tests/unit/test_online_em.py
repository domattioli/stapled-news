"""Tests for online EM."""

from stapled.db import connect
from stapled.infer.online_em import OnlineEM
from stapled.infer.em import run_em
from stapled.infer.model import RunConfig


def test_online_em_single_batch_vs_em(tmp_path):
    """REGRESSION: single batch online EM ≈ full batch EM (delta < 0.15)."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Create test data: 3 outlets, 5 events
    outlet_ids = []
    for i in range(3):
        cursor = conn.execute(
            "INSERT INTO outlet (name, is_synthetic) VALUES (?, 1)", (f"outlet{i}",)
        )
        outlet_ids.append(cursor.lastrowid)

    cursor = conn.execute(
        "INSERT INTO corpus (seed, params_json, validation_status) VALUES (42, '{}', 'PASSED')"
    )
    corpus_id = cursor.lastrowid
    conn.commit()

    # Create 5 events with known true states
    true_states = [1, 0, 1, 0, 1]
    for event_idx, true_state in enumerate(true_states):
        cursor = conn.execute(
            "INSERT INTO event (corpus_id, label, true_state) VALUES (?, ?, ?)",
            (corpus_id, f"Event {event_idx}", true_state),
        )
        event_id = cursor.lastrowid

        # All outlets report correctly (perfect accuracy)
        for outlet_id in outlet_ids:
            cursor = conn.execute(
                "INSERT INTO article (outlet_id, corpus_id, url, ingest_status) "
                "VALUES (?, ?, ?, 'ok')",
                (outlet_id, corpus_id, f"http://ex.com/{outlet_id}/{event_idx}"),
            )
            article_id = cursor.lastrowid

            action = "occurred" if true_state else "did-not-occur"
            cursor = conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty, valence, extraction_score) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (article_id, event_id, action, 0.9, 0.0, 1.0),
            )

    conn.commit()

    # Run batch EM
    config = RunConfig(max_iter=50, tol=1e-6, restarts=1)
    run_id = run_em(conn, corpus_id, config, is_real=False)

    # Get baseline EM params
    cursor = conn.execute(
        "SELECT est_reliability FROM run_outlet_result WHERE run_id = ? ORDER BY outlet_id",
        (run_id,),
    )
    baseline_reliabilities = [row[0] for row in cursor.fetchall()]

    # Now run online EM with single batch
    online_em = OnlineEM(outlet_ids)
    online_em.connect(conn)

    # Prepare events batch
    events_batch = []
    for event_id in range(1, 6):
        claims = []
        true_state = true_states[event_id - 1]
        for outlet_id in outlet_ids:
            claims.append({
                "outlet_id": outlet_id,
                "observation": true_state,
                "certainty": 0.9,
            })
        events_batch.append({"event_id": event_id, "claims": claims})

    # E-step
    posteriors = online_em.e_step_batch(events_batch)

    # Compute M-step stats
    batch_stats = {oid: {
        "sens": 0.5, "spec": 0.5,
        "exp_tp": 0.0, "exp_fp": 0.0,
        "exp_tn": 0.0, "exp_fn": 0.0,
        "n_obs": 0.0
    } for oid in outlet_ids}

    for event_id, claims in [(e["event_id"], e["claims"]) for e in events_batch]:
        p_s1 = posteriors[event_id][1]
        for claim in claims:
            outlet_id = claim["outlet_id"]
            obs = claim["observation"]
            if obs == 1:
                batch_stats[outlet_id]["exp_tp"] += p_s1
                batch_stats[outlet_id]["exp_fn"] += 1 - p_s1
            else:
                batch_stats[outlet_id]["exp_tn"] += 1 - p_s1
                batch_stats[outlet_id]["exp_fp"] += p_s1
            batch_stats[outlet_id]["n_obs"] += 1

    batch_stats["ll"] = 0.0

    # Accumulate
    online_em.accumulate(batch_stats, 0)

    # Get online EM reliabilities
    online_reliabilities = online_em.m_params()[2]
    online_rel_list = [online_reliabilities[oid] for oid in outlet_ids]

    # Check deltas < 0.15 (online vs batch EM can have variation)
    for i, oid in enumerate(outlet_ids):
        delta = abs(baseline_reliabilities[i] - online_rel_list[i])
        assert delta < 0.15, f"Outlet {oid} reliability delta {delta} >= 0.15"


def test_online_em_anchor_clamping(tmp_path):
    """Test anchor true_state clamping."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    outlet_ids = [1, 2, 3]
    online_em = OnlineEM(outlet_ids)
    online_em.connect(conn)

    # Create anchor
    event_id = 1
    conn.execute(
        "INSERT INTO event (corpus_id, label, true_state) VALUES (NULL, 'test', 1)"
    )
    conn.execute(
        "INSERT INTO anchor (event_id, true_state, source) VALUES (?, 1, 'test')",
        (event_id,),
    )
    conn.commit()

    # E-step with contradictory claims
    events = [{
        "event_id": event_id,
        "claims": [
            {"outlet_id": 1, "observation": 0, "certainty": 0.9},  # says 0
            {"outlet_id": 2, "observation": 0, "certainty": 0.9},  # says 0
        ]
    }]

    posteriors = online_em.e_step_batch(events)
    p_s0, p_s1 = posteriors[event_id]

    # Should be clamped to anchor: true_state=1 → p_s1 high
    assert p_s1 > 0.9, f"Anchor clamping failed: p_s1={p_s1}"
    assert p_s0 < 0.1, f"Anchor clamping failed: p_s0={p_s0}"


def test_online_em_convergence_check(tmp_path):
    """Test convergence tracking."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    outlet_ids = [1, 2]
    online_em = OnlineEM(outlet_ids, tolerance=1e-5)
    online_em.connect(conn)

    # First check should return False (no prior)
    assert not online_em.converged()

    # Update sens slightly
    online_em.sens[1] += 0.001
    online_em.sens[2] += 0.001

    # Should still not converged (deltas > tolerance)
    assert not online_em.converged(l2_tol=1e-9)

    # Update slightly and converge
    online_em.sens[1] += 0.00000001
    online_em.sens[2] += 0.00000001

    # Should converge (L2 norm small)
    assert online_em.converged(l2_tol=1e-5)
