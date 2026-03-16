-- Dedup feedback: persists merge and not_duplicate decisions.
CREATE TABLE IF NOT EXISTS dedup_feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    part_id_a INTEGER NOT NULL,
    part_id_b INTEGER NOT NULL,
    decision TEXT NOT NULL,          -- 'merged', 'not_duplicate'
    score REAL,
    reasons_json TEXT NOT NULL DEFAULT '[]',
    sig_snapshot_a TEXT,             -- JSON of PartSignature at review time
    sig_snapshot_b TEXT,             -- JSON of PartSignature at review time
    name_a TEXT,                     -- name at review time
    name_b TEXT,                     -- name at review time
    created_at TEXT NOT NULL,
    UNIQUE(part_id_a, part_id_b)
);

CREATE INDEX IF NOT EXISTS idx_dedup_feedback_decision
    ON dedup_feedback(decision);
