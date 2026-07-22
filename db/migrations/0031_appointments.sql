-- Migration 031: appointments & calendar.
-- A first-class scheduled meeting/visit, optionally tied to a lead and assigned
-- to a rep. Distinct from tasks (which are reminders) — appointments have a
-- start/end time, a location, and a lifecycle status, and can send the customer
-- a calendar invite.

CREATE TABLE IF NOT EXISTS appointments (
    id           SERIAL PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    property_id  INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    assigned_to  INTEGER REFERENCES users(id),
    title        TEXT NOT NULL,
    location     TEXT,
    starts_at    TIMESTAMPTZ NOT NULL,
    ends_at      TIMESTAMPTZ NOT NULL,
    status       TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled | completed | cancelled | no_show
    notes        TEXT,
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_appt_account_time ON appointments(account_id, starts_at);
CREATE INDEX IF NOT EXISTS idx_appt_property     ON appointments(property_id);
CREATE INDEX IF NOT EXISTS idx_appt_assigned     ON appointments(assigned_to, starts_at);

CREATE TRIGGER appointments_updated_at
  BEFORE UPDATE ON appointments
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
