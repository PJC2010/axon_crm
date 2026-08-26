-- fk_support_indexes — index every FK child column, so deleting a parent row
-- is a lookup instead of a sequential scan.
--
-- Migration 0074 made an organization deletable by handing the teardown to
-- Postgres: every FK into accounts(id) is ON DELETE CASCADE, so
-- `DELETE FROM accounts WHERE id = 5` is the whole purge. What it did not do is
-- give Postgres a way to *find* the child rows. A referential-integrity action
-- is an AFTER-ROW trigger: for each deleted parent row, and for each FK
-- pointing at it, the server runs one query against the child table —
--
--     DELETE FROM ONLY child   WHERE $1 = fk_col          -- ON DELETE CASCADE
--     UPDATE ONLY child SET fk_col = NULL WHERE $1 = fk_col  -- ON DELETE SET NULL
--
-- On an indexed child column that is a sub-millisecond index probe. On an
-- unindexed one it is a full sequential scan of the child table, repeated once
-- per parent row, and the delete becomes quadratic. That is what took the admin
-- dashboard's DELETE /admin/accounts/{id} past the 30s statement_timeout
-- (DB_STATEMENT_TIMEOUT_MS, api/deps.py) and returned QueryCanceled to the
-- operator; the statement the timeout happened to interrupt was
-- `UPDATE ONLY policies SET property_id = NULL WHERE $1 = property_id`, one of
-- the nineteen child queries `properties` fires per deleted lead.
--
-- Two shapes of the problem, both fixed here:
--
--   * Child of a HIGH-CARDINALITY parent — properties (19 child FKs) and users
--     (29). The trigger fires once per deleted row, so an unindexed child is
--     scanned N times. `expenses.property_id` and `scoring_reveals.property_id`
--     were scanned once per lead; the seventeen users(id) attribution columns
--     were scanned once per user, and two of them (properties.assigned_to,
--     properties.owner_id) mean each deleted rep sequentially scanned the
--     largest table in the database twice.
--
--   * Child of accounts(id) — six tables carrying account_id with no index on
--     it. The trigger fires once (one account row), so this is not quadratic,
--     but it is still a seq scan of tables that grow without bound
--     (geocode_queue, lead_score_snapshots), inside the same capped statement.
--     Those indexes pay for themselves anyway: account_id is the scoping
--     predicate of every tenant query, and _assert_account_purged's EXISTS
--     probe reads exactly this column on exactly these tables.
--
-- On index cost, and why this does not undo 0078: 0078 dropped indexes no query
-- could reach, having measured index maintenance at 94% of a bulk seed's write
-- cost. Every index here is reachable by construction — the RI trigger is a
-- real query shape the server runs on its own. The write cost is kept near zero
-- by matching the index to the column: the twenty-eight nullable columns below
-- are attribution (created_by / assigned_to / actor_user_id), NULL on every
-- pipeline-seeded row, so they are indexed PARTIAL on `IS NOT NULL`. Postgres
-- stores no entry for a row failing the predicate, so a 47k-row seed writing
-- assigned_to IS NULL adds nothing to idx_properties_assigned_to_fk and does
-- not lose HOT on it. The planner still uses such an index for `col = $1`,
-- generic plan included, because a strict operator implies IS NOT NULL — the
-- predicate is proved, not guessed. The seven NOT NULL columns get plain
-- indexes because a partial one would index the same rows at no saving.
--
-- Naming: <table>_<column>_fk so these read as what they are — FK support, not
-- an access path someone chose for a query — and so the assertion at the bottom
-- has an obvious thing to point at. Existing indexes that already serve an FK
-- keep their own names; nothing here is renamed.

-- CREATE INDEX takes SHARE on the table: it blocks writes, not reads, and the
-- request queues behind in-flight writes while new writes queue behind it. Same
-- trade 0077/0078 made — fail fast and let a migrate.py re-run be the retry,
-- since every statement is IF NOT EXISTS. (CONCURRENTLY is not an option: the
-- runner wraps each migration in a transaction.)
SET LOCAL lock_timeout = '10s';

-- ── Children of accounts(id): scanned once per account delete ────────────────
CREATE INDEX IF NOT EXISTS geocode_queue_account_id_fk        ON geocode_queue (account_id);
CREATE INDEX IF NOT EXISTS lead_score_snapshots_account_id_fk ON lead_score_snapshots (account_id);
CREATE INDEX IF NOT EXISTS pipeline_schedules_account_id_fk   ON pipeline_schedules (account_id);
CREATE INDEX IF NOT EXISTS workflow_rules_account_id_fk       ON workflow_rules (account_id);
-- model_versions.account_id and vertical_geo_config.account_id are nullable:
-- NULL means "platform-wide default" (0074), and those rows are not the
-- account's to delete, so the partial index is both cheaper and exactly right.
CREATE INDEX IF NOT EXISTS model_versions_account_id_fk       ON model_versions (account_id) WHERE account_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS vertical_geo_config_account_id_fk  ON vertical_geo_config (account_id) WHERE account_id IS NOT NULL;

