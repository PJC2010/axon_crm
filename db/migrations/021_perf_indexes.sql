-- Composite index for the hottest tenant-scoped access patterns.
-- /api/pipeline/stats groups by status filtered only by account_id, and most
-- list/board queries filter on (account_id, status); none of the existing
-- indexes lead with account_id + status.
CREATE INDEX IF NOT EXISTS idx_props_acct_status ON properties(account_id, status);
