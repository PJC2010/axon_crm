import os
from dotenv import load_dotenv

load_dotenv()

# ── Database ──────────────────────────────────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost/smart_crm")

# ── Harris County Appraisal District DuckDB ───────────────────────────────────
PERMIT_DB_PATH = os.getenv("PERMIT_DB_PATH", "/Users/petecastillo/property_data/harris_county.duckdb")

# ── API keys ─────────────────────────────────────────────────────────────────
RENTCAST_API_KEY    = os.getenv("RENTCAST_API_KEY", "")
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

# ── Household demographics / life-events enrichment ───────────────────────────
# Provider-pluggable (e.g. "versium"); default "" = step is a no-op.
# Supported providers: see pipeline/demographics.py PROVIDERS.
DEMO_PROVIDER         = os.getenv("DEMO_PROVIDER", "")
DEMO_API_KEY          = os.getenv("DEMO_API_KEY", "")
DEMO_BASE_URL         = os.getenv("DEMO_BASE_URL", "")
DEMO_MAX_ROWS_PER_ZIP = int(os.getenv("DEMO_MAX_ROWS_PER_ZIP", "200"))
# Only enrich leads at or above this grade ("" = no grade filter).
DEMO_MIN_GRADE        = os.getenv("DEMO_MIN_GRADE", "")

# ── Storm / hail event enrichment (NOAA/IEM, free) ───────────────────────────
# IEM Local Storm Report API — no key required.
IEM_LSR_URL           = os.getenv("IEM_LSR_URL", "https://mesonet.agron.iastate.edu/geojson/lsr.php")
# NWS Weather Forecast Office code covering Harris County (Houston/Galveston).
STORM_WFO             = os.getenv("STORM_WFO", "HGX")
# How far back to fetch storm reports (months). Matches the permit/sale window.
STORM_LOOKBACK_MONTHS = int(os.getenv("STORM_LOOKBACK_MONTHS", "24"))
# A property is considered "hit" by a storm event if it falls within this radius.
STORM_MATCH_RADIUS_MI = float(os.getenv("STORM_MATCH_RADIUS_MI", "1.0"))
# Hail size (inches) at which the storm signal is fully saturated (score = 1.0).
STORM_HAIL_TARGET_IN  = float(os.getenv("STORM_HAIL_TARGET_IN", "1.5"))

# ── HTTP robustness (retry/backoff for all outbound API calls) ────────────────
HTTP_RETRIES = int(os.getenv("HTTP_RETRIES", "3"))
HTTP_BACKOFF = float(os.getenv("HTTP_BACKOFF", "0.5"))   # seconds, exponential

# ── Property detail source priority ───────────────────────────────────────────
# Free HCAD already runs upstream. enrich_property tries these paid sources in
# order; each only fills fields still NULL after the previous one (upsert writes
# non-NULL only), so cost is spent only on genuine gaps.
# Env-overridable (comma-separated); unknown names are dropped.
SOURCE_FIELDS = {
    "rentcast": [
        "year_built", "square_footage", "estimated_value", "estimated_equity",
        "last_sale_date", "last_sale_price", "owner_name", "owner_occupied",
        "ownership_years", "garage_spaces", "garage_type",
    ],
}
PROPERTY_FIELD_SOURCES = [
    s for s in (t.strip().lower() for t in
                os.getenv("PROPERTY_FIELD_SOURCES", "rentcast").split(","))
    if s in SOURCE_FIELDS
]

# ── Equity estimation ─────────────────────────────────────────────────────────
# Fallback fraction of value treated as equity when no mortgage/sale data exists.
EQUITY_FALLBACK_PCT = float(os.getenv("EQUITY_FALLBACK_PCT", "0.6"))

