CREATE TABLE IF NOT EXISTS properties (
    id                SERIAL PRIMARY KEY,
    address           TEXT NOT NULL,
    city              TEXT,
    state             TEXT,
    zip               TEXT,
    latitude          FLOAT,
    longitude         FLOAT,
    geohash           TEXT,
    year_built        INT,
    square_footage    INT,
    garage_spaces     INT,
    lot_size          FLOAT,
    property_type     TEXT,
    estimated_value   INT,
    estimated_equity  INT,
    last_sale_date    DATE,
    last_sale_price   INT,
    owner_name        TEXT,
    owner_occupied    BOOLEAN,
    ownership_years   INT,
    zip_median_income INT,
    permit_count_24mo INT,
    lead_score        FLOAT,
    score_grade       TEXT,
    vertical          TEXT,
    score_updated_at  TIMESTAMP,
    enrichment_flags  JSONB DEFAULT '{}'::jsonb,
    created_at        TIMESTAMP DEFAULT NOW(),
    updated_at        TIMESTAMP DEFAULT NOW(),
    UNIQUE (address, zip)
);

CREATE INDEX IF NOT EXISTS idx_zip_score ON properties (zip, lead_score DESC NULLS LAST);
CREATE INDEX IF NOT EXISTS idx_geo       ON properties (longitude, latitude);
CREATE INDEX IF NOT EXISTS idx_vertical  ON properties (vertical, score_grade);

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_properties_updated_at ON properties;
CREATE TRIGGER trg_properties_updated_at
    BEFORE UPDATE ON properties
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ── Phase 2 additions ─────────────────────────────────────────────────────────

ALTER TABLE properties ADD COLUMN IF NOT EXISTS
    status TEXT NOT NULL DEFAULT 'new';
-- Allowed values: new | contacted | qualified | not_interested | converted

CREATE TABLE IF NOT EXISTS contact_notes (
    id          SERIAL PRIMARY KEY,
    property_id INT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    note        TEXT NOT NULL,
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_notes_property ON contact_notes (property_id);

CREATE TABLE IF NOT EXISTS contact_history (
    id          SERIAL PRIMARY KEY,
    property_id INT NOT NULL REFERENCES properties(id) ON DELETE CASCADE,
    action      TEXT NOT NULL,   -- e.g. "Called", "Door knocked", "Emailed"
    outcome     TEXT,            -- e.g. "No answer", "Interested", "Booked"
    created_at  TIMESTAMP DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_history_property ON contact_history (property_id);
