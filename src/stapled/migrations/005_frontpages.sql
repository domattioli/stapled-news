-- Frontpage Archive metadata and article tracking

CREATE TABLE IF NOT EXISTS fp_article_meta (
    url TEXT PRIMARY KEY,
    outlet TEXT NOT NULL,
    section TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    title_variants INTEGER DEFAULT 1
);
