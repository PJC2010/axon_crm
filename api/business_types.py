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


# Default dashboard KPI set (the pre-Phase-6 hardcoded tiles). Presets override
# to surface their vertical's numbers; frontend/components/HomeDashboard.tsx
# maps these ids to tiles.
DEFAULT_KPIS: tuple[str, ...] = ("revenue_mtd", "outstanding_ar", "win_rate", "forecast")


# Default lead-list columns (property / home-services). `record` is the primary
# identifier cell; the rest map to renderers in the frontend column registry at
# frontend/components/lead/leadColumns.tsx. Presets override to drop the property
# columns for verticals where they're meaningless (insurance, retail, …).
DEFAULT_LIST_COLUMNS: tuple[str, ...] = (
    "record", "score", "year_built", "equity", "garage", "last_sale", "status",
)
# Non-property list layout: identity, score, the vertical's category + deal value,
# then status. Reuses only fields already on the lead row (no policy/order join).
_NON_PROPERTY_LIST_COLUMNS: tuple[str, ...] = (
    "record", "score", "category", "job_value", "status",
)


@dataclass(frozen=True)
class BusinessType:
    key: str
    label: str
    property_based: bool
    default_modules: dict[str, bool]
    categories: list[dict[str, str]]
    # Only the overrides vs BASE_TERMINOLOGY; resolve_terminology() merges them.
    terminology_overrides: dict[str, str] = field(default_factory=dict)
    # ── Provisioning pack (Phase 6) ────────────────────────────────────────────
    # Pipeline stages seeded at account creation / opt-in switch. None → the
    # classic accounts.DEFAULT_STAGES. Tuples match the pipeline_stages insert:
    # (key, label, color, sort_order, is_terminal, is_default).
    default_stages: tuple | None = None
    # record_field_defs seeds: {"key", "label", "field_type", "options"?}.
    default_fields: tuple = ()
    # workflow_rules seeds (full rule shape incl. trigger_type/action_type).
    # Seeded separately from create_account because rules need a creator user
    # (scheduled rules run as created_by) — see accounts.seed_business_type_workflows.
    # A rule may reference default_templates by name via action_config
    # {"template_names": {"sms": name, "email": name}}; the seeder resolves
    # them to this account's template ids ({"templates": {...}}).
    default_workflows: tuple = ()
    # message_templates seeds: {"name", "channel", "subject"?, "body"}.
    default_templates: tuple = ()
    # Dashboard KPI tile ids for this vertical (see HomeDashboard KPI config).
    kpis: tuple[str, ...] = DEFAULT_KPIS
    # Child-object modules this preset is built around (subset of MODULE_KEYS).
    objects: tuple[str, ...] = ()
    # Ordered lead-list column keys (see DEFAULT_LIST_COLUMNS / the frontend
    # registry). Defaults to the property columns for home-services parity.
    list_columns: tuple[str, ...] = DEFAULT_LIST_COLUMNS


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

_INSURANCE_CATEGORIES = [
    {"value": "auto", "label": "Auto"},
    {"value": "home", "label": "Home"},
    {"value": "life", "label": "Life"},
    {"value": "health", "label": "Health"},
    {"value": "commercial", "label": "Commercial"},
]

_RETAIL_CATEGORIES = [
    {"value": "in_store", "label": "In store"},
    {"value": "online", "label": "Online"},
    {"value": "marketplace", "label": "Marketplace"},
    {"value": "wholesale", "label": "Wholesale"},
]

# Insurance pipeline mirrors the sales→bound→renewal book lifecycle.
_INSURANCE_STAGES = (
    ("prospect", "Prospect", "var(--color-ink-300)", 0, False, True),
    ("quoted",   "Quoted",   "var(--color-gold)",    1, False, False),
    ("bound",    "Bound",    "var(--color-moss)",    2, False, False),
    ("renewal",  "Renewal",  "var(--color-ocean)",   3, False, False),
    ("lost",     "Lost",     "var(--color-danger)",  4, True,  False),
)

# Retail stages are customer-lifecycle segments, not a deal funnel.
_RETAIL_STAGES = (
    ("new",     "New",     "var(--color-ink-300)", 0, False, True),
    ("repeat",  "Repeat",  "var(--color-ocean)",   1, False, False),
    ("vip",     "VIP",     "var(--color-moss)",    2, False, False),
    ("at_risk", "At risk", "var(--color-gold)",    3, False, False),
    ("lapsed",  "Lapsed",  "var(--color-danger)",  4, True,  False),
)

