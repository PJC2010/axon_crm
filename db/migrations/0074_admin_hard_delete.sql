-- admin_hard_delete — make an organization (and a user) actually deletable.
--
-- The platform-admin dashboard (migration 0073, api/routes/admin.py) can create
-- orgs and users, change plans, and deactivate logins, but it could not delete
-- anything: every FK pointing at accounts(id) and users(id) was created without
-- an ON DELETE clause, i.e. NO ACTION. `DELETE FROM accounts WHERE id = 5` on
-- that schema fails on the first child row and there is no ordering a caller
-- can pick that avoids it — a 40-table graph has to be torn down bottom-up, and
-- an application-side list of DELETEs would silently rot the moment someone
-- adds a table. So the delete order is pushed into the database, where Postgres
-- computes it and keeps computing it for tables that don't exist yet.
--
-- Two rules, and the difference between them is the whole design:
--
--   accounts(id)  -> ON DELETE CASCADE.  An account IS its data. Every
--                    account_id row is org-owned, so deleting the org deletes
--                    them, and the tenant-parent FKs below it (contact_history
--                    -> properties, invoice_line_items -> invoices, …) were
--                    already CASCADE, so the sweep reaches the whole graph.
--
--   users(id)     -> ON DELETE SET NULL.  A user OWNS nothing. created_by /
--                    assigned_to / actor_user_id / transitioned_by are
--                    attribution, not ownership: deleting a sales rep must
--                    unassign their leads and anonymize their notes, never
--                    delete the org's invoices. Every such column is already
--                    nullable, so SET NULL needs no data migration. The two
--                    genuine user-owned tables (user_tokens, oauth_identities)
--                    were CASCADE from the start and are left alone.
--
-- Nullable account_id columns (model_versions, vertical_geo_config,
-- lead_feature_snapshots) use NULL to mean "platform-wide default", and CASCADE
-- only matches rows that name the account — the platform rows survive.
--
-- NOT covered by either rule, and therefore handled explicitly in the endpoint:
-- auth_events.account_id is denormalized with no FK at all (0073, deliberately,
-- so the login trail outlives the user it describes). DELETE /admin/accounts
-- purges it by hand and then re-checks every account_id table for leftovers
-- before committing — see _assert_account_purged in api/routes/admin.py.
--
-- Constraint names are Postgres's own <table>_<column>_fkey defaults, which is
-- what every one of them is called on a database built by this runner; the
-- assertion at the bottom fails the migration loudly if that ever stops being
-- true, rather than leaving a half-cascading schema behind.

-- ── accounts(id) → ON DELETE CASCADE ─────────────────────────────────────────
-- (calls, property_field_audits, scoring_reveals, stripe_accounts and
-- tracking_numbers already declared CASCADE and are not repeated here.)