# ── Job-value estimation ──────────────────────────────────────────────────────
# Coarse, deterministic per-vertical ballpark for estimated_job_value when a lead
# has no manual estimate. Pure math lives in pipeline/job_value.py (testable like
# equity). Each model contributes a flat `base` plus optional per-unit terms that
# only apply when the underlying property field is known:
#   per_sqft     × square_footage   per_garage   × garage_spaces
#   per_lot_sqft × lot_size         requires_pool/pool_value (has_pool gated)
# Numbers are rough Houston-market defaults — tune freely; they exist so the field
# is useful instead of blank, not to produce a precise quote.
JOB_VALUE_MODEL = {
    "roofing":          {"base": 3000, "per_sqft": 4.5},
    "hvac":             {"base": 6000, "per_sqft": 1.5},
    "solar":            {"base": 12000, "per_sqft": 4.0},
    "epoxy_flooring":   {"base": 800,  "per_garage": 1800},
    "fencing":          {"base": 1500, "per_lot_sqft": 0.4},
    "landscaping":      {"base": 1000, "per_lot_sqft": 0.5},
    "pressure_washing": {"base": 350,  "per_sqft": 0.15},
    "pool_maintenance": {"base": 0, "requires_pool": True, "pool_value": 1800},
}
# Generic fallback when no vertical model applies or its inputs are missing:
# a small fraction of the home's estimated value as a rough job ticket.
JOB_VALUE_FALLBACK_PCT = float(os.getenv("JOB_VALUE_FALLBACK_PCT", "0.04"))

# ── Seed source ───────────────────────────────────────────────────────────────
# Where the seed step (step 1) gets its address list:
#   "rentcast" — RentCast /properties scan (paid; default).
#   "hcad"     — local Harris County DuckDB/Postgres mirror (free). Seeds every
#                parcel in the ZIP and pre-fills the assessor fields RentCast
#                would otherwise be paid to fetch. CLI: --seed-source hcad.
# An explicit --seed-csv / --region still takes precedence over this default.
SEED_SOURCE = os.getenv("SEED_SOURCE", "rentcast").strip().lower()

# ── Seed property-type filter ─────────────────────────────────────────────────
# Only these RentCast `propertyType` values are seeded; everything else (e.g.
# Apartment, Multi-Family, Land) is skipped at seed so paid enrichment never
# touches it. Comma-separated env override. Set to "*" (or empty) to seed all.
SEED_PROPERTY_TYPES = [
    t.strip() for t in os.getenv(
        "SEED_PROPERTY_TYPES",
        "Single Family,Condo,Townhouse,Manufactured",
    ).split(",") if t.strip()
]

# ── Search-area expansion (when a ZIP returns too few seed rows) ──────────────
SEED_EXPAND_ENABLED   = os.getenv("SEED_EXPAND_ENABLED", "true").lower() == "true"
SEED_EXPAND_THRESHOLD = int(os.getenv("SEED_EXPAND_THRESHOLD", "50"))   # expand below this
SEED_EXPAND_TARGET    = int(os.getenv("SEED_EXPAND_TARGET", "200"))     # stop once reached
SEED_EXPAND_RADIUS_MI = float(os.getenv("SEED_EXPAND_RADIUS_MI", "5"))
SEED_EXPAND_MAX_ZIPS  = int(os.getenv("SEED_EXPAND_MAX_ZIPS", "10"))

# ── CSV import guardrails ────────────────────────────────────────────────────
IMPORT_MAX_BYTES = int(os.getenv("IMPORT_MAX_BYTES", str(5 * 1024 * 1024)))  # 5 MB

# ── Connectors / Marketing insights ──────────────────────────────────────────
# File uploads (Meta exports) reuse IMPORT_MAX_BYTES.
# Insight generator: "rules" (deterministic, default) | future "claude" (LLM).
INSIGHTS_GENERATOR = os.getenv("INSIGHTS_GENERATOR", "rules")
# Rule benchmarks — tunable without code changes.
INSIGHTS_ENGAGEMENT_BENCHMARK = float(os.getenv("INSIGHTS_ENGAGEMENT_BENCHMARK", "0.03"))  # 3% of reach
INSIGHTS_MIN_POSTS_PER_WEEK   = int(os.getenv("INSIGHTS_MIN_POSTS_PER_WEEK", "3"))
INSIGHTS_TARGET_ROAS          = float(os.getenv("INSIGHTS_TARGET_ROAS", "2.0"))
INSIGHTS_MAX_CPA              = float(os.getenv("INSIGHTS_MAX_CPA", "50"))
INSIGHTS_MIN_CTR              = float(os.getenv("INSIGHTS_MIN_CTR", "0.01"))   # 1% of impressions
INSIGHTS_STALE_DAYS           = int(os.getenv("INSIGHTS_STALE_DAYS", "30"))

