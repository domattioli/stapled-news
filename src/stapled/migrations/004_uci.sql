-- UCI News Aggregator story mapping table

CREATE TABLE IF NOT EXISTS uci_story (
    story_id TEXT PRIMARY KEY,
    event_id INTEGER NOT NULL,
    FOREIGN KEY(event_id) REFERENCES event(id)
);
