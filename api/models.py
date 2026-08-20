"""Pydantic schemas for request/response bodies."""
import re
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel

EXPENSE_CATEGORIES = ["fuel", "materials", "meals", "tools", "advertising", "subcontractor", "office", "other"]
PAYMENT_METHODS    = ["cash", "card", "check", "zelle", "stripe", "other"]


# ── Lead ──────────────────────────────────────────────────────────────────────

class Lead(BaseModel):
    id: int
    account_number: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    year_built: Optional[int] = None
    square_footage: Optional[int] = None
    garage_spaces: Optional[int] = None
    estimated_value: Optional[int] = None
    estimated_equity: Optional[int] = None
    last_sale_date: Optional[date] = None
    last_sale_price: Optional[int] = None
    owner_name: Optional[str] = None
    owner_occupied: Optional[bool] = None
    zip_median_income: Optional[int] = None
    permit_count_24mo: Optional[int] = None
    has_pool: Optional[bool] = None
    has_cracked_slab: Optional[bool] = None
    lead_score: Optional[float] = None
    score_grade: Optional[str] = None
    vertical: Optional[str] = None
    neighborhood_value_ratio: Optional[float] = None
    neighborhood_value_pctile: Optional[float] = None
    neighborhood_value_basis: Optional[str] = None
    hcad_neighborhood_code: Optional[str] = None
    hcad_neighborhood_name: Optional[str] = None
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone_alt: Optional[str] = None
    contact_email_alt: Optional[str] = None
    mailing_address: Optional[str] = None
    preferred_contact_method: Optional[str] = None
    best_time_to_call: Optional[str] = None
    # Lead-level DNC flag (migration 0069): set by the dialer's do_not_call
    # disposition, enforced by the dialer queue and the outbound dial webhook.
    do_not_call: bool = False
    status: str = "new"
    assigned_to: Optional[int] = None
    lead_source: Optional[str] = None
    score_updated_at: Optional[datetime] = None
    estimated_job_value: Optional[int] = None
    stage_moved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None
    # Learned conversion probability (0–1) + the model version that produced it.
    # Populated only when SCORER_MODE is 'shadow' or 'learned' and a model exists.
    ml_conversion_prob: Optional[float] = None
    ml_model_version: Optional[int] = None
    # Geospatial layer (juncto geo layer, Phase 1). geo_score is the standalone
    # location score; final_score blends it with the property score and is what the
    # leads list sorts on when sort=final_score. Populated once a lead is geo-scored.
    geo_score: Optional[float] = None
    final_score: Optional[float] = None
    geo_components: Optional[dict] = None
    nearest_customer_m: Optional[float] = None
    customers_within_1600m: Optional[int] = None
    # Account-defined custom field values (see api/routes/record_fields.py). Keyed
    # by record_field_defs.key; empty for accounts that define no custom fields.
    custom_fields: dict = {}
    # True when this row is hidden behind the monthly scored-lead allowance
    # (api/scoring_quota.py): address partially masked, identity/contact nulled.
    quota_masked: Optional[bool] = None

    class Config:
        from_attributes = True


# ── Map ───────────────────────────────────────────────────────────────────────

class MapCell(BaseModel):
    """A geohash-6 'block' aggregate for the service-area choropleth. Carries both
    color bases (intent signals + score) so the frontend toggle needs no refetch.
    The cell's rectangle geometry is derived frontend-side by decoding `cell`."""
    cell: str                              # geohash-6
    name: Optional[str] = None             # mode of hcad_neighborhood_name
    leads: int
    avg_score: Optional[float] = None
    grade_a: int = 0
    grade_b: int = 0
    grade_c: int = 0
    grade_d: int = 0
    signal_count: int = 0                  # leads with a recent signal_event
    lat: Optional[float] = None            # centroid, for initial map fit
    lng: Optional[float] = None


