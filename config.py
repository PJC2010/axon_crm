import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/smart_crm")

# ── Harris County Appraisal District DuckDB ───────────────────────────────────
PERMIT_DB_PATH = os.getenv("PERMIT_DB_PATH", "/Users/petecastillo/property_data/harris_county.duckdb")

# ── API keys ─────────────────────────────────────────────────────────────────
RENTCAST_API_KEY    = os.getenv("RENTCAST_API_KEY", "")
ATTOM_API_KEY       = os.getenv("ATTOM_API_KEY", "")
GOOGLE_GEOCODE_KEY  = os.getenv("GOOGLE_GEOCODE_KEY", "")
CENSUS_API_KEY      = os.getenv("CENSUS_API_KEY", "")   # optional; ACS works without one

# ── Contact / skip-trace enrichment (fills contact_name/phone/email) ──────────
# Provider-pluggable; default "" means the contact step is skipped (no key).
# Supported providers: see pipeline/contact.py PROVIDERS.
CONTACT_PROVIDER         = os.getenv("CONTACT_PROVIDER", "")
CONTACT_API_KEY          = os.getenv("CONTACT_API_KEY", "")
CONTACT_BASE_URL         = os.getenv("CONTACT_BASE_URL", "")
CONTACT_MAX_ROWS_PER_ZIP = int(os.getenv("CONTACT_MAX_ROWS_PER_ZIP", "200"))
# Only skip-trace leads at or above this grade ("" = no grade filter). A is best.
CONTACT_MIN_GRADE        = os.getenv("CONTACT_MIN_GRADE", "")

# ── HTTP robustness (retry/backoff for all outbound API calls) ────────────────
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "3"))
HTTP_BACKOFF = float(os.getenv("HTTP_BACKOFF", "0.5"))   # seconds, exponential

# ── Property detail source priority ───────────────────────────────────────────
# Free HCAD already runs upstream. enrich_property tries these paid sources in
# order; each only fills fields still NULL after the previous one (upsert writes
# non-NULL only), so cost is spent only on genuine gaps.
PROPERTY_FIELD_SOURCES = ["rentcast", "attom"]
SOURCE_FIELDS = {
    "rentcast": [
        "year_built", "square_footage", "estimated_value", "estimated_equity",
        "last_sale_date", "last_sale_price", "owner_name", "owner_occupied",
        "ownership_years",
    ],
    "attom": [
        "year_built", "square_footage", "lot_size", "estimated_value",
        "estimated_equity", "last_sale_date", "last_sale_price", "owner_name",
        "owner_occupied", "garage_spaces", "garage_type",
    ],
}
# Cost guard: cap Attom (paid, ~10x RentCast) lookups per ZIP.
ATTOM_MAX_ROWS_PER_ZIP = int(os.getenv("ATTOM_MAX_ROWS_PER_ZIP", "500"))

# ── Equity estimation ─────────────────────────────────────────────────────────
# Fallback fraction of value treated as equity when no mortgage/sale data exists.
EQUITY_FALLBACK_PCT = float(os.getenv("EQUITY_FALLBACK_PCT", "0.6"))

# ── Search-area expansion (when a ZIP returns too few seed rows) ──────────────
SEED_EXPAND_ENABLED   = os.getenv("SEED_EXPAND_ENABLED", "true").lower() == "true"
SEED_EXPAND_THRESHOLD = int(os.getenv("SEED_EXPAND_THRESHOLD", "50"))   # expand below this
SEED_EXPAND_TARGET    = int(os.getenv("SEED_EXPAND_TARGET", "200"))     # stop once reached
SEED_EXPAND_RADIUS_MI = float(os.getenv("SEED_EXPAND_RADIUS_MI", "5"))
SEED_EXPAND_MAX_ZIPS  = int(os.getenv("SEED_EXPAND_MAX_ZIPS", "10"))

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
# Weights must sum to 1.0. pool/slab keys are optional — omit them (or set 0)
# for verticals where they are irrelevant; _compute_score uses weights.get().
VERTICAL_WEIGHTS = {
    "epoxy_flooring": {
        "age":    0.20,
        "sale":   0.15,
        "equity": 0.15,
        "garage": 0.20,   # garage = primary work surface
        "income": 0.10,
        "permit": 0.05,
        "slab":   0.15,   # cracked slab = confirmed job opportunity (from HCAD)
    },
    "pool_maintenance": {
        "age":    0.10,
        "sale":   0.20,
        "equity": 0.15,
        "garage": 0.00,
        "income": 0.20,
        "permit": 0.05,
        "pool":   0.30,   # has a pool = confirmed service target (from HCAD)
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

# ── Factor metadata (human-readable labels for score explanations) ────────────
# Single source of truth for the labels/descriptions surfaced to users when we
# explain why a lead scored the way it did. Keys match the weight-dict keys
# above; `field` is the property row column each signal reads. Adding a new
# weighted signal means adding its entry here too (enforced by test_scoring.py).
FACTOR_META = {
    "age": {
        "label": "Home age",
        "field": "year_built",
        "description": "Homes 15–30 years old are in the renovation sweet spot.",
    },
    "sale": {
        "label": "Recent sale",
        "field": "last_sale_date",
        "description": "Recently sold homes signal active, motivated owners (last 24 months).",
    },
    "equity": {
        "label": "Home equity",
        "field": "estimated_equity",
        "description": "More equity (toward $100k) means more ability to fund the work.",
    },
    "garage": {
        "label": "Garage space",
        "field": "garage_spaces",
        "description": "Two or more garage spaces — the primary work surface for many jobs.",
    },
    "income": {
        "label": "Area income",
        "field": "zip_median_income",
        "description": "Higher ZIP median income (toward $75k) indicates spending capacity.",
    },
    "permit": {
        "label": "Permit activity",
        "field": "permit_count_24mo",
        "description": "Recent building permits show the owner is already investing in the home.",
    },
    "pool": {
        "label": "Pool present",
        "field": "has_pool",
        "description": "A confirmed pool (from HCAD) is a direct service target.",
    },
    "slab": {
        "label": "Cracked slab",
        "field": "has_cracked_slab",
        "description": "A cracked slab (from HCAD) is a confirmed epoxy-flooring opportunity.",
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

# Binary signal values for presence-based features (pool / cracked slab).
# Both are 0.0–1.0 floats; set to 1.0 so the full vertical weight is applied
# when the feature is confirmed present by HCAD.
POOL_SIGNAL_VALUE    = 1.0
SLAB_SIGNAL_VALUE    = 1.0

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
