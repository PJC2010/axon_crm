-- contact_details
-- Richer per-lead contact fields, editable from the lead drawer / detail page.
ALTER TABLE properties ADD COLUMN IF NOT EXISTS contact_phone_alt        TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS contact_email_alt        TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS mailing_address          TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS preferred_contact_method TEXT;  -- phone | text | email
ALTER TABLE properties ADD COLUMN IF NOT EXISTS best_time_to_call        TEXT;
