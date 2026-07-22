-- 043_child_objects.sql — Phase 5 of the multi-vertical generalization
-- (docs/GENERALIZATION_ROADMAP.md §4, "Associated objects").
--
-- Three typed child-object tables associated to the core record (properties):
--   policies     — insurance book of business (renewal dates drive date_offset
--                  workflow rules; see DATE_TRIGGER_SOURCES in api/workflow_engine.py)
--   orders       — retail purchase history (feeds RFM segmentation later);
--                  summary rows with items as JSONB, not composed documents,
--                  so no line-item child table
--   appointments — reintroduces the 031 schema (dropped by 037) for
--                  appointment-based verticals
--
-- All follow the quotes (023) conventions: account_id NOT NULL tenant key,
-- property_id ON DELETE SET NULL, created_by, TIMESTAMPTZ pair with the
-- set_updated_at() trigger (defined in 005), indexes on account/property/status.

CREATE TABLE IF NOT EXISTS policies (
  id             SERIAL PRIMARY KEY,
  account_id     INTEGER NOT NULL REFERENCES accounts(id),
  property_id    INTEGER REFERENCES properties(id) ON DELETE SET NULL,
  policy_number  TEXT,
  carrier        TEXT,
  policy_type    TEXT,                                -- line of business (auto/home/life/…)
  premium        NUMERIC(12,2),                       -- annualized premium
  billing_frequency TEXT,                             -- annual | semiannual | quarterly | monthly
  effective_date  DATE,
  expiration_date DATE,                               -- the renewal/X-date
  status         TEXT NOT NULL DEFAULT 'quoted',      -- quoted | active | lapsed | cancelled
  commission_rate NUMERIC(5,2),                       -- percent
  notes          TEXT,
  created_by     INTEGER REFERENCES users(id),
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_policies_account    ON policies(account_id);
CREATE INDEX IF NOT EXISTS idx_policies_property   ON policies(property_id);
CREATE INDEX IF NOT EXISTS idx_policies_status     ON policies(status);
-- Renewal scans: the daily workflow tick and the renewals-next-30-days KPI.
CREATE INDEX IF NOT EXISTS idx_policies_expiration ON policies(account_id, expiration_date);

CREATE TRIGGER policies_updated_at
  BEFORE UPDATE ON policies
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();


CREATE TABLE IF NOT EXISTS orders (
  id           SERIAL PRIMARY KEY,
  account_id   INTEGER NOT NULL REFERENCES accounts(id),
  property_id  INTEGER REFERENCES properties(id) ON DELETE SET NULL,
  order_number TEXT,                                  -- external POS/e-commerce id
  order_date   DATE NOT NULL DEFAULT CURRENT_DATE,
  total        NUMERIC(12,2) NOT NULL DEFAULT 0,
  item_count   INTEGER,
  items        JSONB NOT NULL DEFAULT '[]',           -- [{description, quantity, price}]
  channel      TEXT,                                  -- in_store | online | marketplace | …
  status       TEXT NOT NULL DEFAULT 'completed',     -- pending | completed | refunded | cancelled
  notes        TEXT,
  created_by   INTEGER REFERENCES users(id),
  created_at   TIMESTAMPTZ DEFAULT NOW(),
  updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_orders_account  ON orders(account_id);
CREATE INDEX IF NOT EXISTS idx_orders_property ON orders(property_id);
CREATE INDEX IF NOT EXISTS idx_orders_status   ON orders(status);
-- Recency/frequency scans: RFM roll-ups and the revenue-MTD KPI.
CREATE INDEX IF NOT EXISTS idx_orders_date     ON orders(account_id, order_date);

CREATE TRIGGER orders_updated_at
  BEFORE UPDATE ON orders
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- Reintroduced 031 schema (dropped by 037), unchanged.
CREATE TABLE IF NOT EXISTS appointments (
    id           SERIAL PRIMARY KEY,
    account_id   INTEGER NOT NULL REFERENCES accounts(id),
    property_id  INTEGER REFERENCES properties(id) ON DELETE SET NULL,
    assigned_to  INTEGER REFERENCES users(id),
    title        TEXT NOT NULL,
    location     TEXT,
    starts_at    TIMESTAMPTZ NOT NULL,
    ends_at      TIMESTAMPTZ NOT NULL,
    status       TEXT NOT NULL DEFAULT 'scheduled',  -- scheduled | completed | cancelled | no_show
    notes        TEXT,
    created_by   INTEGER REFERENCES users(id),
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_appt_account_time ON appointments(account_id, starts_at);
CREATE INDEX IF NOT EXISTS idx_appt_property     ON appointments(property_id);
CREATE INDEX IF NOT EXISTS idx_appt_assigned     ON appointments(assigned_to, starts_at);

CREATE TRIGGER appointments_updated_at
  BEFORE UPDATE ON appointments
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();


-- Backfill: the three new module keys default OFF for existing accounts.
-- get_account_modules() resolves a missing key permissively from the plan (all
-- three land in `pro`), so without this every existing pro account would wake
-- up with three new nav items. New-vertical presets (Phase 6) opt in instead.
UPDATE account_plans
SET modules = COALESCE(modules, '{}'::jsonb)
           || '{"policies": false, "orders": false, "appointments": false}'::jsonb
WHERE NOT (COALESCE(modules, '{}'::jsonb) ?& ARRAY['policies', 'orders', 'appointments']);
