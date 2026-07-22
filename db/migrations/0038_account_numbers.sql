-- Migration 038: durable customer account numbers + universal search.
--
-- Every lead (properties row) gets a permanent, human-friendly account number
-- like C-01001, sequential PER ORG. The number is assigned by a BEFORE INSERT
-- trigger so EVERY insert path gets one — CSV import, the batch pipeline, and
-- manual creation alike — and it never changes once set (re-imports that hit
-- the (account_id, address, zip) dedup key update the existing row and keep its
-- number). This number is the stable handle the frontend deep link rides on and
-- the primary key users search by.
--
-- Also enables pg_trgm + trigram indexes so /api/leads/search can do fast fuzzy
-- lookups by name, address, phone, and email.

-- ── Account number column + per-org counter ─────────────────────────────────────
ALTER TABLE properties ADD COLUMN IF NOT EXISTS account_number TEXT;

-- Per-org running counter. Starts at 1001 so the first customer is C-01001.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS next_customer_no INT NOT NULL DEFAULT 1001;

-- Assign the next per-org number on insert when one wasn't supplied. The UPDATE
-- locks the account row, serializing concurrent inserts for the same org so two
-- leads can never claim the same number.
CREATE OR REPLACE FUNCTION assign_account_number()
RETURNS TRIGGER AS $$
DECLARE
    consumed INT;
BEGIN
    IF NEW.account_number IS NULL THEN
        UPDATE accounts
           SET next_customer_no = next_customer_no + 1
         WHERE id = NEW.account_id
        RETURNING next_customer_no - 1 INTO consumed;
        NEW.account_number := 'C-' || LPAD(consumed::TEXT, 5, '0');
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_properties_account_number ON properties;
CREATE TRIGGER trg_properties_account_number
  BEFORE INSERT ON properties
  FOR EACH ROW EXECUTE FUNCTION assign_account_number();

-- ── Backfill existing leads ──────────────────────────────────────────────────────
-- Number existing rows per org, oldest first, starting at 1001 to match the
-- counter's start value.
WITH numbered AS (
    SELECT id,
           1000 + ROW_NUMBER() OVER (PARTITION BY account_id ORDER BY id) AS n
    FROM properties
    WHERE account_number IS NULL
)
UPDATE properties p
   SET account_number = 'C-' || LPAD(numbered.n::TEXT, 5, '0')
  FROM numbered
 WHERE p.id = numbered.id;

-- Advance each org's counter past the highest number we just assigned, so new
-- inserts continue the sequence without colliding. Orgs with no leads keep the
-- default (1001).
UPDATE accounts a
   SET next_customer_no = sub.max_n + 1
  FROM (
      SELECT account_id,
             MAX(SUBSTRING(account_number FROM 3)::INT) AS max_n
      FROM properties
      WHERE account_number IS NOT NULL
      GROUP BY account_id
  ) sub
 WHERE a.id = sub.account_id;

-- Uniqueness per org. (account_number is filled by the trigger, so NULLs only
-- exist transiently; Postgres permits multiple NULLs under a unique index.)
CREATE UNIQUE INDEX IF NOT EXISTS idx_props_acct_number
    ON properties (account_id, account_number);

-- ── Universal search: trigram indexes ───────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE INDEX IF NOT EXISTS idx_props_trgm_name
    ON properties USING gin (contact_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_props_trgm_owner
    ON properties USING gin (owner_name gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_props_trgm_address
    ON properties USING gin (address gin_trgm_ops);
CREATE INDEX IF NOT EXISTS idx_props_trgm_email
    ON properties USING gin (contact_email gin_trgm_ops);
-- Phone matched on digits only, so users find a number however it's formatted.
CREATE INDEX IF NOT EXISTS idx_props_trgm_phone
    ON properties USING gin (regexp_replace(contact_phone, '[^0-9]', '', 'g') gin_trgm_ops);
