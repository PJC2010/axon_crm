-- Per-account business type.
--
-- Axon was hard-wired for home-services contractors. This adds a `business_type`
-- on each account so the product can present industry-appropriate terminology
-- ("lead" vs "deal"), the right category list (what "verticals" become), and
-- sensible default feature modules. The canonical catalog of types lives in
-- api/business_types.py; this migration just stores the per-account selection.
--
-- SAFETY: every existing account is backfilled to 'home_services', so current
-- behavior (verticals, property pipeline, home-services labels) is unchanged.

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS business_type TEXT NOT NULL DEFAULT 'home_services';

UPDATE accounts SET business_type = 'home_services' WHERE business_type IS NULL;
