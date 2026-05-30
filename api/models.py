"""Pydantic schemas for request/response bodies."""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel


# ── Lead ──────────────────────────────────────────────────────────────────────

class Lead(BaseModel):
    id: int
    address: str
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
    lead_score: Optional[float] = None
    score_grade: Optional[str] = None
    vertical: Optional[str] = None
    status: str = "new"
    score_updated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class LeadPage(BaseModel):
    total: int
    page: int
    page_size: int
    results: list[Lead]


class StatusUpdate(BaseModel):
    status: str   # new | contacted | qualified | not_interested | converted

    def validate_status(self):
        allowed = {"new", "contacted", "qualified", "not_interested", "converted"}
        if self.status not in allowed:
            raise ValueError(f"status must be one of {allowed}")
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