-- ── Children of properties(id): scanned once per deleted lead ────────────────
CREATE INDEX IF NOT EXISTS scoring_reveals_property_id_fk ON scoring_reveals (property_id);
CREATE INDEX IF NOT EXISTS expenses_property_id_fk        ON expenses (property_id) WHERE property_id IS NOT NULL;

-- ── Children of invoices(id) / pipeline_schedules(id) / tracking_numbers(id) ─
CREATE INDEX IF NOT EXISTS invoices_recurring_source_id_fk ON invoices (recurring_source_id) WHERE recurring_source_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS quotes_converted_invoice_id_fk  ON quotes (converted_invoice_id) WHERE converted_invoice_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS pipeline_runs_schedule_id_fk    ON pipeline_runs (schedule_id) WHERE schedule_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS calls_tracking_number_id_fk     ON calls (tracking_number_id) WHERE tracking_number_id IS NOT NULL;

-- ── Children of users(id): attribution columns, scanned once per deleted user ─
-- All nullable and all sparse, so all partial. properties carries two of them
-- and is the table 0078 was protecting; both stay empty under a bulk seed.
CREATE INDEX IF NOT EXISTS properties_assigned_to_fk          ON properties (assigned_to) WHERE assigned_to IS NOT NULL;
CREATE INDEX IF NOT EXISTS properties_owner_id_fk             ON properties (owner_id) WHERE owner_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS admin_audit_log_admin_user_id_fk   ON admin_audit_log (admin_user_id) WHERE admin_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS appointments_created_by_fk         ON appointments (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS calls_user_id_fk                   ON calls (user_id) WHERE user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS contact_history_created_by_fk      ON contact_history (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS contact_notes_created_by_fk        ON contact_notes (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS geo_events_created_by_fk           ON geo_events (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS invoice_payments_created_by_fk     ON invoice_payments (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS invoices_created_by_fk             ON invoices (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS lead_events_actor_user_id_fk       ON lead_events (actor_user_id) WHERE actor_user_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS message_templates_created_by_fk    ON message_templates (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS orders_created_by_fk               ON orders (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS pipeline_schedules_created_by_fk   ON pipeline_schedules (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS pipeline_stages_created_by_fk      ON pipeline_stages (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS policies_created_by_fk             ON policies (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS prospect_pulls_pulled_by_fk        ON prospect_pulls (pulled_by) WHERE pulled_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS quotes_created_by_fk               ON quotes (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS segments_created_by_fk             ON segments (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS stage_transitions_transitioned_by_fk ON stage_transitions (transitioned_by) WHERE transitioned_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS stripe_accounts_created_by_fk      ON stripe_accounts (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS tasks_created_by_fk                ON tasks (created_by) WHERE created_by IS NOT NULL;
CREATE INDEX IF NOT EXISTS workflow_rules_created_by_fk       ON workflow_rules (created_by) WHERE created_by IS NOT NULL;

-- ── Assertion: no FK may be left without a supporting index ──────────────────
-- The companion to 0074's "no FK into accounts may be left un-cascaded". That
-- one proves the delete *reaches* every table; this one proves it can reach
-- them in bounded time. Together they are the whole contract of
-- DELETE /admin/accounts/{id}, and both fail the deploy rather than shipping a
-- schema where it 500s or times out in front of an operator.
--
-- "Supporting" means an index whose LEADING columns are the FK's columns, in
-- order — that is the only shape the RI query can use. A partial index counts:
-- its predicate is `IS NOT NULL`, which `col = $1` implies. A composite index
-- that merely *contains* the column does not, which is why
-- idx_properties_assigned — (account_id, assigned_to) — never helped here.
DO $$
DECLARE unsupported TEXT;
BEGIN
    SELECT string_agg(src.relname || '.' || cols, ', ' ORDER BY src.relname, cols)
      INTO unsupported
      FROM pg_constraint c
      JOIN pg_class src ON src.oid = c.conrelid
      JOIN pg_namespace n ON n.oid = src.relnamespace AND n.nspname = 'public'
      CROSS JOIN LATERAL (
        SELECT string_agg(a.attname, ',' ORDER BY k.ord) AS cols
          FROM unnest(c.conkey) WITH ORDINALITY AS k(attnum, ord)
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
      ) AS fk
     WHERE c.contype = 'f'
       AND NOT EXISTS (
         SELECT 1 FROM pg_index i
          WHERE i.indrelid = c.conrelid
            AND i.indislive AND i.indisvalid
            AND (i.indkey::int2[])[0:array_length(c.conkey, 1) - 1] = c.conkey
       );
    IF unsupported IS NOT NULL THEN
        RAISE EXCEPTION 'FK child column(s) with no supporting index — deleting the parent would sequentially scan: %', unsupported;
    END IF;
END $$;
