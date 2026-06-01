-- Foundation schema: properties, contact_notes, contact_history
-- This table existed before the migration system was introduced.

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS properties (
    id                  SERIAL PRIMARY KEY,
    address             TEXT NOT NULL,
    city                TEXT,
    state               TEXT,
    zip                 TEXT,
    latitude            DOUBLE PRECISION,
    longitude           DOUBLE PRECISION,
    geohash             TEXT,
    year_built          INTEGER,
    square_footage      INTEGER,
    garage_spaces       INTEGER,
    lot_size            DOUBLE PRECISION,
    property_type       TEXT,
    estimated_value     INTEGER,
    estimated_equity    INTEGER,
    last_sale_date      DATE,
    last_sale_price     INTEGER,
    owner_name          TEXT,
    owner_occupied      BOOLEAN,
    ownership_years     INTEGER,
    zip_median_income   INTEGER,
    permit_count_24mo   INTEGER,
    lead_score          DOUBLE PRECISION,
    score_grade         TEXT,
    vertical            TEXT,
    score_updated_at    TIMESTAMP,
    enrichment_flags    JSONB DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'new',
    created_at          TIMESTAMP DEFAULT NOW(),
    updated_at          TIMESTAMP DEFAULT NOW(),
    UNIQUE (address, zip)
);

CREATE INDEX IF NOT EXISTS idx_zip_score  ON properties(zip, lead_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_vertical   ON properties(vertical, score_grade);
CREATE INDEX IF NOT EXISTS idx_geo        ON properties(longitude, latitude);

CREATE OR REPLACE TRIGGER trg_properties_updated_at
    BEFORE UPDATE ON properties
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TABLE IF NOT EXISTS contact_notes (
    id          SERIAL PRIMARY KEY,
    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    note        TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_notes_property ON contact_notes(property_id);

CREATE TABLE IF NOT EXISTS contact_history (
    id          SERIAL PRIMARY KEY,
    property_id INTEGER NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    action      TEXT NOT NULL,
    outcome     TEXT,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_history_property ON contact_history(property_id);
