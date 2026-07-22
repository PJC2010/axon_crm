-- workflow_rules
CREATE TABLE IF NOT EXISTS workflow_rules (
    id             SERIAL PRIMARY KEY,
    name           TEXT NOT NULL,
    trigger_type   TEXT NOT NULL,
    trigger_config JSONB NOT NULL DEFAULT '{}',
    action_type    TEXT NOT NULL,
    action_config  JSONB NOT NULL DEFAULT '{}',
    is_active      BOOLEAN NOT NULL DEFAULT TRUE,
    vertical       TEXT,
    created_by     INT REFERENCES users(id),
    created_at     TIMESTAMP DEFAULT NOW(),
    updated_at     TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_workflow_trigger ON workflow_rules(trigger_type, is_active);
