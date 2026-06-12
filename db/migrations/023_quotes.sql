-- 023_quotes.sql — quotes module (Phase 1): quotes + line items.
--
-- Quotes get their own number sequence (Q-2026-0001) separate from invoices.
-- When a quote is accepted and converted, a *fresh* invoice is created through
-- the normal next_invoice_number() default, so the invoice sequence stays
-- gapless for bookkeeping regardless of how many quotes are declined/expired.

CREATE SEQUENCE quote_seq START 1;

CREATE OR REPLACE FUNCTION next_quote_number()
RETURNS TEXT AS $$
  SELECT 'Q-' || EXTRACT(YEAR FROM NOW())::TEXT || '-' || LPAD(nextval('quote_seq')::TEXT, 4, '0')
$$ LANGUAGE sql;

CREATE TABLE quotes (
  id             SERIAL PRIMARY KEY,
  quote_number   TEXT NOT NULL UNIQUE DEFAULT next_quote_number(),
  property_id    INTEGER REFERENCES properties(id) ON DELETE SET NULL,
  client_name    TEXT NOT NULL,
  client_phone   TEXT,
  client_email   TEXT,
  client_address TEXT,
  status         TEXT NOT NULL DEFAULT 'draft',  -- draft | sent | accepted | declined | expired
  subtotal       NUMERIC(10,2) NOT NULL DEFAULT 0,
  tax_rate       NUMERIC(5,2)  NOT NULL DEFAULT 0,
  tax_amount     NUMERIC(10,2) NOT NULL DEFAULT 0,
  total          NUMERIC(10,2) NOT NULL DEFAULT 0,
  issue_date     DATE NOT NULL DEFAULT CURRENT_DATE,
  valid_until    DATE,
  notes          TEXT,

  -- delivery tracking (mirrors 015_invoice_delivery)
  sent_at         TIMESTAMPTZ,
  sent_channels   TEXT[],
  last_emailed_at TIMESTAMPTZ,
  last_sms_at     TIMESTAMPTZ,

  -- lifecycle
  accepted_at          TIMESTAMPTZ,
  declined_at          TIMESTAMPTZ,
  converted_invoice_id INTEGER REFERENCES invoices(id) ON DELETE SET NULL,

  created_by     INTEGER REFERENCES users(id),
  account_id     INTEGER NOT NULL REFERENCES accounts(id),
  created_at     TIMESTAMPTZ DEFAULT NOW(),
  updated_at     TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE quote_line_items (
  id          SERIAL PRIMARY KEY,
  quote_id    INTEGER NOT NULL REFERENCES quotes(id) ON DELETE CASCADE,
  description TEXT NOT NULL,
  quantity    NUMERIC(10,3) NOT NULL DEFAULT 1,
  unit_price  NUMERIC(10,2) NOT NULL,
  sort_order  INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX idx_quotes_account     ON quotes(account_id);
CREATE INDEX idx_quotes_property    ON quotes(property_id);
CREATE INDEX idx_quotes_status      ON quotes(status);
CREATE INDEX idx_quote_items_quote  ON quote_line_items(quote_id, sort_order);

CREATE TRIGGER quotes_updated_at
  BEFORE UPDATE ON quotes
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
