-- Migration 035: social login (Sign in with Google / Apple) identity links.
-- Authentication only — NOT data sync (that reuses the connections framework,
-- migration 032, in a later phase). A user is invited the usual way (an owner
-- creates the users row); social login matches an EXISTING active user by the
-- provider's verified email on first use, then records this link so subsequent
-- logins match on the provider's stable subject id (`provider_sub`) instead of
-- email — Apple can hide/rotate the email via its private-relay feature.
-- One user may link both Google and Apple, hence a one-to-many table rather
-- than columns on `users`.

CREATE TABLE IF NOT EXISTS oauth_identities (
    id           SERIAL PRIMARY KEY,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider     TEXT NOT NULL,                 -- 'google' | 'apple'
    provider_sub TEXT NOT NULL,                 -- stable subject id from the IdP
    email        TEXT,                          -- email seen at link time
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (provider, provider_sub)
);

CREATE INDEX IF NOT EXISTS idx_oauth_identities_user ON oauth_identities(user_id);