# Client-facing renewal reminders: sent to the policyholder (not the agent) by
# the "Renewal reminder to client" rule below. SMS first with email fallback —
# if the client has no phone on file the email goes out instead.
_INSURANCE_TEMPLATES = (
    {
        "name": "Renewal reminder (SMS)",
        "channel": "sms",
        "body": ("Hi {{first_name}}, it's {{business_name}}. Your {{carrier}} "
                 "{{policy_type}} policy is set to expire on {{expiration_date}}. "
                 "Reply here or give us a call to review your renewal options."),
    },
    {
        "name": "Renewal reminder (Email)",
        "channel": "email",
        "subject": "Your {{policy_type}} policy expires {{expiration_date}}",
        "body": ("Hi {{first_name}},\n\n"
                 "This is a reminder from {{business_name}} that your {{carrier}} "
                 "{{policy_type}} policy is set to expire on {{expiration_date}}.\n\n"
                 "Reply to this email or give us a call and we'll walk through your "
                 "renewal options together.\n\n"
                 "— {{business_name}}"),
    },
    # Speed-to-lead: instant acknowledgment for website form submissions, sent by
    # the public-intake responder (api/routes/public_intake.py) which looks this
    # template up by name.
    {
        "name": "Website lead auto-reply (SMS)",
        "channel": "sms",
        "body": ("Hi {{first_name}}, thanks for reaching out to {{business_name}}! We "
                 "received your request and will be in touch shortly. Reply here if "
                 "there's anything you'd like to add."),
    },
)

# X-date automation: the whole reason an agency runs a CRM. Rules target the
# policies child table via the Phase-4 date_offset trigger; the firings ledger
# fires each policy's renewal exactly once per offset per expiration date.
_INSURANCE_WORKFLOWS = (
    {
        "name": "Renewal — 90 days out",
        "trigger_type": "date_offset",
        "trigger_config": {"source": "policies", "date_field": "expiration_date", "offset_days": -90},
        "action_type": "create_task",
        "action_config": {"title": "Renewal in 90 days — start remarketing quotes", "due_days_offset": 7, "priority": "normal"},
    },
    {
        "name": "Renewal — 30 days out",
        "trigger_type": "date_offset",
        "trigger_config": {"source": "policies", "date_field": "expiration_date", "offset_days": -30},
        "action_type": "create_task",
        "action_config": {"title": "Renewal in 30 days — present renewal terms", "due_days_offset": 3, "priority": "high"},
    },
    {
        "name": "Renewal reminder to client — 30 days out",
        "trigger_type": "date_offset",
        "trigger_config": {"source": "policies", "date_field": "expiration_date", "offset_days": -30},
        "action_type": "send_template",
        "action_config": {
            "template_names": {"sms": "Renewal reminder (SMS)", "email": "Renewal reminder (Email)"},
            "delivery": "sms_first",
        },
    },
    {
        "name": "Renewal — 7 days out",
        "trigger_type": "date_offset",
        "trigger_config": {"source": "policies", "date_field": "expiration_date", "offset_days": -7},
        "action_type": "create_task",
        "action_config": {"title": "Renewal in 7 days — confirm binding", "due_days_offset": 1, "priority": "urgent"},
    },
    {
        "name": "Annual review call",
        "trigger_type": "inactivity",
        "trigger_config": {"days": 180},
        "action_type": "create_task",
        "action_config": {"title": "No contact in 6 months — schedule annual review", "due_days_offset": 7, "priority": "normal"},
    },
)

_RETAIL_WORKFLOWS = (
    {
        "name": "Win-back — 90 days quiet",
        "trigger_type": "inactivity",
        "trigger_config": {"days": 90},
        "action_type": "create_task",
        "action_config": {"title": "No purchase in 90 days — send a win-back offer", "due_days_offset": 3, "priority": "normal"},
    },
)

# Home-services growth loop (prospective-user audit P1): reviews are the #2 lead
# source after referrals, and website leads convert far better inside 5 minutes.
# The review request renders {{review_link}} (accounts.review_link); until the
# owner sets one in Settings the send is skipped, never sent broken. The
# auto-reply template is looked up by name by the public-intake speed-to-lead
# responder (api/routes/public_intake.py).
_HOME_SERVICES_TEMPLATES = (
    {
        "name": "Review request (SMS)",
        "channel": "sms",
        "body": ("Hi {{first_name}}, thanks for choosing {{business_name}}! If you were "
                 "happy with the work, would you leave us a quick review? It's how "
                 "neighbors find us: {{review_link}}"),
    },
    {
        "name": "Review request (Email)",
        "channel": "email",
        "subject": "How did we do, {{first_name}}?",
        "body": ("Hi {{first_name}},\n\n"
                 "Thanks again for choosing {{business_name}}. If you were happy with the "
                 "work, a quick review would mean a lot — it's how neighbors find us:\n\n"
                 "{{review_link}}\n\n"
                 "— {{business_name}}"),
    },
    {
        "name": "Website lead auto-reply (SMS)",
        "channel": "sms",
        "body": ("Hi {{first_name}}, thanks for reaching out to {{business_name}}! We got "
                 "your request and will call you shortly. Reply here if there's anything "
                 "you'd like to add."),
    },
)

