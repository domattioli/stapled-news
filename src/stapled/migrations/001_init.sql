-- Initialize schema for stapled-news

CREATE TABLE IF NOT EXISTS outlet (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    feed_url TEXT,
    is_synthetic BOOLEAN DEFAULT 0
);

CREATE TABLE IF NOT EXISTS article (
    id INTEGER PRIMARY KEY,
    outlet_id INTEGER NOT NULL,
    corpus_id INTEGER,
    url TEXT NOT NULL,
    published_at TEXT,
    title TEXT,
    body TEXT,
    dedup_cluster_id INTEGER,
    ingest_status TEXT DEFAULT 'ok',
    skip_reason TEXT,
    UNIQUE(outlet_id, url),
    FOREIGN KEY(outlet_id) REFERENCES outlet(id),
    FOREIGN KEY(corpus_id) REFERENCES corpus(id)
);

CREATE TABLE IF NOT EXISTS event (
    id INTEGER PRIMARY KEY,
    corpus_id INTEGER,
    label TEXT,
    true_state INTEGER,
    true_magnitude_bucket INTEGER,
    FOREIGN KEY(corpus_id) REFERENCES corpus(id)
);

CREATE TABLE IF NOT EXISTS claim (
    id INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL,
    event_id INTEGER,
    actor TEXT,
    action TEXT,
    object TEXT,
    time_ref TEXT,
    location TEXT,
    magnitude_value REAL,
    magnitude_unit TEXT,
    hedging TEXT DEFAULT 'none',
    certainty REAL,
    valence REAL,
    attribution TEXT,
    extraction_score REAL,
    FOREIGN KEY(article_id) REFERENCES article(id),
    FOREIGN KEY(event_id) REFERENCES event(id),
    CHECK(certainty >= 0 AND certainty <= 1),
    CHECK(valence >= -1 AND valence <= 1),
    CHECK(extraction_score >= 0 AND extraction_score <= 1)
);

CREATE TABLE IF NOT EXISTS corpus (
    id INTEGER PRIMARY KEY,
    seed INTEGER,
    params_json TEXT,
    validation_status TEXT DEFAULT 'pending',
    validation_report_json TEXT
);

CREATE TABLE IF NOT EXISTS outlet_truth (
    corpus_id INTEGER NOT NULL,
    outlet_id INTEGER NOT NULL,
    reliability REAL,
    bias REAL,
    calibration REAL,
    PRIMARY KEY(corpus_id, outlet_id),
    FOREIGN KEY(corpus_id) REFERENCES corpus(id),
    FOREIGN KEY(outlet_id) REFERENCES outlet(id)
);

CREATE TABLE IF NOT EXISTS inference_run (
    id INTEGER PRIMARY KEY,
    created_at TEXT,
    corpus_id INTEGER,
    claim_set_hash TEXT,
    status TEXT,
    iterations INTEGER,
    log_likelihood REAL,
    config_json TEXT,
    FOREIGN KEY(corpus_id) REFERENCES corpus(id)
);

CREATE TABLE IF NOT EXISTS run_event_result (
    run_id INTEGER NOT NULL,
    event_id INTEGER NOT NULL,
    inferred_state INTEGER,
    inferred_magnitude_bucket INTEGER,
    confidence REAL,
    corroboration TEXT,
    weighting_json TEXT,
    PRIMARY KEY(run_id, event_id),
    FOREIGN KEY(run_id) REFERENCES inference_run(id),
    FOREIGN KEY(event_id) REFERENCES event(id)
);

CREATE TABLE IF NOT EXISTS run_outlet_result (
    run_id INTEGER NOT NULL,
    outlet_id INTEGER NOT NULL,
    est_reliability REAL,
    est_bias REAL,
    est_calibration REAL,
    PRIMARY KEY(run_id, outlet_id),
    FOREIGN KEY(run_id) REFERENCES inference_run(id),
    FOREIGN KEY(outlet_id) REFERENCES outlet(id)
);

CREATE TABLE IF NOT EXISTS recovery_report (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL,
    corpus_id INTEGER NOT NULL,
    state_accuracy REAL,
    reliability_rank_corr REAL,
    verdict TEXT,
    FOREIGN KEY(run_id) REFERENCES inference_run(id),
    FOREIGN KEY(corpus_id) REFERENCES corpus(id),
    CHECK(verdict IN ('PASS', 'FAIL'))
);

CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT
);
