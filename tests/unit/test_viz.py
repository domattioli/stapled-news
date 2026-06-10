"""Tests for visualization."""

import tempfile
from pathlib import Path
import json

from stapled.db import connect, insert_and_get_id
from stapled.viz.charts import render_all


def test_render_charts_creates_files():
    """Test that charts are created for a valid run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        conn = connect(str(db_path))

        # Create minimal run data
        outlet_id = insert_and_get_id(
            conn, "INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("test", 0)
        )

        event_id = insert_and_get_id(
            conn, "INSERT INTO event (corpus_id, label) VALUES (NULL, ?)", ("test_event",)
        )

        run_id = insert_and_get_id(
            conn,
            """INSERT INTO inference_run
               (created_at, corpus_id, claim_set_hash, status, iterations, log_likelihood, config_json)
               VALUES (?, NULL, ?, ?, ?, ?, ?)""",
            (
                "2024-01-01T00:00:00",
                "hash123",
                "converged",
                10,
                -100.5,
                json.dumps({"ll_trace": [-200, -150, -120, -110, -105, -103, -102, -101, -100.5]}),
            ),
        )

        insert_and_get_id(
            conn,
            """INSERT INTO run_outlet_result
               (run_id, outlet_id, est_reliability, est_bias, est_calibration)
               VALUES (?, ?, ?, ?, ?)""",
            (run_id, outlet_id, 0.85, 0.1, 1.0),
        )

        insert_and_get_id(
            conn,
            """INSERT INTO run_event_result
               (run_id, event_id, inferred_state, confidence, corroboration, weighting_json)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (run_id, event_id, 1, 0.9, "triangulated", json.dumps([])),
        )

        out_dir = Path(tmpdir) / "output"

        filenames = render_all(conn, run_id, str(out_dir))

        # Should create at least some charts
        assert len(filenames) > 0

        # Check files exist and have run_id prefix
        for filename in filenames:
            filepath = out_dir / filename
            assert filepath.exists(), f"Chart {filename} not created"
            # Verify filename includes run_id prefix
            assert f"run_{run_id}_" in filename, f"Chart {filename} missing run_id prefix"
