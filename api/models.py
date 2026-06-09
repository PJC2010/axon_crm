"""Pydantic schemas for request/response bodies."""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel

EXPENSE_CATEGORIES = ["fuel", "materials", "meals", "tools", "advertising", "subcontractor", "office", "other"]
PAYMENT_METHODS    = ["cash", "card", "check", "zelle", "other"]


# ── Lead ──────────────────────────────────────────────────────────────────────

class Lead(BaseModel):
    id: int
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
    contact_phone: Optional[str] = None
    contact_email: Optional[str] = None
    contact_name: Optional[str] = None
    status: str = "new"
    score_updated_at: Optional[datetime] = None
    estimated_job_value: Optional[int] = None
    stage_moved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    archived_at: Optional[datetime] = None

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


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

    class Config:
        from_attributes = True


# ── Invoice delivery ──────────────────────────────────────────────────────────

class SendInvoiceRequest(BaseModel):
    channels: list[str]  # any of: "email", "sms"


class LeadPage(BaseModel):
    total: int
    page: int
    page_size: int
    results: list[Lead]


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


class ScoreExplanation(BaseModel):
    lead_id: int
    score: Optional[float] = None
    grade: Optional[str] = None
    vertical: Optional[str] = None
    is_default_profile: bool = False
    factors: list[ScoreFactor] = []
    top_drivers: list[str] = []
    vertical_description: list[VerticalFactor] = []
    score_updated_at: Optional[datetime] = None
    weights_drift: bool = False


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
    errors: list[str] = []


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

    class Config:
        from_attributes = True
