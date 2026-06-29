"""Business-type presets.

Axon began as a home-services tool, but the CRM is general. A *business type* on
each account (see db/migrations/040_account_business_type.sql) selects a preset
that bundles, for that industry:

  * ``terminology`` — user-facing word overrides (lead↔deal, property↔record, …),
  * ``categories``  — the picklist that "verticals" become (service lines, deal
    types, practice areas, …),
  * ``property_based`` — whether the property data pipeline / property UI apply,
  * ``default_modules`` — sensible feature defaults at provisioning time.

This mirrors the catalog pattern in api/entitlements.py: presets are code-defined
(versioned, testable), and each account just stores which preset key it uses.

Terminology resolution is layered: ``home_services`` is the base vocabulary and
every other preset's overrides are merged on top, so a key missing from a preset
always resolves to the home-services default (and the frontend ships the same
defaults as a final fallback). Scoring is unaffected — pipeline/scorer.py still
falls back to DEFAULT_WEIGHTS for any category without a profile in config.py.
"""
from dataclasses import dataclass, field

from api.entitlements import MODULE_KEYS


def _modules(**enabled: bool) -> dict[str, bool]:
    """Build a full module map, defaulting unlisted modules to the given base."""
    base = enabled.pop("_base", True)
    return {key: enabled.get(key, base) for key in MODULE_KEYS}


# Base vocabulary. Every other preset's `terminology` is merged over this, so any
# key it omits falls back here. Keep the keys in sync with the frontend defaults
# in frontend/lib/terminology.ts.
BASE_TERMINOLOGY: dict[str, str] = {
    "lead": "Lead",
    "leads": "Leads",
    "record": "Property",
    "records": "Properties",
    "jobValue": "Job value",
    "territory": "Service area",
    "category": "Vertical",
    "categories": "Verticals",
    "owner": "Owner",
    "propertySignals": "Property signals",
    "quote": "Quote",
    "contact": "Contact",
}


@dataclass(frozen=True)
class BusinessType:
    key: str
    label: str
    property_based: bool
    default_modules: dict[str, bool]
    categories: list[dict[str, str]]
    # Only the overrides vs BASE_TERMINOLOGY; resolve_terminology() merges them.
    terminology_overrides: dict[str, str] = field(default_factory=dict)


# The 8 home-services verticals (keys match config.py JOB_VALUE_MODEL /
# VERTICAL_WEIGHTS so scoring keeps working).
_HOME_SERVICES_CATEGORIES = [
    {"value": "epoxy_flooring", "label": "Epoxy flooring"},
    {"value": "pool_maintenance", "label": "Pool maintenance"},
    {"value": "solar", "label": "Solar"},
    {"value": "roofing", "label": "Roofing"},
    {"value": "hvac", "label": "HVAC"},
    {"value": "fencing", "label": "Fencing"},
    {"value": "landscaping", "label": "Landscaping"},
    {"value": "pressure_washing", "label": "Pressure washing"},
]

_GENERAL_SALES_CATEGORIES = [
    {"value": "inbound", "label": "Inbound"},
    {"value": "outbound", "label": "Outbound"},
    {"value": "referral", "label": "Referral"},
    {"value": "partner", "label": "Partner"},
    {"value": "renewal", "label": "Renewal"},
]

_PROFESSIONAL_SERVICES_CATEGORIES = [
    {"value": "consulting", "label": "Consulting"},
    {"value": "retainer", "label": "Retainer"},
    {"value": "project", "label": "Project"},
    {"value": "advisory", "label": "Advisory"},
]


BUSINESS_TYPES: dict[str, BusinessType] = {
    "home_services": BusinessType(
        key="home_services",
        label="Home services",
        property_based=True,
        default_modules=_modules(_base=True),  # everything on — current behavior
        categories=_HOME_SERVICES_CATEGORIES,
        terminology_overrides={},  # base vocabulary
    ),
    "general_sales": BusinessType(
        key="general_sales",
        label="General sales / B2B",
        property_based=False,
        # No property pipeline or map for non-property businesses.
        default_modules=_modules(prospecting=False, map=False),
        categories=_GENERAL_SALES_CATEGORIES,
        terminology_overrides={
            "record": "Account",
            "records": "Accounts",
            "jobValue": "Deal value",
            "territory": "Region",
            "category": "Lead source",
            "categories": "Lead sources",
            "owner": "Primary contact",
            "lead": "Deal",
            "leads": "Deals",
        },
    ),
    "professional_services": BusinessType(
        key="professional_services",
        label="Professional services",
        property_based=False,
        default_modules=_modules(prospecting=False, map=False),
        categories=_PROFESSIONAL_SERVICES_CATEGORIES,
        terminology_overrides={
            "lead": "Client",
            "leads": "Clients",
            "record": "Client",
            "records": "Clients",
            "jobValue": "Engagement value",
            "territory": "Market",
            "category": "Service line",
            "categories": "Service lines",
            "owner": "Primary contact",
        },
    ),
}

DEFAULT_BUSINESS_TYPE = "home_services"


def get_business_type(key: str | None) -> BusinessType:
    """Return the preset for ``key``, falling back to the default."""
    return BUSINESS_TYPES.get(key or DEFAULT_BUSINESS_TYPE, BUSINESS_TYPES[DEFAULT_BUSINESS_TYPE])


def resolve_terminology(key: str | None) -> dict[str, str]:
    """Full terminology map: base vocabulary with the preset's overrides applied."""
    bt = get_business_type(key)
    return {**BASE_TERMINOLOGY, **bt.terminology_overrides}


def business_type_profile(key: str | None) -> dict:
    """The account-facing profile payload returned by the API."""
    bt = get_business_type(key)
    return {
        "business_type": bt.key,
        "property_based": bt.property_based,
        "terminology": resolve_terminology(bt.key),
        "categories": bt.categories,
    }
