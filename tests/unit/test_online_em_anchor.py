"""Unit tests for online EM anchor clamping."""

from stapled.db import connect
from stapled.infer.online_em import OnlineEM


def test_online_em_anchor_clamping(tmp_path):
    """Test anchor clamping: P(s=true_state)≈0.99 when anchor present."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    outlet_ids = [1, 2]
    em = OnlineEM(outlet_ids)
    em.connect(conn)

    # Create event first
    cursor = conn.execute("INSERT INTO event (corpus_id, label, true_state) VALUES (NULL, 'Test', 1)")
    event_id = cursor.lastrowid

    # Insert anchor for event with true_state=1
    conn.execute(
        "INSERT INTO anchor (event_id, true_state) VALUES (?, ?)",
        (event_id, 1),
    )
    conn.commit()

    # Create event with conflicting claims
    events = [
        {
            "event_id": event_id,
            "claims": [
                {"outlet_id": 1, "observation": 0, "certainty": 0.9},  # Says false
                {"outlet_id": 2, "observation": 0, "certainty": 0.9},  # Says false
            ],
        }
    ]

    posteriors = em.e_step_batch(events)

    # Anchor should force P(s=1) ≈ 0.99
    p_s0, p_s1 = posteriors[event_id]
    assert p_s1 > 0.98, f"Expected P(s=1)>0.98 with anchor, got {p_s1}"
    assert p_s0 < 0.02, f"Expected P(s=0)<0.02 with anchor, got {p_s0}"


def test_online_em_anchor_false_state(tmp_path):
    """Test anchor clamping for true_state=0."""
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    outlet_ids = [1, 2]
    em = OnlineEM(outlet_ids)
    em.connect(conn)

    # Create event first
    cursor = conn.execute("INSERT INTO event (corpus_id, label, true_state) VALUES (NULL, 'Test', 0)")
    event_id = cursor.lastrowid

    # Insert anchor with true_state=0
    conn.execute(
        "INSERT INTO anchor (event_id, true_state) VALUES (?, ?)",
        (event_id, 0),
    )
    conn.commit()

    # Create event where all outlets report true (state=1)
    events = [
        {
            "event_id": event_id,
            "claims": [
                {"outlet_id": 1, "observation": 1, "certainty": 0.95},
                {"outlet_id": 2, "observation": 1, "certainty": 0.95},
            ],
        }
    ]

    posteriors = em.e_step_batch(events)

    # Anchor should force P(s=0) ≈ 0.99
    p_s0, p_s1 = posteriors[event_id]
    assert p_s0 > 0.98, f"Expected P(s=0)>0.98 with anchor=0, got {p_s0}"
    assert p_s1 < 0.02, f"Expected P(s=1)<0.02 with anchor=0, got {p_s1}"
