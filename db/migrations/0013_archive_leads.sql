-- Add soft archive support for leads
ALTER TABLE properties ADD COLUMN archived_at TIMESTAMP NULL;
CREATE INDEX idx_properties_archived_at ON properties(archived_at);
