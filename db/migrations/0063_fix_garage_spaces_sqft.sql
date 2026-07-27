-- fix_garage_spaces_sqft
-- hcad_enrichment historically wrote SUM(extra_features.uts) — garage square
-- footage, not a space count — into properties.garage_spaces (e.g. a 462 sqft
-- garage displayed as "462 spaces"). Convert implausible values to an
-- estimated space count at ~240 sqft per car, matching
-- pipeline/hcad_store.garage_spaces_from_sqft(). Legitimate counts (<= 10)
-- are left untouched.
UPDATE properties
SET garage_spaces = GREATEST(1, LEAST(10, ROUND(garage_spaces / 240.0)::int))
WHERE garage_spaces > 10;
