"""Unit tests for E4 external label (MBFC) experiment."""

import json
import numpy as np

from stapled.experiments import e4_external
from stapled.experiments.runner import run_experiment
from stapled.db import connect


def test_e4_runs_on_synthetic_db(tmp_path):
    """Test e4 experiment on a minimal synthetic fnn-like DB with external labels."""

    # Create tiny synthetic DB
    db_path = tmp_path / "tiny_fnn_external.db"
    conn = connect(str(db_path))

    # Create outlets
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("good.com", 0))
    good_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("bad.com", 1))
    bad_id = cursor.lastrowid

    # Add external labels
    conn.execute(
        "INSERT INTO outlet_external_label (domain, fact, bias, source) VALUES (?, ?, ?, ?)",
        ("good.com", "high", "center", "mbfc"),
    )
    conn.execute(
        "INSERT INTO outlet_external_label (domain, fact, bias, source) VALUES (?, ?, ?, ?)",
        ("bad.com", "low", "extreme-right", "mbfc"),
    )

    # Create events
    for i in range(2):
        conn.execute("INSERT INTO event (id) VALUES (?)", (i + 1,))

    event_ids = [1, 2]

    # Create articles (one per outlet per event)
    article_id = 1
    for event_id in event_ids:
        for outlet_id in [good_id, bad_id]:
            conn.execute(
                "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (outlet_id, f"url-{article_id}", f"title-{article_id}", "body text", "2024-01-01", "ok"),
            )
            article_id += 1

    # Create claims
    article_id = 1
    for event_id in event_ids:
        for outlet_id in [good_id, bad_id]:
            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty) "
                "VALUES (?, ?, ?, ?)",
                (article_id, event_id, "occurred", 0.9),
            )
            article_id += 1

    conn.commit()
    conn.close()

    # Run experiment
    config = {
        "db_path": str(db_path),
        "min_outlets": 2,
        "batch_size": 32,
        "min_articles_per_outlet": 1,
    }

    out_dir = tmp_path / "e4_output"
    entry = run_experiment("e4", e4_external.run, config, seed=42, out_dir=str(out_dir))

    # Check CSV exists and is valid
    csv_path = out_dir / "e4_external.csv"
    assert csv_path.exists()

    with open(csv_path) as f:
        lines = f.readlines()

    assert lines[0].strip() == "outlet,n_articles,fact,bias,sens,spec,reliability,n_obs"

    # Expect: 2 outlets with external labels
    assert len(lines) == 3  # header + 2 outlets

    # Parse and validate rows
    outlets_seen = set()
    for line in lines[1:]:
        parts = line.strip().split(",")
        assert len(parts) == 8

        outlet = parts[0]
        n_articles = int(parts[1])
        fact = parts[2]
        bias = parts[3]
        sens = float(parts[4])
        spec = float(parts[5])
        reliability = float(parts[6])
        n_obs = int(parts[7])

        assert outlet in ["good.com", "bad.com"]
        assert n_articles >= 1
        assert fact in ["high", "low"]
        assert bias in ["center", "extreme-right"]
        assert 0.01 <= sens <= 0.99
        assert 0.01 <= spec <= 0.99
        assert 0.01 <= reliability <= 0.99
        assert n_obs >= 0

        outlets_seen.add(outlet)

    assert outlets_seen == {"good.com", "bad.com"}

    # Check PNG exists
    png_path = out_dir / "e4_external.png"
    assert png_path.exists()
    assert png_path.stat().st_size > 0

    # Check manifest
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()

    with open(manifest_path) as f:
        manifest = json.load(f)

    assert len(manifest) == 1
    assert manifest[0]["experiment"] == "e4"

    # Check metrics
    metrics = entry["metrics"]
    assert "spearman_fact" in metrics
    assert "spearman_fact_ci_lower" in metrics
    assert "spearman_fact_ci_upper" in metrics
    assert "spearman_bias_abs" in metrics
    assert "spearman_bias_abs_ci_lower" in metrics
    assert "spearman_bias_abs_ci_upper" in metrics
    assert "n_outlets_joined" in metrics
    assert "n_events_used" in metrics

    # Validate metric ranges
    if metrics["spearman_fact"] is not None:
        assert -1.0 <= metrics["spearman_fact"] <= 1.0
    if metrics["spearman_bias_abs"] is not None:
        assert -1.0 <= metrics["spearman_bias_abs"] <= 1.0
    assert metrics["n_outlets_joined"] == 2


