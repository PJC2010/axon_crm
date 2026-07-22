-- 045_recurring_invoices.sql — Phase 7 (recurring revenue): let an invoice
-- recur on a fixed cadence (memberships, retainers, maintenance contracts).
--
-- A recurring invoice is a normal invoice with `recurrence` set; it is the
-- first occurrence. A daily scheduler tick (api/recurring_invoices.py) clones
-- it forward each time recurrence_next falls due — the clone is an independent,
-- non-recurring invoice with a fresh number and recurring_source_id pointing
-- back — then advances recurrence_next by the cadence. recurrence_end (optional)
-- stops the series.

ALTER TABLE invoices ADD COLUMN IF NOT EXISTS recurrence          TEXT;    -- weekly|monthly|quarterly|annual
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS recurrence_next     DATE;    -- next generation date
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS recurrence_end      DATE;    -- optional last date
ALTER TABLE invoices ADD COLUMN IF NOT EXISTS recurring_source_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL;

-- The tick scans only active recurring templates that are due.
CREATE INDEX IF NOT EXISTS idx_invoices_recurrence_next
    ON invoices(recurrence_next)
    WHERE recurrence IS NOT NULL;