ALTER TABLE account_billing DROP CONSTRAINT IF EXISTS account_billing_account_id_fkey;
ALTER TABLE account_billing ADD CONSTRAINT account_billing_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE account_plans DROP CONSTRAINT IF EXISTS account_plans_account_id_fkey;
ALTER TABLE account_plans ADD CONSTRAINT account_plans_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_account_id_fkey;
ALTER TABLE appointments ADD CONSTRAINT appointments_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE connections DROP CONSTRAINT IF EXISTS connections_account_id_fkey;
ALTER TABLE connections ADD CONSTRAINT connections_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE customer_clusters DROP CONSTRAINT IF EXISTS customer_clusters_account_id_fkey;
ALTER TABLE customer_clusters ADD CONSTRAINT customer_clusters_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE expenses DROP CONSTRAINT IF EXISTS expenses_account_id_fkey;
ALTER TABLE expenses ADD CONSTRAINT expenses_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE geo_events DROP CONSTRAINT IF EXISTS geo_events_account_id_fkey;
ALTER TABLE geo_events ADD CONSTRAINT geo_events_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE geocode_queue DROP CONSTRAINT IF EXISTS geocode_queue_account_id_fkey;
ALTER TABLE geocode_queue ADD CONSTRAINT geocode_queue_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_account_id_fkey;
ALTER TABLE invoices ADD CONSTRAINT invoices_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE lead_events DROP CONSTRAINT IF EXISTS lead_events_account_id_fkey;
ALTER TABLE lead_events ADD CONSTRAINT lead_events_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE lead_feature_snapshots DROP CONSTRAINT IF EXISTS lead_feature_snapshots_account_id_fkey;
ALTER TABLE lead_feature_snapshots ADD CONSTRAINT lead_feature_snapshots_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE lead_geo_scores DROP CONSTRAINT IF EXISTS lead_geo_scores_account_id_fkey;
ALTER TABLE lead_geo_scores ADD CONSTRAINT lead_geo_scores_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE lead_score_snapshots DROP CONSTRAINT IF EXISTS lead_score_snapshots_account_id_fkey;
ALTER TABLE lead_score_snapshots ADD CONSTRAINT lead_score_snapshots_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE message_templates DROP CONSTRAINT IF EXISTS message_templates_account_id_fkey;
ALTER TABLE message_templates ADD CONSTRAINT message_templates_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE model_versions DROP CONSTRAINT IF EXISTS model_versions_account_id_fkey;
ALTER TABLE model_versions ADD CONSTRAINT model_versions_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_account_id_fkey;
ALTER TABLE orders ADD CONSTRAINT orders_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE pipeline_runs DROP CONSTRAINT IF EXISTS pipeline_runs_account_id_fkey;
ALTER TABLE pipeline_runs ADD CONSTRAINT pipeline_runs_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE pipeline_schedules DROP CONSTRAINT IF EXISTS pipeline_schedules_account_id_fkey;
ALTER TABLE pipeline_schedules ADD CONSTRAINT pipeline_schedules_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE pipeline_stages DROP CONSTRAINT IF EXISTS pipeline_stages_account_id_fkey;
ALTER TABLE pipeline_stages ADD CONSTRAINT pipeline_stages_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE policies DROP CONSTRAINT IF EXISTS policies_account_id_fkey;
ALTER TABLE policies ADD CONSTRAINT policies_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE properties DROP CONSTRAINT IF EXISTS properties_account_id_fkey;
ALTER TABLE properties ADD CONSTRAINT properties_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE prospect_pulls DROP CONSTRAINT IF EXISTS prospect_pulls_account_id_fkey;
ALTER TABLE prospect_pulls ADD CONSTRAINT prospect_pulls_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE quotes DROP CONSTRAINT IF EXISTS quotes_account_id_fkey;
ALTER TABLE quotes ADD CONSTRAINT quotes_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE record_field_defs DROP CONSTRAINT IF EXISTS record_field_defs_account_id_fkey;
ALTER TABLE record_field_defs ADD CONSTRAINT record_field_defs_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE segments DROP CONSTRAINT IF EXISTS segments_account_id_fkey;
ALTER TABLE segments ADD CONSTRAINT segments_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE service_areas DROP CONSTRAINT IF EXISTS service_areas_account_id_fkey;
ALTER TABLE service_areas ADD CONSTRAINT service_areas_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE signal_events DROP CONSTRAINT IF EXISTS signal_events_account_id_fkey;
ALTER TABLE signal_events ADD CONSTRAINT signal_events_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE social_imports DROP CONSTRAINT IF EXISTS social_imports_account_id_fkey;
ALTER TABLE social_imports ADD CONSTRAINT social_imports_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE social_metrics DROP CONSTRAINT IF EXISTS social_metrics_account_id_fkey;
ALTER TABLE social_metrics ADD CONSTRAINT social_metrics_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE social_posts DROP CONSTRAINT IF EXISTS social_posts_account_id_fkey;
ALTER TABLE social_posts ADD CONSTRAINT social_posts_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_account_id_fkey;
ALTER TABLE tasks ADD CONSTRAINT tasks_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE users DROP CONSTRAINT IF EXISTS users_account_id_fkey;
ALTER TABLE users ADD CONSTRAINT users_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE vertical_geo_config DROP CONSTRAINT IF EXISTS vertical_geo_config_account_id_fkey;
ALTER TABLE vertical_geo_config ADD CONSTRAINT vertical_geo_config_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE workflow_rule_firings DROP CONSTRAINT IF EXISTS workflow_rule_firings_account_id_fkey;
ALTER TABLE workflow_rule_firings ADD CONSTRAINT workflow_rule_firings_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;
ALTER TABLE workflow_rules DROP CONSTRAINT IF EXISTS workflow_rules_account_id_fkey;
ALTER TABLE workflow_rules ADD CONSTRAINT workflow_rules_account_id_fkey FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE;