_HOME_SERVICES_WORKFLOWS = (
    {
        "name": "Review request — 2 days after job won",
        "trigger_type": "date_offset",
        "trigger_config": {"source": "won_transitions", "date_field": "transitioned_at",
                           "offset_days": 2},
        "action_type": "send_template",
        "action_config": {
            "template_names": {"sms": "Review request (SMS)", "email": "Review request (Email)"},
            "delivery": "sms_first",
        },
    },
)


BUSINESS_TYPES: dict[str, BusinessType] = {
    "home_services": BusinessType(
        key="home_services",
        label="Home services",
        property_based=True,
        # Everything on except the Phase-5 child objects (matches pre-Phase-5 UX;
        # owners can enable them from the plan settings) and marketing — Meta CSV
        # insights never earned their keep with contractors (positioning plan
        # Phase 4); re-enable per-account if a fit appears.
        default_modules=_modules(_base=True, marketing=False, policies=False, orders=False,
                                 appointments=False),
        categories=_HOME_SERVICES_CATEGORIES,
        terminology_overrides={},  # base vocabulary
        default_workflows=_HOME_SERVICES_WORKFLOWS,
        default_templates=_HOME_SERVICES_TEMPLATES,
    ),
    "general_sales": BusinessType(
        key="general_sales",
        label="General sales / B2B",
        property_based=False,
        # No property pipeline or map for non-property businesses.
        default_modules=_modules(prospecting=False, map=False, policies=False, orders=False),
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
        list_columns=_NON_PROPERTY_LIST_COLUMNS,
    ),
    "professional_services": BusinessType(
        key="professional_services",
        label="Professional services",
        property_based=False,
        default_modules=_modules(prospecting=False, map=False, policies=False, orders=False),
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
        list_columns=_NON_PROPERTY_LIST_COLUMNS,
    ),
    "insurance_agency": BusinessType(
        key="insurance_agency",
        label="Insurance agency",
        property_based=False,
        default_modules=_modules(prospecting=False, map=False, orders=False),
        categories=_INSURANCE_CATEGORIES,
        terminology_overrides={
            "lead": "Client",
            "leads": "Clients",
            "record": "Client",
            "records": "Clients",
            "jobValue": "Premium",
            "territory": "Book of business",
            "category": "Line of business",
            "categories": "Lines of business",
            "owner": "Policyholder",
        },
        default_stages=_INSURANCE_STAGES,
        default_fields=(
            {"key": "current_carrier", "label": "Current carrier", "field_type": "text"},
            {"key": "x_date", "label": "X-date", "field_type": "date"},
            {"key": "household_size", "label": "Household size", "field_type": "number"},
        ),
        default_workflows=_INSURANCE_WORKFLOWS,
        default_templates=_INSURANCE_TEMPLATES,
        kpis=("premium_in_force", "active_policies", "renewals_30d", "win_rate"),
        objects=("policies", "appointments"),
        # x_date (renewal) is the number an agency lives by — surface it in the list.
        list_columns=("record", "score", "category", "job_value", "x_date", "status"),
    ),
    "retail": BusinessType(
        key="retail",
        label="Retail",
        property_based=False,
        default_modules=_modules(prospecting=False, map=False, policies=False, appointments=False),
        categories=_RETAIL_CATEGORIES,
        terminology_overrides={
            "lead": "Customer",
            "leads": "Customers",
            "record": "Customer",
            "records": "Customers",
            "jobValue": "Order value",
            "territory": "Market",
            "category": "Channel",
            "categories": "Channels",
            "owner": "Customer",
        },
        default_stages=_RETAIL_STAGES,
        default_fields=(
            {"key": "loyalty_number", "label": "Loyalty number", "field_type": "text"},
            {"key": "birthday", "label": "Birthday", "field_type": "date"},
            {"key": "preferred_channel", "label": "Preferred channel", "field_type": "select",
             "options": ["in_store", "online", "marketplace"]},
        ),
        default_workflows=_RETAIL_WORKFLOWS,
        kpis=("revenue_mtd", "orders_30d", "repeat_rate", "outstanding_ar"),
        objects=("orders",),
        list_columns=_NON_PROPERTY_LIST_COLUMNS,
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
        "kpis": list(bt.kpis),
        "objects": list(bt.objects),
        "list_columns": list(bt.list_columns),
    }


def business_type_catalog() -> list[dict]:
    """Picker payload for onboarding: every preset, in definition order."""
    return [
        {"key": bt.key, "label": bt.label, "property_based": bt.property_based}
        for bt in BUSINESS_TYPES.values()
    ]
