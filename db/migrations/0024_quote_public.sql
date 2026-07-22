-- 024_quote_public.sql — public quote links (Phase 2).
--
-- Each quote gets an unguessable token used by the unauthenticated customer
-- page (/q/{token}) for view / accept / decline. viewed_at gives read
-- receipts; decline_reason captures the customer's optional note.

ALTER TABLE quotes ADD COLUMN public_token   TEXT NOT NULL UNIQUE DEFAULT gen_random_uuid()::text;
ALTER TABLE quotes ADD COLUMN viewed_at      TIMESTAMPTZ;
ALTER TABLE quotes ADD COLUMN decline_reason TEXT;