# FUTURE OAuth (unused now — placeholders so the seam is documented).
META_APP_ID             = os.getenv("META_APP_ID", "")
META_APP_SECRET         = os.getenv("META_APP_SECRET", "")
META_OAUTH_REDIRECT_URI = os.getenv("META_OAUTH_REDIRECT_URI", "")

# ── Social login (Sign in with Google / Apple) ───────────────────────────────
# Used by api/oauth_verify.py to validate the OIDC ID token's audience. The app
# boots with these empty — the /api/auth/oauth/* endpoints return 503 until set.
#   GOOGLE_OAUTH_CLIENT_ID — the Web OAuth client id from Google Cloud Console.
#   APPLE_CLIENT_ID        — the Apple "Services ID" used for Sign in with Apple.
GOOGLE_OAUTH_CLIENT_ID  = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")
APPLE_CLIENT_ID         = os.getenv("APPLE_CLIENT_ID", "")
# LLM / vision (Anthropic). Used by api/receipt_extract.py for receipt OCR; the
# marketing-insights "claude" generator is still a future seam. The app boots
# with no key — only the receipt-scan endpoint requires one.
ANTHROPIC_API_KEY       = os.getenv("ANTHROPIC_API_KEY", "")

# ── Receipt OCR ──────────────────────────────────────────────────────────────
# Model used to extract expense fields from a receipt photo. Haiku handles clean
# receipts well and is the cheapest tier; bump to claude-sonnet-4-6 for messier
# images without a code change.
RECEIPT_SCAN_MODEL = os.getenv("RECEIPT_SCAN_MODEL", "claude-haiku-4-5")
# Receipt photos run larger than CSVs, so this is separate from IMPORT_MAX_BYTES.
RECEIPT_MAX_BYTES  = int(os.getenv("RECEIPT_MAX_BYTES", str(10 * 1024 * 1024)))  # 10 MB

# ── Machine-learning predictive lead scoring ─────────────────────────────────
# Scorer mode controls whether the learned model is computed/shown:
#   "rules"   — deterministic scoring only (default; unchanged behaviour).
#   "shadow"  — compute the learned probability and STORE it alongside the rules
#               score, but keep the rules score as the user-facing grade. Use this
#               to validate model lift in production before flipping the UI.
#   "learned" — surface the learned conversion probability to users.
SCORER_MODE = os.getenv("SCORER_MODE", "rules")
# Minimum labeled examples (with both outcomes present) before a scope is trained.
# Below this the scope falls back to the pooled/global model, then to rules.
ML_MIN_TRAINING_LABELS = int(os.getenv("ML_MIN_TRAINING_LABELS", "40"))
# An open lead older than this with no real engagement is treated as a soft loss
# (negative label) so the model learns from leads that quietly went nowhere.
ML_STALE_OPEN_DAYS = int(os.getenv("ML_STALE_OPEN_DAYS", "120"))
# Logistic-regression training hyperparameters (pure-Python trainer in
# pipeline/ml/model.py — no heavyweight ML dependency required).
ML_L2 = float(os.getenv("ML_L2", "1.0"))
ML_LR = float(os.getenv("ML_LR", "0.1"))
ML_EPOCHS = int(os.getenv("ML_EPOCHS", "600"))
# Hour (UTC) of the nightly retrain job that refreshes labels and re-fits models.
ML_RETRAIN_HOUR = int(os.getenv("ML_RETRAIN_HOUR", "3"))

# ── Scheduled workflow rules (date_offset / inactivity triggers) ──────────────
# Hour (UTC) of the daily tick that evaluates date-based and inactivity workflow
# rules (see api/workflow_engine.py run_daily_rules). Runs at :15 past the hour.
WORKFLOW_TICK_HOUR = int(os.getenv("WORKFLOW_TICK_HOUR", "7"))

# ── Invoice delivery (notifications) ─────────────────────────────────────────
RESEND_API_KEY      = os.getenv("RESEND_API_KEY", "")
RESEND_FROM_EMAIL   = os.getenv("RESEND_FROM_EMAIL", "")
TWILIO_ACCOUNT_SID  = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN   = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_FROM_NUMBER  = os.getenv("TWILIO_FROM_NUMBER", "")

