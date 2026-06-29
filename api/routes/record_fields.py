"""
Account-defined custom fields (the generic record-model layer).

GET    /api/record-fields              — list this account's field definitions
POST   /api/record-fields              — create a field definition (owner)
PATCH  /api/record-fields/{id}         — rename / reorder / edit options (owner)
DELETE /api/record-fields/{id}         — remove a field definition (owner)
PATCH  /api/leads/{id}/custom-fields   — set custom field values on a record

This lets any business model its own lead data without the property schema. Field
definitions are per-account; values live in properties.custom_fields (JSONB), so
the existing record store and pipeline are untouched (see migration 041).
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PGConn
from psycopg2.extras import Json
from pydantic import BaseModel

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner

router = APIRouter()

FIELD_TYPES = ("text", "number", "date", "boolean", "select")


class RecordFieldCreate(BaseModel):
    label: str
    field_type: str = "text"
    key: str | None = None           # derived from label when omitted
    options: list[str] = []
    sort_order: int = 0


class RecordFieldUpdate(BaseModel):
    label: str | None = None
    field_type: str | None = None
    options: list[str] | None = None
    sort_order: int | None = None


class CustomFieldsUpdate(BaseModel):
    values: dict


def _slugify(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.strip().lower()).strip("_")
    return slug or "field"


def _validate_type(field_type: str) -> None:
    if field_type not in FIELD_TYPES:
        raise HTTPException(status_code=400, detail=f"field_type must be one of {', '.join(FIELD_TYPES)}")


@router.get("/record-fields")
def list_fields(user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, key, label, field_type, options, sort_order "
            "FROM record_field_defs WHERE account_id = %s ORDER BY sort_order, id",
            (user["account_id"],),
        )
        return dict_fetchall(cur)


@router.post("/record-fields", status_code=201)
def create_field(body: RecordFieldCreate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    _validate_type(body.field_type)
    key = _slugify(body.key or body.label)
    try:
        with db.cursor() as cur:
            cur.execute(
                "INSERT INTO record_field_defs (account_id, key, label, field_type, options, sort_order) "
                "VALUES (%s, %s, %s, %s, %s, %s) "
                "RETURNING id, key, label, field_type, options, sort_order",
                (current_user["account_id"], key, body.label, body.field_type,
                 Json(body.options), body.sort_order),
            )
            row = dict_fetchone(cur)
            db.commit()
    except Exception:
        db.rollback()
        raise HTTPException(status_code=409, detail="A field with that key already exists")
    return row


@router.patch("/record-fields/{field_id}")
def update_field(field_id: int, body: RecordFieldUpdate, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    sets, params = [], []
    if body.label is not None:
        sets.append("label = %s"); params.append(body.label)
    if body.field_type is not None:
        _validate_type(body.field_type)
        sets.append("field_type = %s"); params.append(body.field_type)
    if body.options is not None:
        sets.append("options = %s"); params.append(Json(body.options))
    if body.sort_order is not None:
        sets.append("sort_order = %s"); params.append(body.sort_order)
    if not sets:
        raise HTTPException(status_code=400, detail="Nothing to update")
    params.extend([field_id, current_user["account_id"]])
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE record_field_defs SET {', '.join(sets)} WHERE id = %s AND account_id = %s "
            "RETURNING id, key, label, field_type, options, sort_order",
            params,
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Field not found")
    return row


@router.delete("/record-fields/{field_id}", status_code=204)
def delete_field(field_id: int, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM record_field_defs WHERE id = %s AND account_id = %s RETURNING id",
            (field_id, current_user["account_id"]),
        )
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Field not found")


@router.patch("/leads/{lead_id}/custom-fields")
def update_custom_fields(lead_id: int, body: CustomFieldsUpdate, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    """Merge the given values into the record's custom_fields. A key set to null
    is removed; other keys are added/updated, leaving the rest of the bag intact."""
    to_remove = [k for k, v in body.values.items() if v is None]
    to_set = {k: v for k, v in body.values.items() if v is not None}
    with db.cursor() as cur:
        cur.execute(
            "UPDATE properties "
            "SET custom_fields = (COALESCE(custom_fields, '{}'::jsonb) || %s::jsonb) - %s::text[] "
            "WHERE id = %s AND account_id = %s RETURNING custom_fields",
            (Json(to_set), to_remove, lead_id, user["account_id"]),
        )
        row = dict_fetchone(cur)
        db.commit()
    if not row:
        raise HTTPException(status_code=404, detail="Lead not found")
    return {"custom_fields": row["custom_fields"]}
