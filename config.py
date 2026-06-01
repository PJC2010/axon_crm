import os

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/smart_crm")

# ── Harris County Appraisal District DuckDB ───────────────────────────────────
PERMIT_DB_PATH = os.getenv("PERMIT_DB_PATH", "/Users/petecastillo/property_data/harris_county.duckdb")

# ── API keys ─────────────────────────────────────────────────────────────────
RENTCAST_API_KEY    = os.getenv("RENTCAST_API_KEY", "")
ATTOM_API_KEY       = os.getenv("ATTOM_API_KEY", "")
GOOGLE_GEOCODE_KEY  = os.getenv("GOOGLE_GEOCODE_KEY", "")
CENSUS_API_KEY      = os.getenv("CENSUS_API_KEY", "")   # optional; ACS works without one

# ── Score weights (must sum to 1.0) ──────────────────────────────────────────
# Default weights from context - score.docx.
# Override per vertical by passing a weights dict to the scorer.
DEFAULT_WEIGHTS = {
    "age":    0.25,   # home age in renovation sweet spot (15–30 years)
    "sale":   0.22,   # recency of last sale
    "equity": 0.18,   # estimated equity >= $100k
    "garage": 0.15,   # garage spaces >= 2
    "income": 0.12,   # zip median income
    "permit": 0.08,   # permit activity in last 24 months
}

# Per-vertical weight overrides. Keys match vertical names used in the DB.
VERTICAL_WEIGHTS = {
    "epoxy_flooring": {
        "age":    0.25,
        "sale":   0.20,
        "equity": 0.18,
        "garage": 0.22,   # garage is more important for epoxy
        "income": 0.10,
        "permit": 0.05,
    },
    "pool_maintenance": {
        "age":    0.15,
        "sale":   0.25,
        "equity": 0.20,
        "garage": 0.05,
        "income": 0.25,
        "permit": 0.10,
    },
    "solar": {
        "age":    0.10,
        "sale":   0.20,
        "equity": 0.30,
        "garage": 0.10,
        "income": 0.25,
        "permit": 0.05,
    },
}

# ── Signal thresholds ────────────────────────────────────────────────────────
AGE_SWEET_SPOT_MIN   = 15    # years
AGE_SWEET_SPOT_MAX   = 30    # years
SALE_RECENCY_MAX_MO  = 24    # months — anything older scores 0
EQUITY_TARGET        = 100_000   # USD
GARAGE_TARGET        = 2     # spaces
INCOME_TARGET        = 75_000    # zip median USD
PERMIT_TARGET        = 2     # permits in 24 months

# ── Grade bands ──────────────────────────────────────────────────────────────
GRADE_BANDS = [
    (75, "A"),
    (55, "B"),
    (35, "C"),
    (0,  "D"),
]

# ── RentCast ─────────────────────────────────────────────────────────────────
RENTCAST_BASE_URL = "https://api.rentcast.io/v1"

# ── Attom ────────────────────────────────────────────────────────────────────
ATTOM_BASE_URL = "https://api.gateway.attomdata.com/propertyapi/v1.0.0"

# ── Google Geocoding ─────────────────────────────────────────────────────────
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# ── Census ACS ───────────────────────────────────────────────────────────────
CENSUS_ACS_URL = "https://api.census.gov/data/2022/acs/acs5"
CENSUS_INCOME_VAR = "B19013_001E"   # median household income