class MapPoint(BaseModel):
    """A single property pin — intentionally lighter than Lead for bulk payloads."""
    id: int
    address: Optional[str] = None
    latitude: float
    longitude: float
    lead_score: Optional[float] = None
    score_grade: Optional[str] = None
    status: str = "new"
    signals: list[str] = []                # recent signal_type values


class MapZip(BaseModel):
    """A ZIP the account has mapped leads in, plus the extent of those leads.

    Powers the map's ZIP jump control: the frontend fits straight to the returned
    bounding box, so navigating to a ZIP needs no external geocoder and can only
    offer ZIPs the account actually holds data for.
    """
    zip: str
    leads: int
    min_lat: float
    min_lng: float
    max_lat: float
    max_lng: float


# ── Expenses ──────────────────────────────────────────────────────────────────

class ExpenseCreate(BaseModel):
    amount: float
    category: str
    vendor: str
    description: Optional[str] = None
    expense_date: date
    payment_method: str = "card"
    is_tax_deductible: bool = True
    property_id: Optional[int] = None


class ExpenseUpdate(BaseModel):
    amount: Optional[float] = None
    category: Optional[str] = None
    vendor: Optional[str] = None
    description: Optional[str] = None
    expense_date: Optional[date] = None
    payment_method: Optional[str] = None
    is_tax_deductible: Optional[bool] = None
    property_id: Optional[int] = None


class Expense(BaseModel):
    id: int
    amount: float
    category: str
    vendor: str
    description: Optional[str] = None
    expense_date: date
    payment_method: str
    is_tax_deductible: bool
    property_id: Optional[int] = None
    receipt_url: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ExpenseSummary(BaseModel):
    total: float
    by_category: dict
    tax_deductible_total: float
    count: int


class ReceiptScanResult(BaseModel):
    """Fields extracted from a receipt photo to pre-fill the expense form. All
    optional — a partial read still pre-fills whatever was recognized."""
    amount: Optional[float] = None
    vendor: Optional[str] = None
    expense_date: Optional[date] = None
    category: Optional[str] = None
    is_tax_deductible: Optional[bool] = None
    description: Optional[str] = None


# ── Invoices ──────────────────────────────────────────────────────────────────

INVOICE_STATUSES = ["draft", "sent", "paid", "partial", "overdue", "void"]


class LineItemCreate(BaseModel):
    description: str
    quantity: float = 1.0
    unit_price: float
    sort_order: int = 0


class LineItem(BaseModel):
    id: int
    invoice_id: int
    description: str
    quantity: float
    unit_price: float
    amount: float
    sort_order: int

    class Config:
        from_attributes = True


class PaymentCreate(BaseModel):
    amount: float
    payment_date: date
    payment_method: str = "card"
    notes: Optional[str] = None


class InvoicePayment(BaseModel):
    id: int
    invoice_id: int
    amount: float
    payment_date: date
    payment_method: str
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime
    # Set on payments recorded by the Stripe webhook; such rows can't be
    # deleted manually (refund via Stripe instead).
    stripe_payment_intent_id: Optional[str] = None
    stripe_charge_id: Optional[str] = None

    class Config:
        from_attributes = True


INVOICE_RECURRENCES = ["weekly", "monthly", "quarterly", "annual"]


class InvoiceCreate(BaseModel):
    property_id: Optional[int] = None
    client_name: str
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    client_address: Optional[str] = None
    tax_rate: float = 0.0
    issue_date: date
    due_date: Optional[date] = None
    notes: Optional[str] = None
    line_items: list[LineItemCreate]
    # Recurring revenue (memberships/retainers): cadence + optional end date.
    recurrence: Optional[str] = None
    recurrence_end: Optional[date] = None


class InvoiceUpdate(BaseModel):
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    client_address: Optional[str] = None
    status: Optional[str] = None
    tax_rate: Optional[float] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    notes: Optional[str] = None
    line_items: Optional[list[LineItemCreate]] = None
    # Pass recurrence="" (or null) to stop a series; a cadence to (re)start it.
    recurrence: Optional[str] = None
    recurrence_end: Optional[date] = None


