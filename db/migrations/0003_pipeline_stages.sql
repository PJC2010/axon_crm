-- Extend lead statuses for full sales pipeline and add job value tracking
ALTER TABLE properties ADD COLUMN IF NOT EXISTS estimated_job_value INT;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS stage_moved_at TIMESTAMP;
-- status now also allows: quote_sent | won | lost