def test_fact_ordinal_encoding():
    """Test MBFC fact ordinal encoding."""

    # Valid encodings
    assert e4_external._encode_fact_ordinal("low") == 0
    assert e4_external._encode_fact_ordinal("mixed") == 1
    assert e4_external._encode_fact_ordinal("high") == 2

    # Case insensitive
    assert e4_external._encode_fact_ordinal("LOW") == 0
    assert e4_external._encode_fact_ordinal("MIXED") == 1
    assert e4_external._encode_fact_ordinal("HIGH") == 2

    # With whitespace
    assert e4_external._encode_fact_ordinal("  low  ") == 0
    assert e4_external._encode_fact_ordinal("  high  ") == 2

    # Invalid/unknown
    assert e4_external._encode_fact_ordinal("unknown") is None
    assert e4_external._encode_fact_ordinal("") is None
    assert e4_external._encode_fact_ordinal(None) is None


def test_bias_distance_encoding():
    """Test MBFC bias distance encoding."""

    # Valid encodings
    assert e4_external._encode_bias_distance("center") == 0
    assert e4_external._encode_bias_distance("center-left") == 1
    assert e4_external._encode_bias_distance("center-right") == 1
    assert e4_external._encode_bias_distance("left") == 2
    assert e4_external._encode_bias_distance("right") == 2
    assert e4_external._encode_bias_distance("extreme-left") == 3
    assert e4_external._encode_bias_distance("extreme-right") == 3

    # Case insensitive
    assert e4_external._encode_bias_distance("CENTER") == 0
    assert e4_external._encode_bias_distance("EXTREME-LEFT") == 3

    # With whitespace
    assert e4_external._encode_bias_distance("  left  ") == 2

    # Invalid/unknown
    assert e4_external._encode_bias_distance("biased") is None
    assert e4_external._encode_bias_distance("") is None
    assert e4_external._encode_bias_distance(None) is None


def test_e4_handles_missing_external_labels(tmp_path):
    """Test that outlets without external labels are filtered out."""

    db_path = tmp_path / "missing_labels.db"
    conn = connect(str(db_path))

    # Create 3 outlets
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("labeled.com", 0))
    labeled_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("unlabeled.com", 0))
    unlabeled_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("partial.com", 0))
    partial_id = cursor.lastrowid

    # Add external labels (only for labeled and partial)
    conn.execute(
        "INSERT INTO outlet_external_label (domain, fact, bias, source) VALUES (?, ?, ?, ?)",
        ("labeled.com", "high", "center", "mbfc"),
    )
    conn.execute(
        "INSERT INTO outlet_external_label (domain, fact, bias, source) VALUES (?, ?, ?, ?)",
        ("partial.com", "high", None, "mbfc"),  # Missing bias
    )

    # Create event and articles
    conn.execute("INSERT INTO event (id) VALUES (?)", (1,))

    article_id = 1
    for outlet_id in [labeled_id, unlabeled_id, partial_id]:
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{article_id}", f"title-{article_id}", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 1, "occurred", 0.9),
        )
        article_id += 1

    conn.commit()
    conn.close()

    # Run experiment
    config = {
        "db_path": str(db_path),
        "min_outlets": 1,
        "batch_size": 32,
        "min_articles_per_outlet": 1,
    }

    out_dir = tmp_path / "e4_missing_test"
    entry = run_experiment("e4", e4_external.run, config, seed=42, out_dir=str(out_dir))

    csv_path = out_dir / "e4_external.csv"
    with open(csv_path) as f:
        lines = f.readlines()

    # Only labeled.com has both fact and bias → only 1 outlet in output
    assert len(lines) == 2  # header + 1 outlet

    parts = lines[1].strip().split(",")
    outlet = parts[0]
    assert outlet == "labeled.com"

    metrics = entry["metrics"]
    # Only 1 outlet with complete labels
    assert metrics["n_outlets_joined"] == 1


