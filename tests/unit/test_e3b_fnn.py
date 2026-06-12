"""Unit tests for E3b FNN held-out label experiment."""

import json

from stapled.experiments import e3b_fnn
from stapled.experiments.runner import run_experiment
from stapled.db import connect


def test_e3b_runs_on_synthetic_db(tmp_path):
    """Test e3b experiment on a minimal synthetic fnn-like DB with labels."""

    # Create tiny synthetic DB
    db_path = tmp_path / "tiny_fnn.db"
    conn = connect(str(db_path))

    # Create outlets: good, ok, bad
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("good.com", 0))
    good_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("ok.com", 0))
    ok_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("bad.com", 1))
    bad_id = cursor.lastrowid

    # Create events
    for i in range(2):
        conn.execute("INSERT INTO event (id) VALUES (?)", (i + 1,))

    event_ids = [1, 2]

    # Create articles (two per outlet per event)
    article_id = 1
    for event_id in event_ids:
        for outlet_id in [good_id, ok_id, bad_id]:
            conn.execute(
                "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (outlet_id, f"url-{article_id}", f"title-{article_id}", "body text", "2024-01-01", "ok"),
            )
            article_id += 1

    # Create claims
    article_id = 1
    for event_id in event_ids:
        for outlet_id in [good_id, ok_id, bad_id]:
            conn.execute(
                "INSERT INTO claim (article_id, event_id, action, certainty) "
                "VALUES (?, ?, ?, ?)",
                (article_id, event_id, "occurred", 0.9),
            )
            article_id += 1

    # Add article_label rows: good=mostly real, ok=mixed, bad=mostly fake
    article_id = 1
    for event_id in event_ids:
        # good.com: label='real'
        conn.execute(
            "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
            (article_id, "fnn", "real"),
        )
        article_id += 1

        # ok.com: mixed (one real, one fake)
        if event_id == 1:
            conn.execute(
                "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
                (article_id, "fnn", "real"),
            )
        else:
            conn.execute(
                "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
                (article_id, "fnn", "fake"),
            )
        article_id += 1

        # bad.com: label='fake'
        conn.execute(
            "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
            (article_id, "fnn", "fake"),
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

    out_dir = tmp_path / "e3b_output"
    entry = run_experiment("e3b", e3b_fnn.run, config, seed=42, out_dir=str(out_dir))

    # Check CSV exists and is valid
    csv_path = out_dir / "e3b_fnn.csv"
    assert csv_path.exists()

    with open(csv_path) as f:
        lines = f.readlines()

    assert lines[0].strip() == "outlet,n_articles,fake_share,sens,spec,reliability,n_obs"

    # Expect: 3 outlets (all have >= 1 article with label)
    assert len(lines) == 4  # header + 3 outlets

    # Parse and validate rows
    outlets_seen = set()
    for line in lines[1:]:
        parts = line.strip().split(",")
        assert len(parts) == 7

        outlet = parts[0]
        n_articles = int(parts[1])
        fake_share = float(parts[2])
        sens = float(parts[3])
        spec = float(parts[4])
        reliability = float(parts[5])
        n_obs = int(parts[6])

        assert outlet in ["good.com", "ok.com", "bad.com"]
        assert n_articles >= 1
        assert 0.0 <= fake_share <= 1.0
        assert 0.01 <= sens <= 0.99
        assert 0.01 <= spec <= 0.99
        assert 0.01 <= reliability <= 0.99
        assert n_obs >= 0

        outlets_seen.add(outlet)

    assert outlets_seen == {"good.com", "ok.com", "bad.com"}

    # Check PNG exists
    png_path = out_dir / "e3b_fnn.png"
    assert png_path.exists()
    assert png_path.stat().st_size > 0

    # Check manifest
    manifest_path = out_dir / "manifest.json"
    assert manifest_path.exists()

    with open(manifest_path) as f:
        manifest = json.load(f)

    assert len(manifest) == 1
    assert manifest[0]["experiment"] == "e3b"

    # Check metrics
    metrics = entry["metrics"]
    assert "spearman_rho" in metrics
    assert "spearman_pval" in metrics
    assert "auc_mostly_fake" in metrics
    assert "n_outlets_scored" in metrics
    assert "n_events_used" in metrics

    # Validate metric ranges
    if metrics["spearman_rho"] is not None:
        assert -1.0 <= metrics["spearman_rho"] <= 1.0
    if metrics["spearman_pval"] is not None:
        assert 0.0 <= metrics["spearman_pval"] <= 1.0
    assert 0.0 <= metrics["auc_mostly_fake"] <= 1.0
    assert metrics["n_outlets_scored"] == 3


def test_e3b_encodes_labels_correctly(tmp_path):
    """Test that label encoding (fake_share) works correctly."""

    db_path = tmp_path / "label_test.db"
    conn = connect(str(db_path))

    # Create outlet
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("test.com", 0))
    outlet_id = cursor.lastrowid

    # Create event
    conn.execute("INSERT INTO event (id) VALUES (?)", (1,))

    # Create 3 articles
    article_ids = []
    for i in range(3):
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (outlet_id, f"url-{i}", f"title-{i}", "body", "2024-01-01", "ok"),
        )
        article_ids.append(cursor.lastrowid)

    # Create claims for each article
    for i, article_id in enumerate(article_ids):
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (article_id, 1, "occurred", 0.9),
        )

    # Label: 1 fake, 2 real
    conn.execute(
        "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
        (article_ids[0], "fnn", "fake"),
    )
    conn.execute(
        "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
        (article_ids[1], "fnn", "real"),
    )
    conn.execute(
        "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
        (article_ids[2], "fnn", "real"),
    )

    conn.commit()
    conn.close()

    # Run experiment
    config = {
        "db_path": str(db_path),
        "min_outlets": 1,
        "batch_size": 32,
        "min_articles_per_outlet": 1,
    }

    out_dir = tmp_path / "e3b_label_test"
    run_experiment("e3b", e3b_fnn.run, config, seed=42, out_dir=str(out_dir))

    # Parse CSV
    csv_path = out_dir / "e3b_fnn.csv"
    with open(csv_path) as f:
        lines = f.readlines()

    assert len(lines) == 2  # header + 1 outlet

    parts = lines[1].strip().split(",")
    outlet = parts[0]
    fake_share = float(parts[2])

    assert outlet == "test.com"
    # fake_share should be 1/3 ≈ 0.333333
    assert abs(fake_share - 1.0/3.0) < 0.001


