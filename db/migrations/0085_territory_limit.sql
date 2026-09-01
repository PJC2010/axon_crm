-- territory_limit — per-plan cap on distinct pipeline ZIP codes ("territories").
--
-- Only pro runs unlimited territories: lower tiers get a fixed number of
-- distinct ZIPs they may schedule or run the pipeline against. Plan defaults
-- live in code (api/entitlements.py PLAN_TERRITORY_LIMITS: starter 1, growth 3,
-- pro unlimited); this column is the per-account override for custom deals.
-- NULL = use the plan default. Mirrors 0061's scoring_monthly_limit exactly —
-- there is no ledger table because the territory set is derived live from
-- pipeline_schedules / pipeline_runs / properties (api/territory.py).
ALTER TABLE account_plans ADD COLUMN IF NOT EXISTS territory_limit INT;