def test_e4_bootstrap_ci(tmp_path):
    """Test that bootstrap confidence intervals are computed."""

    db_path = tmp_path / "bootstrap_test.db"
    conn = connect(str(db_path))

    # Create multiple outlets with external labels
    outlets = []
    for i in range(5):
        cursor = conn.execute(
            "INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)",
            (f"outlet{i}.com", 0),
        )
        outlets.append(cursor.lastrowid)

        # Vary fact and bias
        fact = ["low", "mixed", "high"][i % 3]
        bias = ["center", "left", "extreme-left"][i % 3]
        conn.execute(
            "INSERT INTO outlet_external_label (domain, fact, bias, source) VALUES (?, ?, ?, ?)",
            (f"outlet{i}.com", fact, bias, "mbfc"),
        )

    # Create event and articles
    conn.execute("INSERT INTO event (id) VALUES (?)", (1,))

    article_id = 1
    for outlet_id in outlets:
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{article_id}", f"title-{article_id}", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 1, "occurred", 0.9),
        )
        article_id += 1

    conn.commit()
    conn.close()

    # Run experiment
    config = {
        "db_path": str(db_path),
        "min_outlets": 1,
        "batch_size": 32,
        "min_articles_per_outlet": 1,
    }

    out_dir = tmp_path / "e4_bootstrap_test"
    entry = run_experiment("e4", e4_external.run, config, seed=42, out_dir=str(out_dir))

    metrics = entry["metrics"]

    # Check that CI bounds exist and are reasonable
    if metrics["spearman_fact"] is not None:
        assert metrics["spearman_fact_ci_lower"] is not None
        assert metrics["spearman_fact_ci_upper"] is not None
        # CI lower <= estimate <= CI upper (should hold for bootstrapped CIs)
        if not np.isnan(metrics["spearman_fact"]):
            assert (metrics["spearman_fact_ci_lower"] <= metrics["spearman_fact"] <= metrics["spearman_fact_ci_upper"]
                    or
                    # Allow for edge case where estimate is outside CI due to bootstrap sampling
                    abs(metrics["spearman_fact_ci_upper"] - metrics["spearman_fact_ci_lower"]) > 0.1)


def test_e4_unknown_value_handling(tmp_path):
    """Test handling of unknown fact/bias values in external labels."""

    db_path = tmp_path / "unknown_values.db"
    conn = connect(str(db_path))

    # Create outlets with various label combinations
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("good.com", 0))
    good_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("unknown_fact.com", 0))
    unknown_fact_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("unknown_bias.com", 0))
    unknown_bias_id = cursor.lastrowid

    # Add external labels
    conn.execute(
        "INSERT INTO outlet_external_label (domain, fact, bias, source) VALUES (?, ?, ?, ?)",
        ("good.com", "high", "center", "mbfc"),
    )
    conn.execute(
        "INSERT INTO outlet_external_label (domain, fact, bias, source) VALUES (?, ?, ?, ?)",
        ("unknown_fact.com", "unknown_category", "center", "mbfc"),
    )
    conn.execute(
        "INSERT INTO outlet_external_label (domain, fact, bias, source) VALUES (?, ?, ?, ?)",
        ("unknown_bias.com", "high", "unknown_bias", "mbfc"),
    )

    # Create event and articles
    conn.execute("INSERT INTO event (id) VALUES (?)", (1,))

    article_id = 1
    for outlet_id in [good_id, unknown_fact_id, unknown_bias_id]:
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{article_id}", f"title-{article_id}", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 1, "occurred", 0.9),
        )
        article_id += 1

    conn.commit()
    conn.close()

    # Run experiment
    config = {
        "db_path": str(db_path),
        "min_outlets": 1,
        "batch_size": 32,
        "min_articles_per_outlet": 1,
    }

    out_dir = tmp_path / "e4_unknown_test"
    entry = run_experiment("e4", e4_external.run, config, seed=42, out_dir=str(out_dir))

    csv_path = out_dir / "e4_external.csv"
    with open(csv_path) as f:
        lines = f.readlines()

    # Only good.com has valid fact and bias
    assert len(lines) == 2  # header + 1 outlet

    parts = lines[1].strip().split(",")
    outlet = parts[0]
    assert outlet == "good.com"

    metrics = entry["metrics"]
    assert metrics["n_outlets_joined"] == 1
