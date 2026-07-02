-- 046_order_import.sql — Phase 8 (integrations): dedup key for imported orders.
--
-- POS/e-commerce exports (Square, Shopify) carry a stable external order id.
-- A partial unique index on (account_id, order_number) lets the orders importer
-- upsert on re-import (ON CONFLICT) instead of duplicating rows, while orders
-- created in-app without a number are unaffected.

CREATE UNIQUE INDEX IF NOT EXISTS uniq_orders_account_number
    ON orders (account_id, order_number)
    WHERE order_number IS NOT NULL;
