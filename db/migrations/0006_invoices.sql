-- invoices, line items, and payments for bookkeeping module

CREATE SEQUENCE invoice_seq START 1;

CREATE OR REPLACE FUNCTION next_invoice_number()
RETURNS TEXT AS $$
  SELECT 'INV-' || EXTRACT(YEAR FROM NOW())::TEXT || '-' || LPAD(nextval('invoice_seq')::TEXT, 4, '0')
$$ LANGUAGE sql;

CREATE TABLE invoices (
  id             SERIAL PRIMARY KEY,
  invoice_number TEXT NOT NULL UNIQUE DEFAULT next_invoice_number(),
  property_id    INTEGER REFERENCES properties(id) ON DELETE SET NULL,
  client_name    TEXT NOT NULL,
  client_phone   TEXT,
  client_email   TEXT,
  client_address TEXT,
  status         TEXT NOT NULL DEFAULT 'draft',
  subtotal       NUMERIC(10,2) NOT NULL DEFAULT 0,
  tax_rate       NUMERIC(5,2)  NOT NULL DEFAULT 0,
  tax_amount     NUMERIC(10,2) NOT NULL DEFAULT 0,
  total          NUMERIC(10,2) NOT NULL DEFAULT 0,
  amount_paid    NUMERIC(10,2) NOT NULL DEFAULT 0,
  issue_date     DATE NOT NULL DEFAULT CURRENT_DATE,
  due_date       DATE,
  notes          TEXT,
  created_by     INTEGER REFERENCES users(id),
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE invoice_line_items (
  id           SERIAL PRIMARY KEY,
  invoice_id   INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  description  TEXT NOT NULL,
  quantity     NUMERIC(10,3) NOT NULL DEFAULT 1,
  unit_price   NUMERIC(10,2) NOT NULL,
  sort_order   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE invoice_payments (
  id             SERIAL PRIMARY KEY,
  invoice_id     INTEGER NOT NULL REFERENCES invoices(id) ON DELETE CASCADE,
  amount         NUMERIC(10,2) NOT NULL,
  payment_date   DATE NOT NULL DEFAULT CURRENT_DATE,
  payment_method TEXT NOT NULL DEFAULT 'card',
  notes          TEXT,
  created_by     INTEGER REFERENCES users(id),
  created_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_invoices_property  ON invoices(property_id);
CREATE INDEX idx_invoices_status    ON invoices(status);
CREATE INDEX idx_invoices_due       ON invoices(due_date, status);
CREATE INDEX idx_line_items_invoice ON invoice_line_items(invoice_id, sort_order);
CREATE INDEX idx_payments_invoice   ON invoice_payments(invoice_id);

CREATE TRIGGER invoices_updated_at
  BEFORE UPDATE ON invoices
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
