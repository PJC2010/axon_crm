-- 0057_account_review_link.sql — where customers leave the business a review.
--
-- Powers the review-request automation (audit P1: "job hits won → wait 2 days →
-- SMS with the owner's Google review link"). The link renders into message
-- templates via the {{review_link}} merge field (api/messaging.py); sends that
-- reference it are skipped while the account hasn't set one, so the default
-- rule can ship enabled without ever sending a broken message.

ALTER TABLE accounts ADD COLUMN IF NOT EXISTS review_link TEXT;
