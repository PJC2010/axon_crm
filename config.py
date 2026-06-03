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

# ── Payments (Stripe Connect) ────────────────────────────────────────────────
# Axon is the Connect platform; each owner is an Express connected account.
# Payments are direct charges on the connected account with an application fee.
STRIPE_SECRET_KEY       = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET   = os.getenv("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PLATFORM_FEE_PCT = float(os.getenv("STRIPE_PLATFORM_FEE_PCT", "0.02"))  # 2% platform fee

# ── Notifications (invoice delivery) ─────────────────────────────────────────
RESEND_API_KEY      = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL   = os.getenv("RESEND_FROM_EMAIL", "")
TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER  = os.getenv("TWILIO_FROM_NUMBER", "")

# Public base URL used to build customer-facing pay links (/pay/<token>).
PUBLIC_APP_URL      = os.getenv("PUBLIC_APP_URL", "http://localhost:3000")

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
