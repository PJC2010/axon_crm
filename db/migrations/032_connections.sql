-- Migration 032: connectors / connections framework.
-- A generic per-account link to an external digital-presence provider. The first
-- providers are Meta (facebook / instagram). auth_type records HOW data arrives:
-- 'file' (manual export upload — shipping now) or 'oauth' (live sync — future).
-- credentials_json is an (eventually encrypted) placeholder for future OAuth
-- tokens; it stays NULL on the file path. File imports and any future OAuth sync
-- write the SAME social_* rows, distinguished only by a `source` discriminator,
-- so OAuth slots in later with no schema change.

CREATE TABLE IF NOT EXISTS connections (
    id               SERIAL PRIMARY KEY,
    account_id       INTEGER NOT NULL REFERENCES accounts(id),
    provider         TEXT NOT NULL,                      -- 'meta_facebook' | 'meta_instagram' (extensible)
    display_name     TEXT,                               -- page / profile name the user typed
    status           TEXT NOT NULL DEFAULT 'connected',  -- connected | disconnected | error
    auth_type        TEXT NOT NULL DEFAULT 'file',       -- file | oauth
    credentials_json JSONB,                              -- FUTURE OAuth tokens (encrypted); NULL for file
    last_synced_at   TIMESTAMPTZ,                        -- last successful import / sync
    created_by       INTEGER REFERENCES users(id),
    created_at       TIMESTAMPTZ DEFAULT NOW(),
    updated_at       TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_connections_account ON connections(account_id, provider);
-- One connection per provider per account; re-uploads update the same row.
CREATE UNIQUE INDEX IF NOT EXISTS connections_acct_provider_uq
    ON connections(account_id, provider);

CREATE TRIGGER connections_updated_at
  BEFORE UPDATE ON connections
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
