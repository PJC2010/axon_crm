-- Contact / lead CSV import.
--
-- Until now every lead (properties row) came from the enrichment pipeline, which
-- always has a street address. The import feature lets an owner bring in their
-- existing book of contacts and leads from a spreadsheet or Google Contacts
-- export. Some of those rows are address-based leads (job sites); others are
-- pure people contacts (name/phone/email) with no address at all.
--
-- To store address-less contacts we relax the NOT NULL on properties.address.
-- The existing (account_id, address, zip) unique constraint still dedups
-- address-based rows; Postgres treats NULL addresses as distinct so address-less
-- contacts never collide on it. To dedup people-only contacts we add a partial
-- unique index on their email instead.

ALTER TABLE properties ALTER COLUMN address DROP NOT NULL;

-- Dedup address-less contacts by email within an org (case-insensitive).
CREATE UNIQUE INDEX IF NOT EXISTS properties_acct_email_noaddr
    ON properties (account_id, lower(contact_email))
    WHERE address IS NULL AND contact_email IS NOT NULL;
