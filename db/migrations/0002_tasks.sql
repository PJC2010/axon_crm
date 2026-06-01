-- Tasks & follow-ups linked to leads
CREATE TABLE IF NOT EXISTS tasks (
    id           SERIAL PRIMARY KEY,
    property_id  INT REFERENCES properties(id) ON DELETE CASCADE,
    assigned_to  INT REFERENCES users(id),
    title        TEXT NOT NULL,
    due_date     DATE,
    priority     TEXT NOT NULL DEFAULT 'normal',
    is_complete  BOOLEAN NOT NULL DEFAULT FALSE,
    completed_at TIMESTAMP,
    created_by   INT REFERENCES users(id),
    created_at   TIMESTAMP DEFAULT NOW(),
    updated_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_property ON tasks(property_id);
CREATE INDEX IF NOT EXISTS idx_tasks_due      ON tasks(due_date, is_complete);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned ON tasks(assigned_to, is_complete);