def test_e3b_filters_by_min_articles(tmp_path):
    """Test that min_articles_per_outlet filtering works."""

    db_path = tmp_path / "filter_test.db"
    conn = connect(str(db_path))

    # Create 3 outlets
    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("rich.com", 0))
    rich_id = cursor.lastrowid

    cursor = conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("poor.com", 0))
    poor_id = cursor.lastrowid

    conn.execute("INSERT INTO outlet (name, is_synthetic) VALUES (?, ?)", ("none.com", 0))

    # Create event
    conn.execute("INSERT INTO event (id) VALUES (?)", (1,))

    # Create 5 articles for rich, 2 for poor, 0 for none
    article_id = 1
    for i in range(5):
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (rich_id, f"url-{article_id}", f"title-{article_id}", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
            (cursor.lastrowid, "fnn", "real"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (cursor.lastrowid, 1, "occurred", 0.9),
        )
        article_id += 1

    for i in range(2):
        cursor = conn.execute(
            "INSERT INTO article (outlet_id, url, title, body, published_at, ingest_status) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (poor_id, f"url-{article_id}", f"title-{article_id}", "body", "2024-01-01", "ok"),
        )
        conn.execute(
            "INSERT INTO article_label (article_id, dataset, label) VALUES (?, ?, ?)",
            (cursor.lastrowid, "fnn", "real"),
        )
        conn.execute(
            "INSERT INTO claim (article_id, event_id, action, certainty) VALUES (?, ?, ?, ?)",
            (cursor.lastrowid, 1, "occurred", 0.9),
        )
        article_id += 1

    conn.commit()
    conn.close()

    # Run with min_articles_per_outlet=3 → should exclude poor.com and none.com
    config = {
        "db_path": str(db_path),
        "min_outlets": 1,
        "batch_size": 32,
        "min_articles_per_outlet": 3,
    }

    out_dir = tmp_path / "e3b_filter_test"
    run_experiment("e3b", e3b_fnn.run, config, seed=42, out_dir=str(out_dir))

    csv_path = out_dir / "e3b_fnn.csv"
    with open(csv_path) as f:
        lines = f.readlines()

    # Expect: header + 1 outlet (rich.com)
    assert len(lines) == 2

    parts = lines[1].strip().split(",")
    outlet = parts[0]
    assert outlet == "rich.com"


def test_auc_computation():
    """Test rank-based AUC for mostly-real vs mostly-fake separation."""

    # Case 1: mostly-real clearly > mostly-fake
    mostly_real = [0.8, 0.7]
    mostly_fake = [0.3, 0.2]
    auc = e3b_fnn._compute_auc(mostly_real, mostly_fake)
    # All 4 pairs (real, fake) have real > fake → AUC = 1.0
    assert auc == 1.0

    # Case 2: mostly-real clearly < mostly-fake
    mostly_real = [0.2, 0.3]
    mostly_fake = [0.7, 0.8]
    auc = e3b_fnn._compute_auc(mostly_real, mostly_fake)
    # All 4 pairs have real < fake → AUC = 0.0
    assert auc == 0.0

    # Case 3: mixed
    mostly_real = [0.5]
    mostly_fake = [0.3, 0.7]
    auc = e3b_fnn._compute_auc(mostly_real, mostly_fake)
    # 1 pair correct (0.5 > 0.3), 1 pair wrong (0.5 < 0.7) → AUC = 0.5
    assert auc == 0.5

    # Case 4: empty
    mostly_real = []
    mostly_fake = [0.5]
    auc = e3b_fnn._compute_auc(mostly_real, mostly_fake)
    assert auc == 0.5
