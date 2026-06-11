"""Smoke tests: verify modules import and basic functionality."""

import pytest


def test_imports_online_em():
    """Test online_em module imports."""
    from stapled.infer.online_em import OnlineEM
    assert OnlineEM is not None


def test_imports_align_incremental():
    """Test align_incremental module imports."""
    from stapled.infer.align_incremental import align_incremental
    assert align_incremental is not None


def test_imports_stream():
    """Test stream module imports."""
    from stapled.ingest.stream import iter_remote_lines, dedup_new_articles
    assert iter_remote_lines is not None
    assert dedup_new_articles is not None


def test_imports_visualization():
    """Test visualization module imports."""
    from stapled.viz.online_convergence import online_convergence
    assert online_convergence is not None


def test_imports_cli():
    """Test CLI imports including new train-stream command."""
    from stapled.cli import app, train_stream
    assert app is not None
    assert train_stream is not None


def test_database_migrations():
    """Test that migrations apply without error."""
    from stapled.db import connect
    import tempfile
    import os

    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        conn = connect(db_path)

        # Check that streaming tables exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN "
            "('source_cursor', 'em_state', 'em_suffstats', 'anchor', 'simhash_bucket', "
            "'event_centroid', 'tfidf_vocab', 'reliability_snapshot')"
        )
        tables = {row[0] for row in cursor.fetchall()}

        expected = {
            'source_cursor', 'em_state', 'em_suffstats', 'anchor',
            'simhash_bucket', 'event_centroid', 'tfidf_vocab', 'reliability_snapshot'
        }

        assert expected.issubset(tables), f"Missing tables: {expected - tables}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
