-- Prospect email capture from the public landing/preview pages.
-- Platform-level (no account_id): these are potential customers of Axon
-- itself, not tenant CRM data. Written by POST /api/public/prospect.

CREATE TABLE IF NOT EXISTS prospect_signups (
    id          SERIAL PRIMARY KEY,
    email       TEXT NOT NULL,
    name        TEXT,
    source      TEXT,                       -- 'landing' | 'preview' | ...
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_prospect_signups_email
    ON prospect_signups (lower(email));
