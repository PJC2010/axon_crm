-- sms_seen_tracking
-- Unread tracking for two-way SMS: inbound messages land in contact_history
-- (migration 0048) with seen_at NULL = unread. Opening a lead's conversation
-- marks its inbound rows seen (POST /api/leads/{id}/conversation/seen), and the
-- account-level unread summary (GET /api/unread-messages) drives the header
-- message bell. Outbound rows and non-message history never use seen_at.

ALTER TABLE contact_history ADD COLUMN IF NOT EXISTS seen_at TIMESTAMPTZ;

-- The unread summary filters on exactly this shape, grouped by property.
CREATE INDEX IF NOT EXISTS idx_history_unread_sms
    ON contact_history (property_id)
    WHERE channel = 'sms' AND direction = 'inbound' AND seen_at IS NULL;
