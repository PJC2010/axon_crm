-- Back the CSV import's address dedup lookup.
--
-- The importer used to dedup address rows purely through
-- ON CONFLICT (account_id, address, zip). That misses two whole classes of
-- duplicate:
--
--   * Postgres treats NULLs as distinct, so a row with a street address but no
--     ZIP never conflicted with anything — re-importing the same contact list
--     inserted every one of those rows again, every time.
--   * The key is the raw string, so "12 Ash St", "12 ash st" and "12 Ash St."
--     are three different leads for one property, and an imported address never
--     matches the same property seeded by the pipeline.
--
-- api/routes/imports.py now looks the row up through axon_normalize_address()
-- first — the same normalization rule pipeline/addr.py applies everywhere else
-- (migration 0065) — and falls back to the unique key as the insert-race guard.
-- Without this index that lookup is a sequential scan of the account's leads
-- once per imported row.
--
-- Deliberately not UNIQUE: existing accounts already hold rows that collide
-- under normalization, and this migration must not fail on their data. It makes
-- the lookup cheap; the importer decides what to do with what it finds.

CREATE INDEX IF NOT EXISTS idx_props_acct_addr_norm
    ON properties (account_id, axon_normalize_address(address))
    WHERE address IS NOT NULL;


-- Same story for address-less contacts that carry a phone but no email: they
-- matched neither key, so every re-import inserted them again. The importer now
-- looks them up by the last-10-digits rule the rest of the app compares phone
-- numbers by (api/routes/twilio_inbound.py::normalize_phone).
--
-- Also not UNIQUE, and for a second reason: the importer additionally requires
-- the contact name to match, because a household or shop landline is shared and
-- a unique key on the number alone would be wrong.

CREATE INDEX IF NOT EXISTS idx_props_acct_phone_noaddr
    ON properties (
        account_id,
        right(regexp_replace(coalesce(contact_phone, ''), '[^0-9]', '', 'g'), 10)
    )
    WHERE address IS NULL AND contact_phone IS NOT NULL;