# Frontend origin used to build customer-facing links (public quote pages).
APP_BASE_URL        = os.getenv("APP_BASE_URL", "http://localhost:3000")

# ── Website lead intake (insure-auto public site) ────────────────────────────
# Shared-secret header (X-Axon-Api-Key) that authenticates server-to-server
# calls from the insure-auto Next.js API routes — never exposed to a browser.
# Both must be set for POST /api/public/website-lead to accept requests; it
# returns 503 while either is empty. PUBLIC_INTAKE_ACCOUNT_ID pins every
# website lead to this single agency's account (this deployment serves one).
PUBLIC_INTAKE_API_KEY    = os.getenv("PUBLIC_INTAKE_API_KEY", "")
PUBLIC_INTAKE_ACCOUNT_ID = os.getenv("PUBLIC_INTAKE_ACCOUNT_ID", "")

# ── Online payments (Stripe Connect Express) ─────────────────────────────────
# Owners onboard Express connected accounts; customers pay via Checkout Sessions
# created on the connected account (direct charges) and Axon takes a platform
# fee. STRIPE_WEBHOOK_SECRET is the signing secret of the *Connect* webhook
# endpoint ("events on connected accounts") — direct charges emit their events
# on the connected account, not the platform account.
STRIPE_SECRET_KEY       = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET   = os.getenv("STRIPE_WEBHOOK_SECRET", "")
# Platform fee taken on each charge, as a percentage of the amount (e.g. 2.0).
STRIPE_PLATFORM_FEE_PCT = float(os.getenv("STRIPE_PLATFORM_FEE_PCT", "2.0"))

# ── Self-serve signup ─────────────────────────────────────────────────────────
# POST /auth/signup and OAuth first-login provisioning create a new account +
# owner user (api/routes/signup.py). Set to "false" to return to the invite-only
# model (signup 403s and unknown OAuth identities are rejected again).
SELF_SERVE_SIGNUP = os.getenv("SELF_SERVE_SIGNUP", "true").lower() != "false"
# New self-serve accounts start on the full `pro` module set for this many days
# (status 'trialing' in account_billing). A daily scheduler job downgrades
# expired trials with no subscription to `starter` — core is never locked out.
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "14"))

# ── Subscription billing (Stripe Billing for Axon plans) ─────────────────────
# How accounts pay for Axon itself — separate from Stripe Connect above, where
# an account's customers pay that account's invoices. Uses the same platform
# STRIPE_SECRET_KEY; each plan maps to a recurring Price created in the Stripe
# dashboard. Leave the price ids empty to disable self-serve billing (the
# billing endpoints return 503 and plans stay admin-managed via
# scripts/set_account_plan.py). STRIPE_BILLING_WEBHOOK_SECRET is the signing
# secret of a *platform* ("events on your account") webhook endpoint pointed at
# /api/public/stripe/billing-webhook — distinct from the Connect endpoint.
STRIPE_BILLING_WEBHOOK_SECRET = os.getenv("STRIPE_BILLING_WEBHOOK_SECRET", "")
STRIPE_PRICE_STARTER = os.getenv("STRIPE_PRICE_STARTER", "")
STRIPE_PRICE_GROWTH  = os.getenv("STRIPE_PRICE_GROWTH", "")
STRIPE_PRICE_PRO     = os.getenv("STRIPE_PRICE_PRO", "")

# ── Public ZIP-sample widget (landing-page growth loop) ───────────────────────
# "Enter your ZIP, see your best leads free": the landing page serves a masked
# teaser of scored properties from this designated sample account. Empty =
# widget disabled (the endpoint reports configured=false). The account should
# be a dedicated demo org — its scored data is shown (masked) to strangers.
PUBLIC_SAMPLE_ACCOUNT_ID = os.getenv("PUBLIC_SAMPLE_ACCOUNT_ID", "")
# Queue a free HCAD-seeded pipeline run when a visitor asks for a ZIP the
# sample account hasn't scored yet (Harris County only; costs CPU, not API
# dollars). Capped globally per hour to keep strangers from soaking the worker.
PUBLIC_SAMPLE_AUTORUN = os.getenv("PUBLIC_SAMPLE_AUTORUN", "true").lower() != "false"
PUBLIC_SAMPLE_RUNS_PER_HOUR = int(os.getenv("PUBLIC_SAMPLE_RUNS_PER_HOUR", "4"))
# How many teaser rows the endpoint returns.
PUBLIC_SAMPLE_TOP_N = int(os.getenv("PUBLIC_SAMPLE_TOP_N", "10"))

