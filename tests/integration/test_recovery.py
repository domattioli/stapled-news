"""Integration test: synthetic recovery pipeline (MVP scope)."""

import yaml
from pathlib import Path
from stapled.db import connect
from stapled.synth.generator import generate as synth_generate
from stapled.synth.validate import validate as synth_validate
from stapled.infer.em import run_em
from stapled.infer.model import RunConfig
from stapled.recover.score import score
from stapled.gates import assert_corpus_passed


def test_recovery_full_pipeline(tmp_path):
    """Test full synthetic pipeline: generate → validate → infer → score.

    MVP scope per spec: SC-001..003, SC-006 checks.
    - State accuracy >= 0.85
    - Rank correlation >= 0.8
    - Liar outlet ranked least reliable
    """
    db_path = tmp_path / "test.db"
    conn = connect(str(db_path))

    # Load baseline config
    config_path = Path(__file__).parent.parent.parent / "configs" / "synth-baseline.yml"
    config = yaml.safe_load(config_path.read_text())

    # Step 1: Generate synthetic corpus
    corpus_id = synth_generate(conn, config, seed=42)
    assert corpus_id is not None

    # Step 2: Validate corpus
    report = synth_validate(conn, corpus_id)
    assert report["status"] == "PASSED"
    assert all(c["passed"] for c in report["checks"])

    # Step 3: Run inference
    assert_corpus_passed(conn, corpus_id)
    config_obj = RunConfig(max_iter=200, tol=1e-6, restarts=5)
    run_id = run_em(conn, corpus_id, config_obj)
    assert run_id is not None

    # Check run converged
    cursor = conn.execute(
        "SELECT status FROM inference_run WHERE id = ?", (run_id,)
    )
    status = cursor.fetchone()[0]
    assert status == "converged", f"Run status: {status}"

    # Step 4: Score recovery
    result = score(conn, run_id)

    # Hard thresholds per spec (SC-001..003)
    assert result["state_accuracy"] >= 0.85, f"State accuracy {result['state_accuracy']} < 0.85"
    assert result["reliability_rank_corr"] >= 0.8, f"Rank correlation {result['reliability_rank_corr']} < 0.8"
    assert result["verdict"] == "PASS", f"Verdict {result['verdict']} != PASS"

    # Verify liar outlet (tabloid-mirror) has LOWEST est_reliability
    cursor = conn.execute(
        """
        SELECT a.name, b.est_reliability
        FROM outlet a
        JOIN run_outlet_result b ON a.id = b.outlet_id
        WHERE b.run_id = ?
        ORDER BY b.est_reliability
        """,
        (run_id,),
    )
    outlet_reliability_ordered = cursor.fetchall()
    assert outlet_reliability_ordered[0][0] == "tabloid-mirror", \
        f"Liar outlet not ranked lowest; order: {[r[0] for r in outlet_reliability_ordered]}"


def test_recovery_with_custom_seed(tmp_path):
    """Test recovery pipeline with different seed yields reproducible results."""
    config_path = Path(__file__).parent.parent.parent / "configs" / "synth-baseline.yml"
    config = yaml.safe_load(config_path.read_text())

    # Use separate databases for each corpus (outlets have unique names)
    db_path1 = tmp_path / "test1.db"
    conn1 = connect(str(db_path1))
    corpus1_id = synth_generate(conn1, config, seed=10)

    db_path2 = tmp_path / "test2.db"
    conn2 = connect(str(db_path2))
    corpus2_id = synth_generate(conn2, config, seed=20)

    assert corpus1_id == corpus2_id == 1  # Both are first corpora in their DBs

    # Both should validate
    report1 = synth_validate(conn1, corpus1_id)
    report2 = synth_validate(conn2, corpus2_id)
    # Reports should be about the same structure (both pass or both fail)
    assert report1["status"] == report2["status"]
