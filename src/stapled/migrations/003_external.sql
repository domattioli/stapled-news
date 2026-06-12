-- External label tables for held-out truth and outlet metadata

CREATE TABLE IF NOT EXISTS article_label (
    article_id INTEGER PRIMARY KEY,
    dataset TEXT,
    label TEXT,
    FOREIGN KEY(article_id) REFERENCES article(id)
);

CREATE TABLE IF NOT EXISTS outlet_external_label (
    domain TEXT PRIMARY KEY,
    fact TEXT,
    bias TEXT,
    source TEXT
);