class Invoice(BaseModel):
    id: int
    invoice_number: str
    property_id: Optional[int] = None
    client_name: str
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    client_address: Optional[str] = None
    status: str
    subtotal: float
    tax_rate: float
    tax_amount: float
    total: float
    amount_paid: float
    balance_due: float
    issue_date: date
    due_date: Optional[date] = None
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime
    line_items: list[LineItem] = []
    payments: list[InvoicePayment] = []
    recurrence: Optional[str] = None
    recurrence_next: Optional[date] = None
    recurrence_end: Optional[date] = None
    recurring_source_id: Optional[int] = None
    # Token addressing the public pay page (/pay/{pay_token}); separate from
    # public_token so a circulating PDF link can't initiate payment.
    pay_token: Optional[str] = None

    class Config:
        from_attributes = True


# ── Invoice delivery ──────────────────────────────────────────────────────────

class SendInvoiceRequest(BaseModel):
    channels: list[str]  # any of: "email", "sms"


# ── Online payments (Stripe Connect) ──────────────────────────────────────────

class StripeStatus(BaseModel):
    available: bool                    # platform key configured on the server
    connected: bool                    # this account has a connected account
    charges_enabled: bool = False
    payouts_enabled: bool = False
    details_submitted: bool = False


class PublicPayInfo(BaseModel):
    """Customer-safe pay-page payload — no ids or account internals."""
    business_name: str
    invoice_number: str
    status: str
    total: float
    amount_paid: float
    balance_due: float
    issue_date: date
    due_date: Optional[date] = None
    payable: bool
    pdf_url: str


# ── Quotes ────────────────────────────────────────────────────────────────────

QUOTE_STATUSES = ["draft", "sent", "accepted", "declined", "expired"]


class QuoteLineItem(BaseModel):
    id: int
    quote_id: int
    description: str
    quantity: float
    unit_price: float
    amount: float
    sort_order: int

    class Config:
        from_attributes = True


class QuoteCreate(BaseModel):
    property_id: Optional[int] = None
    client_name: str
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    client_address: Optional[str] = None
    tax_rate: float = 0.0
    issue_date: date
    valid_until: Optional[date] = None
    notes: Optional[str] = None
    line_items: list[LineItemCreate]


class QuoteUpdate(BaseModel):
    client_name: Optional[str] = None
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    client_address: Optional[str] = None
    status: Optional[str] = None
    tax_rate: Optional[float] = None
    issue_date: Optional[date] = None
    valid_until: Optional[date] = None
    notes: Optional[str] = None
    line_items: Optional[list[LineItemCreate]] = None


class Quote(BaseModel):
    id: int
    quote_number: str
    property_id: Optional[int] = None
    client_name: str
    client_phone: Optional[str] = None
    client_email: Optional[str] = None
    client_address: Optional[str] = None
    status: str
    subtotal: float
    tax_rate: float
    tax_amount: float
    total: float
    issue_date: date
    valid_until: Optional[date] = None
    notes: Optional[str] = None
    sent_at: Optional[datetime] = None
    viewed_at: Optional[datetime] = None
    accepted_at: Optional[datetime] = None
    declined_at: Optional[datetime] = None
    decline_reason: Optional[str] = None
    converted_invoice_id: Optional[int] = None
    public_token: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime
    line_items: list[QuoteLineItem] = []

    class Config:
        from_attributes = True


class ConvertQuoteRequest(BaseModel):
    due_date: Optional[date] = None  # invoice due date; defaults to +30 days


class PublicDeclineRequest(BaseModel):
    reason: Optional[str] = None  # customer's optional note


class ScoringQuota(BaseModel):
    """Monthly scored-lead reveal allowance state (api/scoring_quota.py)."""
    limit: int
    used: int
    remaining: int