# ── Score weights (must sum to 1.0) ──────────────────────────────────────────
# Default weights from context - score.docx.
# Override per vertical by passing a weights dict to the scorer.
DEFAULT_WEIGHTS = {
    "age":          0.25,   # home age in renovation sweet spot (15–30 years)
    "sale":         0.22,   # recency of last sale
    "equity":       0.18,   # estimated equity >= $100k
    "garage":       0.15,   # garage spaces >= 2
    "income":       0.06,   # zip median income (coarse — half its weight moved to neighborhood)
    "neighborhood": 0.06,   # value-per-sqft vs the immediate block (granular locality)
    "permit":       0.08,   # permit activity in last 24 months
}

# Per-vertical weight overrides. Keys match vertical names used in the DB.
# Weights must sum to 1.0. pool/slab keys are optional — omit them (or set 0)
# for verticals where they are irrelevant; _compute_score uses weights.get().
VERTICAL_WEIGHTS = {
    # Weights must sum to 1.0 per profile. Optional signals (pool, slab, storm,
    # home_improvement, refi, credit, children, gardening, absentee, tenure,
    # life_stage) use weights.get() in _compute_score, so they are safe to include
    # only in the verticals where they carry predictive value.
    "epoxy_flooring": {
        "age":              0.20,
        "sale":             0.13,
        "equity":           0.15,
        "garage":           0.20,   # garage = primary work surface
        "income":           0.02,
        "neighborhood":     0.02,
        "permit":           0.03,
        "slab":             0.15,   # cracked slab = confirmed job opportunity (from HCAD)
        "home_improvement": 0.05,   # intent signal — owner already invests in the home
        "life_stage":       0.03,   # new movers finish/upgrade garages soon after moving
        "tenure":           0.02,   # long-tenured owners finally tackle the garage floor
    },
    "pool_maintenance": {
        "age":              0.10,
        "sale":             0.15,
        "equity":           0.10,
        "garage":           0.00,
        "income":           0.08,
        "neighborhood":     0.10,
        "permit":           0.04,
        "pool":             0.20,   # has a pool = confirmed service target (from HCAD)
        "children":         0.10,   # families with children = primary pool-maintenance customer
        "credit":           0.05,   # financing eligibility for pool upgrades
        "home_improvement": 0.05,   # intent signal — owner already invests in the home
        "life_stage":       0.03,   # new movers with a pool start recurring service
    },
    "solar": {
        "age":              0.10,
        "sale":             0.10,
        "equity":           0.20,
        "garage":           0.08,
        "income":           0.03,
        "neighborhood":     0.15,   # premium homes within a block are prime solar targets
        "permit":           0.03,
        "refi":             0.10,   # recent cash-out refi = capital + investment mindset
        "credit":           0.10,   # solar financing requires credit approval
        "home_improvement": 0.05,   # intent signal
        "tenure":           0.03,   # long-term owners invest in long-payback upgrades
        "life_stage":       0.03,   # new movers upgrade systems early
    },
    "roofing": {
        "age":              0.20,   # roof age tracks home age — 15–30y roofs are due
        "sale":             0.13,
        "equity":           0.13,
        "garage":           0.00,
        "income":           0.02,
        "neighborhood":     0.02,
        "permit":           0.12,   # active permits often follow storm/repair work
        "storm":            0.20,   # recent hail/wind event = most direct demand driver
        "home_improvement": 0.05,   # intent signal
        "refi":             0.05,   # capital signal
        "absentee":         0.04,   # landlords re-roof rentals to protect the asset
        "tenure":           0.04,   # long-tenured owners are on an aging original roof
    },
    "hvac": {
        "age":              0.24,   # systems hit end-of-life at 15–25 years
        "sale":             0.13,
        "equity":           0.13,
        "garage":           0.00,
        "income":           0.02,
        "neighborhood":     0.03,
        "permit":           0.10,
        "storm":            0.10,   # freeze events drive HVAC failures
        "home_improvement": 0.07,   # intent signal
        "refi":             0.05,   # capital signal
        "credit":           0.04,   # financing eligibility
        "absentee":         0.04,   # landlords replace units to keep rentals occupied
        "tenure":           0.05,   # long-tenured owners run an aging original system
    },
    "fencing": {
        "age":              0.10,
        "sale":             0.16,   # new owners replace fences early
        "equity":           0.13,
        "garage":           0.00,
        "income":           0.02,
        "neighborhood":     0.03,
        "permit":           0.09,
        "pool":             0.15,   # pools require code-compliant fencing
        "storm":            0.10,   # hail/wind damage is a primary fence-replacement trigger
        "children":         0.10,   # safety fencing for children
        "home_improvement": 0.05,   # intent signal
        "life_stage":       0.04,   # new movers fence for privacy/pets/kids
        "tenure":           0.03,   # long-tenured owners replace an aged-out fence
    },
    "landscaping": {
        "age":              0.05,
        "sale":             0.25,   # new owners re-landscape early
        "equity":           0.20,
        "garage":           0.00,
        "income":           0.13,   # recurring service — spending capacity matters
        "neighborhood":     0.15,   # high-value blocks invest most in curb appeal
        "permit":           0.04,
        "home_improvement": 0.05,   # intent signal
        "gardening":        0.05,   # direct behavioral signal for outdoor services
        "life_stage":       0.05,   # new movers re-landscape to make the home their own
        "tenure":           0.03,   # long-tenured owners refresh tired landscaping
    },
    "pressure_washing": {
        "age":              0.22,   # older exteriors show the most buildup
        "sale":             0.13,
        "equity":           0.10,
        "garage":           0.00,
        "income":           0.08,
        "neighborhood":     0.08,
        "permit":           0.05,
        "pool":             0.15,   # pool decks are a core upsell surface
        "storm":            0.10,   # post-storm debris/staining drives cleanup demand
        "home_improvement": 0.05,   # intent signal
        "absentee":         0.04,   # landlords pressure-wash rentals between tenants
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
    "neighborhood": {
        "label": "Neighborhood value",
        "field": "neighborhood_value_ratio",
        "description": "Home value-per-sqft is strong relative to its immediate neighborhood — a sharper locality signal than ZIP-wide income.",
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
    "storm": {
        "label": "Storm activity",
        "field": "last_storm_date",
        "description": "A recent storm or hail event (NOAA/IEM) signals surge demand for roofing, HVAC, fencing, and pressure-washing.",
    },
    "home_improvement": {
        "label": "Home improvement",
        "field": "home_improvement_flag",
        "description": "Owner actively buys home-improvement products — a direct behavioral intent signal for all service verticals.",
    },
    "refi": {
        "label": "Recent refinance",
        "field": "refi_date",
        "description": "A recent mortgage refinance (especially cash-out) indicates available capital and willingness to invest in the property.",
    },
    "credit": {
        "label": "Credit quality",
        "field": "credit_rating",
        "description": "Higher owner credit rating (A/B) means financing eligibility for large jobs — solar, HVAC, roofing.",
    },
    "children": {
        "label": "Children in home",
        "field": "has_children",
        "description": "Presence of children drives safety-focused spending: pool fencing, HVAC air quality, structural work.",
    },
    "gardening": {
        "label": "Gardening interest",
        "field": "gardening_flag",
        "description": "Owner is a gardening enthusiast — a direct behavioral indicator for landscaping and outdoor services.",
    },
    "absentee": {
        "label": "Absentee owner",
        "field": "owner_occupied",
        "description": "Owner does not live at the property (investor/landlord) — reachable by mail and a strong prospect for rental turnover, exterior, and systems work.",
    },
    "tenure": {
        "label": "Ownership tenure",
        "field": "ownership_years",
        "description": "Long-tenured owners (toward 12+ years) run aging systems that are overdue for big-ticket replacement.",
    },
    "life_stage": {
        "label": "Life stage",
        "field": "life_stage",
        "description": "Owner life stage signals intent: recent movers renovate soon after moving; retirees invest in aging-in-place.",
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

# Neighborhood-relative value (see pipeline/neighborhood.py). A home whose
# value-per-sqft is NEIGHBORHOOD_RATIO_TARGET× its neighborhood median (or higher)
# scores full marks on the neighborhood signal; at/below the median scores 0.
NEIGHBORHOOD_RATIO_TARGET = 1.3   # 30% above the block median = top signal
NEIGHBORHOOD_MIN_MEMBERS  = 5     # geohash cells smaller than this fall back to ZIP median

# Storm recency window — events older than this score 0 (matches SALE_RECENCY_MAX_MO).
STORM_RECENCY_MAX_MO  = STORM_LOOKBACK_MONTHS

# ── Demographic signal thresholds ────────────────────────────────────────────
# Refinance recency window (months). A refi within this window scores towards 1.0.
REFI_RECENCY_MAX_MO   = int(os.getenv("REFI_RECENCY_MAX_MO", "36"))
# Credit grade-to-score mapping (ordinal A=best, D=worst).
CREDIT_GRADE_SCORES   = {"A": 1.0, "B": 0.75, "C": 0.40, "D": 0.10}

# ── Seller-intent / homeowner-motivation thresholds ──────────────────────────
# Ownership tenure (years) at which the "due for big-ticket work" signal saturates.
TENURE_TARGET_YEARS   = int(os.getenv("TENURE_TARGET_YEARS", "12"))
# Ordinal life-stage motivation scores. Values match pipeline.demographics
# (_normalize_life_stage): 'new_mover' | 'established' | 'retiree' | 'other'.
# Recent movers renovate soonest; retirees invest in aging-in-place with equity.
LIFE_STAGE_SCORES     = {"new_mover": 1.0, "retiree": 0.6, "established": 0.4, "other": 0.1}

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

# ── Google Geocoding ─────────────────────────────────────────────────────────
GOOGLE_GEOCODE_URL = "https://maps.googleapis.com/maps/api/geocode/json"

# ── Census ACS ───────────────────────────────────────────────────────────────
CENSUS_ACS_URL = "https://api.census.gov/data/2022/acs/acs5"
CENSUS_INCOME_VAR = "B19013_001E"   # median household income

# ── Geospatial scoring layer (Juncto geo layer, Phase 1) ──────────────────────
# Proximity + density + territory scoring on top of the property score. Distance
# uses haversine × a road-circuity factor (no routing engine at MVP — see
# docs/geo_scoring.md for the OSRM upgrade path). "Customers" are properties in
# a won/converted status; their locations drive proximity/density.
CUSTOMER_STATUSES = ("won", "converted")

GEO_ROAD_CIRCUITY        = float(os.getenv("GEO_ROAD_CIRCUITY", "1.3"))   # straight-line → road
GEO_PROXIMITY_DECAY_KM   = float(os.getenv("GEO_PROXIMITY_DECAY_KM", "2.0"))  # 100*exp(-d/decay)
GEO_DENSITY_RADIUS_M     = int(os.getenv("GEO_DENSITY_RADIUS_M", "1600"))
GEO_DENSITY_CAP          = int(os.getenv("GEO_DENSITY_CAP", "8"))
GEO_NEIGHBOR_RADIUS_M    = int(os.getenv("GEO_NEIGHBOR_RADIUS_M", "150"))  # Phase 3
GEO_NEIGHBOR_FRESH_DAYS  = int(os.getenv("GEO_NEIGHBOR_FRESH_DAYS", "60"))
GEO_NEIGHBOR_DECAY_DAYS  = int(os.getenv("GEO_NEIGHBOR_DECAY_DAYS", "90"))
GEO_TERRITORY_GATE_OUT   = float(os.getenv("GEO_TERRITORY_GATE_OUT", "0.1"))  # penalty outside area
GEO_RESCORE_RADIUS_KM    = float(os.getenv("GEO_RESCORE_RADIUS_KM", "8.0"))   # blast radius on new customer
GEO_SERVICE_AREA_BUFFER_KM = float(os.getenv("GEO_SERVICE_AREA_BUFFER_KM", "2.0"))
GEO_BLEND_RECURRING      = float(os.getenv("GEO_BLEND_RECURRING", "0.35"))
GEO_BLEND_PROJECT        = float(os.getenv("GEO_BLEND_PROJECT", "0.25"))

# Code-side fallback when a vertical has no vertical_geo_config row (the DB table
# seeded by migration 049 is the source of truth; this keeps scoring resolvable
# for any vertical, mirroring how score_zip falls back to DEFAULT_WEIGHTS).
GEO_DEFAULT_CONFIG = {
    "route_weight":    0.60,
    "neighbor_weight": 0.40,
    "geo_blend":       GEO_BLEND_RECURRING,
}

# Geocoding provider for tenant-entered addresses missing coordinates. RentCast
# leads arrive pre-geocoded and never hit this. "census" (free batch, no key) is
# the default; "google" reuses GOOGLE_GEOCODE_KEY. Provider-pluggable — see
# pipeline/geocode_provider.py.
GEOCODE_PROVIDER   = os.getenv("GEOCODE_PROVIDER", "census")
CENSUS_GEOCODER_URL = os.getenv(
    "CENSUS_GEOCODER_URL",
    "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
)

# ── Geo Phase 2: clustering + heatmap ─────────────────────────────────────────
# Customer clustering (pure-Python DBSCAN over haversine distance — the
# ST_ClusterDBSCAN stand-in while the layer stays PostGIS-free; see
# docs/geo_scoring.md). eps in meters, minpoints includes the point itself, both
# matching the plan's Section 6 example.
GEO_CLUSTER_EPS_M      = int(os.getenv("GEO_CLUSTER_EPS_M", "800"))
GEO_CLUSTER_MIN_POINTS = int(os.getenv("GEO_CLUSTER_MIN_POINTS", "3"))
# H3 resolution for heatmap aggregation. 8 ≈ 0.74 km² hexes. Requires the
# optional `h3` package; the layer degrades gracefully (h3_r8 stays NULL, the
# heatmap reports available=false) when it isn't installed.
GEO_H3_RESOLUTION      = int(os.getenv("GEO_H3_RESOLUTION", "8"))

# ── Geo Phase 2: cluster-seeded prospecting (Section 5) ───────────────────────
# Pull pre-geocoded, pre-enriched prospects from a property-data vendor around a
# seed, dedupe, ingest, and score. Provider-pluggable (pipeline/property_provider.py).
PROPERTY_PROVIDER       = os.getenv("PROPERTY_PROVIDER", "rentcast")
PROSPECT_DEFAULT_RADIUS_M = int(os.getenv("PROSPECT_DEFAULT_RADIUS_M", "1600"))  # ~1 mile
PROSPECT_MAX_RECORDS    = int(os.getenv("PROSPECT_MAX_RECORDS", "500"))          # per pull
# Cost control: skip a seed whose H3 cell was pulled within this many days, and
# cap pulls per account per cycle. Dedupe radius matches a record to an existing
# property by geometry when addresses don't normalize equal.
PROSPECT_SKIP_DAYS      = int(os.getenv("PROSPECT_SKIP_DAYS", "14"))
PROSPECT_MAX_PULLS_PER_CYCLE = int(os.getenv("PROSPECT_MAX_PULLS_PER_CYCLE", "20"))
PROSPECT_DEDUPE_M       = float(os.getenv("PROSPECT_DEDUPE_M", "25"))

# ── Geo Phase 4: event layers (hail swaths, new construction, HOA sweeps) ──────
# A lead inside an active event polygon gets an additive geo bonus, named in the
# component breakdown. Bonus is per event_type (a geo_events row may override via
# its own `bonus` column); unknown types fall back to the default.
GEO_EVENT_DEFAULT_BONUS = float(os.getenv("GEO_EVENT_DEFAULT_BONUS", "30"))
GEO_EVENT_BONUS = {
    "hail_swath":       40.0,   # roofing — the whole game
    "storm":            35.0,
    "new_construction": 25.0,   # lawn, pest, pools
    "hoa_sweep":        20.0,   # lawn enforcement
    "heat_wave":        20.0,   # HVAC
}
