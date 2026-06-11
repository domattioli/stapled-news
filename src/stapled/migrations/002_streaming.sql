-- Streaming Dawid-Skene EM: cursor, suffstats, state, anchors, dedup, centroids, vocab, snapshots

CREATE TABLE IF NOT EXISTS source_cursor (
    id INTEGER PRIMARY KEY,
    source_url TEXT UNIQUE NOT NULL,
    etag TEXT,
    byte_offset INTEGER DEFAULT 0,
    rows_ingested INTEGER DEFAULT 0,
    done INTEGER DEFAULT 0,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS em_suffstats (
    outlet_id INTEGER PRIMARY KEY,
    exp_tp REAL DEFAULT 0,
    exp_fp REAL DEFAULT 0,
    exp_tn REAL DEFAULT 0,
    exp_fn REAL DEFAULT 0,
    n_obs INTEGER DEFAULT 0,
    FOREIGN KEY(outlet_id) REFERENCES outlet(id)
);

CREATE TABLE IF NOT EXISTS em_state (
    id INTEGER PRIMARY KEY CHECK (id=1),
    prior_pi REAL DEFAULT 0.5,
    batches_seen INTEGER DEFAULT 0,
    ll_trace_json TEXT,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS anchor (
    id INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL,
    true_state INTEGER CHECK (true_state IN (0, 1)),
    source TEXT,
    FOREIGN KEY(event_id) REFERENCES event(id)
);

CREATE TABLE IF NOT EXISTS simhash_bucket (
    band INTEGER NOT NULL,
    bucketkey TEXT NOT NULL,
    article_id INTEGER NOT NULL,
    PRIMARY KEY(band, bucketkey, article_id),
    FOREIGN KEY(article_id) REFERENCES article(id)
);

CREATE TABLE IF NOT EXISTS event_centroid (
    event_id INTEGER PRIMARY KEY,
    vec_json TEXT,
    n INTEGER DEFAULT 0,
    FOREIGN KEY(event_id) REFERENCES event(id)
);

CREATE TABLE IF NOT EXISTS tfidf_vocab (
    term TEXT PRIMARY KEY,
    idx INTEGER UNIQUE,
    idf REAL
);

CREATE TABLE IF NOT EXISTS reliability_snapshot (
    batch INTEGER NOT NULL,
    outlet_id INTEGER NOT NULL,
    reliability REAL,
    PRIMARY KEY(batch, outlet_id),
    FOREIGN KEY(outlet_id) REFERENCES outlet(id)
);