class LeadPage(BaseModel):
    total: int
    page: int
    page_size: int
    results: list[Lead]
    # Present only for metered plans; None means unlimited (or ledger unavailable).
    scoring_quota: Optional[ScoringQuota] = None


class CustomerSearchResult(BaseModel):
    """Lightweight hit for the universal customer search dropdown — just enough
    to identify and link to a customer without paying for a full Lead payload."""
    id: int
    account_number: Optional[str] = None
    contact_name: Optional[str] = None
    owner_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    zip: Optional[str] = None
    contact_phone: Optional[str] = None
    status: str = "new"
    score_grade: Optional[str] = None
    # Present so a map can fly to a hit without a second round trip. Nullable:
    # `properties` is also the contact book, and an inbound call or web-form lead
    # has no address to geocode.
    latitude: Optional[float] = None
    longitude: Optional[float] = None


# ── Score explanation ─────────────────────────────────────────────────────────

class ScoreFactor(BaseModel):
    """One weighed factor's contribution to a lead's score."""
    key: str
    label: str
    description: str
    weight: float
    signal: float        # normalized 0–1 strength of this factor for the lead
    contribution: float  # weighted points added to the score (weight × signal × 100)


class VerticalFactor(BaseModel):
    """A factor in a vertical's weighting profile (no per-lead values)."""
    key: str
    label: str
    description: str
    weight: float


class MLFactor(BaseModel):
    """One feature's signed log-odds contribution to the learned probability."""
    key: str
    label: str
    contribution: float


class ScoreExplanation(BaseModel):
    lead_id: int
    score: Optional[float] = None
    grade: Optional[str] = None
    vertical: Optional[str] = None
    is_default_profile: bool = False
    factors: list[ScoreFactor] = []
    top_drivers: list[str] = []
    summary: Optional[str] = None  # one-line plain-language reason for the score
    vertical_description: list[VerticalFactor] = []
    score_updated_at: Optional[datetime] = None
    weights_drift: bool = False
    # Learned-model overlay (present when a model is active and SCORER_MODE != rules).
    scorer_mode: str = "rules"
    ml_conversion_prob: Optional[float] = None
    ml_grade: Optional[str] = None
    ml_model_version: Optional[int] = None
    ml_factors: list[MLFactor] = []
    ml_top_drivers: list[str] = []


ALLOWED_STATUSES = {"new", "contacted", "qualified", "not_interested", "converted", "quote_sent", "won", "lost"}


class StatusUpdate(BaseModel):
    status: str

    def validate_status(self):
        if self.status not in ALLOWED_STATUSES:
            raise ValueError(f"status must be one of {ALLOWED_STATUSES}")
        return self


class LeadContactUpdate(BaseModel):
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone_alt: Optional[str] = None
    contact_email_alt: Optional[str] = None
    mailing_address: Optional[str] = None
    preferred_contact_method: Optional[str] = None
    best_time_to_call: Optional[str] = None
    # Undo path for a mis-clicked do_not_call disposition (owner judgment call).
    do_not_call: Optional[bool] = None
    assigned_to: Optional[int] = None
    lead_source: Optional[str] = None


# ── Contact / lead import ──────────────────────────────────────────────────────

class ImportPreviewResponse(BaseModel):
    """What the UI shows after a file is uploaded but before committing."""
    headers: list[str]
    target_fields: list[str]
    mapping: dict[str, str]          # csv header -> properties field
    total_rows: int
    usable_rows: int                 # rows with an address or a contact identifier
    skip_rows: int                   # total_rows - usable_rows
    sample: list[dict] = []          # first few normalized rows


class ImportOptions(BaseModel):
    default_vertical: Optional[str] = None
    default_status: str = "new"


class ImportResult(BaseModel):
    imported: int = 0                # new rows inserted
    updated: int = 0                 # existing rows matched and updated
    skipped: int = 0                 # rows with no usable data
    coerced_statuses: int = 0        # rows whose status wasn't a stage of this account
    error_count: int = 0             # total failed rows (errors[] is capped)
    errors: list[str] = []


