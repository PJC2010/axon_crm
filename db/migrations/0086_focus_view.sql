-- focus_view — server-chosen surfacing cutoff for the default lead list.
--
-- A pipeline run seeds every parcel in the ZIP as a live lead, which buries
-- the good ones. The focus view narrows the default lead list to the account's
-- top grade bands; the cutoff is picked automatically after every scoring pass
-- (pipeline/focus.py: widen band by band until a workable floor count is met),
-- never entered by the user. NULL = focus off (account too thin to shortlist,
-- or nothing scored yet). Only the threshold is stored — the banner's counts
-- are always computed live, so a stale cutoff can mis-size the shortlist but
-- never mis-report it. Thresholds are GRADE_BANDS values (config.py), so the
-- cutoff always falls on a whole grade band.
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS focus_score_cutoff REAL;
ALTER TABLE accounts ADD COLUMN IF NOT EXISTS focus_updated_at TIMESTAMPTZ;
