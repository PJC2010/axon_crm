-- 037_drop_appointments.sql — remove the appointments & calendar feature.
--
-- The Appointments & Calendar feature (introduced in 031_appointments.sql) has
-- been removed from the product. This drops the table along with its indexes and
-- updated_at trigger (all dropped implicitly with the table). Forward-only: no
-- application code references the table after this migration.

DROP TABLE IF EXISTS appointments CASCADE;