# ── Public website lead intake (insure-auto) ───────────────────────────────────

WEBSITE_FORM_TYPES = {"quote", "contact"}
WEBSITE_QUOTE_TYPES = {"personal-auto", "home-insurance", "renters-insurance", "commercial-auto"}
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class WebsiteLeadCreate(BaseModel):
    """Body of POST /api/public/website-lead — a quote request or contact-form
    submission from the insure-auto marketing site. Sent server-to-server by
    insure-auto's own Next.js API routes, never directly by a visitor's browser."""
    form_type: str
    full_name: str
    email: str
    phone: Optional[str] = None
    quote_type: Optional[str] = None
    fields: dict = {}                 # dynamic per-quote-type fields (vehicleYear, propertyAddress, ...)
    subject: Optional[str] = None     # contact form only
    message: Optional[str] = None     # contact form only
    is_preview: bool = False          # true for Vercel Preview-deploy submissions

    def validate_lead(self):
        if self.form_type not in WEBSITE_FORM_TYPES:
            raise ValueError(f"form_type must be one of {WEBSITE_FORM_TYPES}")
        if self.quote_type and self.quote_type not in WEBSITE_QUOTE_TYPES:
            raise ValueError(f"quote_type must be one of {WEBSITE_QUOTE_TYPES}")
        if not self.full_name.strip():
            raise ValueError("full_name is required")
        if not _EMAIL_RE.match(self.email or ""):
            raise ValueError("email is not a valid address")
        return self


# ── Notes ─────────────────────────────────────────────────────────────────────

class NoteCreate(BaseModel):
    note: str


class Note(BaseModel):
    id: int
    property_id: int
    note: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Lead outcome events (scoring feedback loop) ───────────────────────────────

# Append-only outcome log — mirrors the CHECK constraint in migration 0058.
# Lead state is derived from these events; the nightly labeling job (Phase 3)
# turns them into training labels for the scoring model.
LEAD_EVENT_TYPES = [
    "surfaced",           # lead shown/delivered to contractor
    "viewed",
    "contact_attempted",
    "contacted",          # reached a human
    "quote_sent",
    "won",
    "lost",
    "disqualified",       # bad data, wrong property type, etc.
    "suppressed",         # renter, DNC, already-serviced
]


class LeadEventCreate(BaseModel):
    event_type: str
    channel: Optional[str] = None       # 'call','sms','email','door','mail'
    metadata: Optional[dict] = None     # e.g. {"quote_amount": 8500, "loss_reason": "price"}


class LeadEvent(BaseModel):
    id: int
    property_id: int
    account_id: int
    event_type: str
    channel: Optional[str] = None
    actor_user_id: Optional[int] = None
    occurred_at: datetime
    metadata: Optional[dict] = None

    class Config:
        from_attributes = True


# ── History ───────────────────────────────────────────────────────────────────

class HistoryCreate(BaseModel):
    action: str
    outcome: Optional[str] = None


class HistoryEntry(BaseModel):
    id: int
    property_id: int
    action: str
    outcome: Optional[str] = None
    created_at: datetime
    # Two-way messaging (048): NULL on legacy rows and manual log entries.
    channel: Optional[str] = None      # 'sms' | 'email'
    direction: Optional[str] = None    # 'inbound' | 'outbound'
    body: Optional[str] = None

    class Config:
        from_attributes = True


# ── Associated child objects (policies / orders / appointments) ─────────────────

POLICY_STATUSES = ["quoted", "active", "lapsed", "cancelled"]
ORDER_STATUSES = ["pending", "completed", "refunded", "cancelled"]
APPOINTMENT_STATUSES = ["scheduled", "completed", "cancelled", "no_show"]


