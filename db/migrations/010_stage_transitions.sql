-- stage_transitions
CREATE TABLE IF NOT EXISTS stage_transitions (
    id              SERIAL PRIMARY KEY,
    property_id     INT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    from_status     TEXT,
    to_status       TEXT NOT NULL,
    transitioned_at TIMESTAMP DEFAULT NOW(),
    transitioned_by INT REFERENCES users(id)
);

CREATE INDEX IF NOT EXISTS idx_transitions_property ON stage_transitions(property_id);
CREATE INDEX IF NOT EXISTS idx_transitions_status ON stage_transitions(to_status, transitioned_at);
