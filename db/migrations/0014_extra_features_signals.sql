-- Extra-feature signals: pool, cracked slab, garage type
-- has_pool / has_cracked_slab come from HCAD extra_features.txt
-- garage_type is the Attom garageType string (Attached / Detached / etc.)

ALTER TABLE properties ADD COLUMN IF NOT EXISTS has_pool         BOOLEAN DEFAULT FALSE;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS has_cracked_slab BOOLEAN DEFAULT FALSE;
ALTER TABLE properties ADD COLUMN IF NOT EXISTS garage_type      TEXT;

-- Postgres mirror of the HCAD extra_features.txt file.
-- Used as fallback when harris_county.duckdb is unavailable.
-- Only the columns needed by the pipeline are stored.
CREATE TABLE IF NOT EXISTS hcad_extra_features (
    acct    TEXT NOT NULL,
    bld_num TEXT NOT NULL DEFAULT '',
    cd      TEXT,           -- use code (see desc_r_10_extra_features.txt)
    s_dscr  TEXT,           -- short description
    l_dscr  TEXT,           -- long description
    units   TEXT,           -- quantity / unit count
    PRIMARY KEY (acct, bld_num, cd)
);

CREATE INDEX IF NOT EXISTS idx_hcad_ef_acct ON hcad_extra_features(acct);
CREATE INDEX IF NOT EXISTS idx_hcad_ef_zip
    ON hcad_extra_features(acct)
    WHERE cd IS NOT NULL;