class PolicyCreate(BaseModel):
    property_id: Optional[int] = None
    policy_number: Optional[str] = None
    carrier: Optional[str] = None
    policy_type: Optional[str] = None       # line of business (auto/home/life/…)
    premium: Optional[float] = None          # annualized
    billing_frequency: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None   # the renewal/X-date
    status: str = "quoted"
    commission_rate: Optional[float] = None
    notes: Optional[str] = None


class PolicyUpdate(BaseModel):
    property_id: Optional[int] = None
    policy_number: Optional[str] = None
    carrier: Optional[str] = None
    policy_type: Optional[str] = None
    premium: Optional[float] = None
    billing_frequency: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    status: Optional[str] = None
    commission_rate: Optional[float] = None
    notes: Optional[str] = None


class Policy(BaseModel):
    id: int
    property_id: Optional[int] = None
    policy_number: Optional[str] = None
    carrier: Optional[str] = None
    policy_type: Optional[str] = None
    premium: Optional[float] = None
    billing_frequency: Optional[str] = None
    effective_date: Optional[date] = None
    expiration_date: Optional[date] = None
    status: str
    commission_rate: Optional[float] = None
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class OrderCreate(BaseModel):
    property_id: Optional[int] = None
    order_number: Optional[str] = None
    order_date: Optional[date] = None        # defaults to today server-side
    total: float = 0
    item_count: Optional[int] = None
    items: list[dict] = []
    channel: Optional[str] = None
    status: str = "completed"
    notes: Optional[str] = None


class OrderUpdate(BaseModel):
    property_id: Optional[int] = None
    order_number: Optional[str] = None
    order_date: Optional[date] = None
    total: Optional[float] = None
    item_count: Optional[int] = None
    items: Optional[list[dict]] = None
    channel: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class Order(BaseModel):
    id: int
    property_id: Optional[int] = None
    order_number: Optional[str] = None
    order_date: Optional[date] = None
    total: float = 0
    item_count: Optional[int] = None
    items: list[dict] = []
    channel: Optional[str] = None
    status: str
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AppointmentCreate(BaseModel):
    property_id: Optional[int] = None
    assigned_to: Optional[int] = None
    title: str
    location: Optional[str] = None
    starts_at: datetime
    ends_at: datetime
    status: str = "scheduled"
    notes: Optional[str] = None


class AppointmentUpdate(BaseModel):
    property_id: Optional[int] = None
    assigned_to: Optional[int] = None
    title: Optional[str] = None
    location: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class Appointment(BaseModel):
    id: int
    property_id: Optional[int] = None
    assigned_to: Optional[int] = None
    title: str
    location: Optional[str] = None
    starts_at: Optional[datetime] = None
    ends_at: Optional[datetime] = None
    status: str
    notes: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── Message templates & contact-level messaging ─────────────────────────────────

MESSAGE_CHANNELS = ["email", "sms"]


class MessageTemplateCreate(BaseModel):
    name: str
    channel: str = "email"
    subject: Optional[str] = None
    body: str


class MessageTemplateUpdate(BaseModel):
    name: Optional[str] = None
    channel: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None


class MessageTemplate(BaseModel):
    id: int
    name: str
    channel: str
    subject: Optional[str] = None
    body: str
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    # Either reference a saved template, or supply an ad-hoc channel/subject/body.
    template_id: Optional[int] = None
    channel: Optional[str] = None
    subject: Optional[str] = None
    body: Optional[str] = None
    # When set, that policy's merge fields ({{carrier}}, {{expiration_date}}, …)
    # render into the message — the manual renewal-reminder path.
    policy_id: Optional[int] = None


# ── Saved segments ──────────────────────────────────────────────────────────────

class SegmentCreate(BaseModel):
    name: str
    filters: dict = {}


class SegmentUpdate(BaseModel):
    name: Optional[str] = None
    filters: Optional[dict] = None


class Segment(BaseModel):
    id: int
    name: str
    filters: dict = {}
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True
