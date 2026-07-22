-- 044_message_templates.sql — Phase 7 (communication hub): reusable message
-- templates for contact-level email/SMS with merge fields (see api/messaging.py).
-- Sends are logged to contact_history so they appear in the record timeline;
-- the send_template workflow action lets automations message the record's
-- contact (distinct from send_notification, which emails the rule's owner).

CREATE TABLE IF NOT EXISTS message_templates (
  id          SERIAL PRIMARY KEY,
  account_id  INTEGER NOT NULL REFERENCES accounts(id),
  name        TEXT NOT NULL,
  channel     TEXT NOT NULL DEFAULT 'email',   -- email | sms
  subject     TEXT,                            -- email only
  body        TEXT NOT NULL,
  created_by  INTEGER REFERENCES users(id),
  created_at  TIMESTAMPTZ DEFAULT NOW(),
  updated_at  TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE (account_id, name)
);

CREATE INDEX IF NOT EXISTS idx_message_templates_account ON message_templates(account_id);

CREATE TRIGGER message_templates_updated_at
  BEFORE UPDATE ON message_templates
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
