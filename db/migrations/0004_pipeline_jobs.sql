-- Pipeline scheduling and run history
CREATE TABLE IF NOT EXISTS pipeline_schedules (
    id          SERIAL PRIMARY KEY,
    zip         TEXT NOT NULL,
    vertical    TEXT,
    day_of_week TEXT NOT NULL DEFAULT 'monday',
    hour        INT  NOT NULL DEFAULT 6,
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_by  INT REFERENCES users(id),
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id           SERIAL PRIMARY KEY,
    schedule_id  INT REFERENCES pipeline_schedules(id),
    zip          TEXT NOT NULL,
    vertical     TEXT,
    status       TEXT NOT NULL DEFAULT 'queued',
    triggered_by TEXT NOT NULL DEFAULT 'schedule',
    started_at   TIMESTAMP,
    finished_at  TIMESTAMP,
    result_json  JSONB,
    created_at   TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_runs_status  ON pipeline_runs(status);
CREATE INDEX IF NOT EXISTS idx_runs_created ON pipeline_runs(created_at DESC);