-- ── users(id) → ON DELETE SET NULL (attribution, not ownership) ──────────────
-- (auth_events.user_id and calls.user_id already declared SET NULL;
-- user_tokens and oauth_identities already declared CASCADE.)

ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_assigned_to_fkey;
ALTER TABLE appointments ADD CONSTRAINT appointments_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE appointments DROP CONSTRAINT IF EXISTS appointments_created_by_fkey;
ALTER TABLE appointments ADD CONSTRAINT appointments_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE connections DROP CONSTRAINT IF EXISTS connections_created_by_fkey;
ALTER TABLE connections ADD CONSTRAINT connections_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE contact_history DROP CONSTRAINT IF EXISTS contact_history_created_by_fkey;
ALTER TABLE contact_history ADD CONSTRAINT contact_history_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE contact_notes DROP CONSTRAINT IF EXISTS contact_notes_created_by_fkey;
ALTER TABLE contact_notes ADD CONSTRAINT contact_notes_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE expenses DROP CONSTRAINT IF EXISTS expenses_created_by_fkey;
ALTER TABLE expenses ADD CONSTRAINT expenses_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE geo_events DROP CONSTRAINT IF EXISTS geo_events_created_by_fkey;
ALTER TABLE geo_events ADD CONSTRAINT geo_events_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE invoice_payments DROP CONSTRAINT IF EXISTS invoice_payments_created_by_fkey;
ALTER TABLE invoice_payments ADD CONSTRAINT invoice_payments_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE invoices DROP CONSTRAINT IF EXISTS invoices_created_by_fkey;
ALTER TABLE invoices ADD CONSTRAINT invoices_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE lead_events DROP CONSTRAINT IF EXISTS lead_events_actor_user_id_fkey;
ALTER TABLE lead_events ADD CONSTRAINT lead_events_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE message_templates DROP CONSTRAINT IF EXISTS message_templates_created_by_fkey;
ALTER TABLE message_templates ADD CONSTRAINT message_templates_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE orders DROP CONSTRAINT IF EXISTS orders_created_by_fkey;
ALTER TABLE orders ADD CONSTRAINT orders_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE pipeline_schedules DROP CONSTRAINT IF EXISTS pipeline_schedules_created_by_fkey;
ALTER TABLE pipeline_schedules ADD CONSTRAINT pipeline_schedules_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE pipeline_stages DROP CONSTRAINT IF EXISTS pipeline_stages_created_by_fkey;
ALTER TABLE pipeline_stages ADD CONSTRAINT pipeline_stages_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE policies DROP CONSTRAINT IF EXISTS policies_created_by_fkey;
ALTER TABLE policies ADD CONSTRAINT policies_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE properties DROP CONSTRAINT IF EXISTS properties_assigned_to_fkey;
ALTER TABLE properties ADD CONSTRAINT properties_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE properties DROP CONSTRAINT IF EXISTS properties_owner_id_fkey;
ALTER TABLE properties ADD CONSTRAINT properties_owner_id_fkey FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE prospect_pulls DROP CONSTRAINT IF EXISTS prospect_pulls_pulled_by_fkey;
ALTER TABLE prospect_pulls ADD CONSTRAINT prospect_pulls_pulled_by_fkey FOREIGN KEY (pulled_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE quotes DROP CONSTRAINT IF EXISTS quotes_created_by_fkey;
ALTER TABLE quotes ADD CONSTRAINT quotes_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE segments DROP CONSTRAINT IF EXISTS segments_created_by_fkey;
ALTER TABLE segments ADD CONSTRAINT segments_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE social_imports DROP CONSTRAINT IF EXISTS social_imports_created_by_fkey;
ALTER TABLE social_imports ADD CONSTRAINT social_imports_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE stage_transitions DROP CONSTRAINT IF EXISTS stage_transitions_transitioned_by_fkey;
ALTER TABLE stage_transitions ADD CONSTRAINT stage_transitions_transitioned_by_fkey FOREIGN KEY (transitioned_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE stripe_accounts DROP CONSTRAINT IF EXISTS stripe_accounts_created_by_fkey;
ALTER TABLE stripe_accounts ADD CONSTRAINT stripe_accounts_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_assigned_to_fkey;
ALTER TABLE tasks ADD CONSTRAINT tasks_assigned_to_fkey FOREIGN KEY (assigned_to) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE tasks DROP CONSTRAINT IF EXISTS tasks_created_by_fkey;
ALTER TABLE tasks ADD CONSTRAINT tasks_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;
ALTER TABLE workflow_rules DROP CONSTRAINT IF EXISTS workflow_rules_created_by_fkey;
ALTER TABLE workflow_rules ADD CONSTRAINT workflow_rules_created_by_fkey FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL;

-- ── The audit trail has to outlive the admin who wrote it ────────────────────
-- admin_audit_log.admin_user_id was NOT NULL REFERENCES users(id), which makes
-- every platform admin who ever touched the dashboard permanently undeletable —
-- the trail's own FK becomes the thing blocking the delete. Denormalize the
-- username at write time (api/admin_audit.py) and let the id go NULL, the same
-- trade 0073 already made for auth_events.account_id: the row keeps saying who
-- did it after the account is gone, it just stops being a live link.
ALTER TABLE admin_audit_log ADD COLUMN IF NOT EXISTS admin_username TEXT;
UPDATE admin_audit_log l SET admin_username = u.username
  FROM users u WHERE u.id = l.admin_user_id AND l.admin_username IS NULL;
ALTER TABLE admin_audit_log ALTER COLUMN admin_user_id DROP NOT NULL;
ALTER TABLE admin_audit_log DROP CONSTRAINT IF EXISTS admin_audit_log_admin_user_id_fkey;
ALTER TABLE admin_audit_log ADD CONSTRAINT admin_audit_log_admin_user_id_fkey FOREIGN KEY (admin_user_id) REFERENCES users(id) ON DELETE SET NULL;

-- Deleting one schedule should not take its run history with it — that history
-- is the record of what the schedule did. (During an org purge both sides are
-- cascaded from accounts anyway, so this only changes the single-schedule case.)
ALTER TABLE pipeline_runs DROP CONSTRAINT IF EXISTS pipeline_runs_schedule_id_fkey;
ALTER TABLE pipeline_runs ADD CONSTRAINT pipeline_runs_schedule_id_fkey FOREIGN KEY (schedule_id) REFERENCES pipeline_schedules(id) ON DELETE SET NULL;

-- ── Assertion: no FK into accounts may be left un-cascaded ───────────────────
-- The list above was generated from this database's own catalog, so it is
-- complete today. This turns "complete today" into something the migration
-- proves, and fails the deploy instead of shipping a schema where DELETE
-- /admin/accounts throws a foreign-key error on one forgotten table.
DO $$
DECLARE stragglers TEXT;
BEGIN
    SELECT string_agg(src.relname || '.' || a.attname, ', ' ORDER BY src.relname)
      INTO stragglers
      FROM pg_constraint c
      JOIN pg_class src ON src.oid = c.conrelid
      JOIN pg_class tgt ON tgt.oid = c.confrelid
      JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
     WHERE c.contype = 'f' AND tgt.relname = 'accounts' AND c.confdeltype <> 'c';
    IF stragglers IS NOT NULL THEN
        RAISE EXCEPTION 'FKs into accounts(id) still block a delete: %', stragglers;
    END IF;

    SELECT string_agg(src.relname || '.' || a.attname, ', ' ORDER BY src.relname)
      INTO stragglers
      FROM pg_constraint c
      JOIN pg_class src ON src.oid = c.conrelid
      JOIN pg_class tgt ON tgt.oid = c.confrelid
      JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = c.conkey[1]
     WHERE c.contype = 'f' AND tgt.relname = 'users' AND c.confdeltype = 'a';
    IF stragglers IS NOT NULL THEN
        RAISE EXCEPTION 'FKs into users(id) still block a delete: %', stragglers;
    END IF;
END $$;
