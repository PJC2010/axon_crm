-- expenses: track business spending for tax season

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE expenses (
  id                SERIAL PRIMARY KEY,
  amount            NUMERIC(10,2) NOT NULL,
  category          TEXT NOT NULL,
  vendor            TEXT NOT NULL,
  description       TEXT,
  expense_date      DATE NOT NULL,
  payment_method    TEXT NOT NULL DEFAULT 'card',
  is_tax_deductible BOOLEAN NOT NULL DEFAULT TRUE,
  property_id       INTEGER REFERENCES properties(id) ON DELETE SET NULL,
  receipt_url       TEXT,
  created_by        INTEGER REFERENCES users(id),
  created_at        TIMESTAMPTZ DEFAULT NOW(),
  updated_at        TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_expenses_date     ON expenses (expense_date DESC);
CREATE INDEX idx_expenses_category ON expenses (category);
CREATE INDEX idx_expenses_user     ON expenses (created_by);

CREATE TRIGGER expenses_updated_at
  BEFORE UPDATE ON expenses
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
