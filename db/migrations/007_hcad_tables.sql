-- Harris County Appraisal District data (migrated from DuckDB)
-- Only the columns used by the pipeline are stored.

CREATE TABLE IF NOT EXISTS hcad_properties (
    acct             TEXT NOT NULL,
    site_address     TEXT,
    site_zip         TEXT,
    year_built       TEXT,
    building_sqft    BIGINT,
    land_sqft        BIGINT,
    tot_appr_val     BIGINT,
    last_sale_date   DATE,
    owner_name       TEXT,
    likely_owner_occupied BOOLEAN,
    PRIMARY KEY (acct)
);

CREATE INDEX IF NOT EXISTS idx_hcad_props_zip ON hcad_properties(site_zip);
CREATE INDEX IF NOT EXISTS idx_hcad_props_addr ON hcad_properties(site_zip, site_address);

CREATE TABLE IF NOT EXISTS hcad_permits (
    acct         TEXT NOT NULL,
    permit_id    BIGINT NOT NULL,
    status       TEXT,
    issue_date   DATE,
    permit_type  TEXT,
    description  TEXT,
    PRIMARY KEY (acct, permit_id)
);

CREATE INDEX IF NOT EXISTS idx_hcad_permits_acct ON hcad_permits(acct);
CREATE INDEX IF NOT EXISTS idx_hcad_permits_date ON hcad_permits(issue_date);
