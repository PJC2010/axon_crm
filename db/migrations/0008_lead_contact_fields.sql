-- lead_contact_fields
ALTER TABLE properties ADD COLUMN IF NOT EXISTS contact_phone TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS contact_email TEXT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS contact_name  TEXT;
