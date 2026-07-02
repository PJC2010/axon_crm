"""
Retail orders import (Phase 8 — integrations): bring a Square / Shopify order
export into Axon so customers and their purchase history land in the CRM and
feed RFM scoring.

POST /api/imports/orders/preview  — parse a file, auto-detect columns, sample
POST /api/imports/orders          — commit with a confirmed mapping
GET  /api/imports/orders/template — download a sample CSV

Each usable row is attributed to a customer record (upserted on the account's
email index) and inserted as an order deduped on (account_id, order_number).
After a commit the account is rescored (retail RFM) so the new orders move
grades immediately. Gated on the `orders` module.
"""
import csv
import io
import json
import logging

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, get_current_user
from api.entitlements import require_module
from api.order_import_logic import (
    ORDER_FIELDS, CUSTOMER_FIELDS, detect_order_mapping, normalize_order_row, order_row_is_usable,
)
from api.routes.imports import _read_limited, _read_csv, SAMPLE_LIMIT
from api.models import ImportPreviewResponse, ImportResult
from api.ratelimit import import_limiter

log = logging.getLogger(__name__)
router = APIRouter()

_PREVIEW_TARGETS = ORDER_FIELDS + CUSTOMER_FIELDS


def _flatten(normalized: dict) -> dict:
    """Merge the {order, customer} split into one flat dict for the preview sample."""
    return {**normalized["customer"], **normalized["order"]}


@router.post("/imports/orders/preview", response_model=ImportPreviewResponse)
async def preview_order_import(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    import_limiter.check(f"acct:{user['account_id']}")
    headers, raw_rows = _read_csv(await _read_limited(file))
    if not headers:
        raise HTTPException(status_code=400, detail="No columns found in file")

    mapping = detect_order_mapping(headers)
    normalized = [normalize_order_row(r, mapping) for r in raw_rows]
    usable = [n for n in normalized if order_row_is_usable(n)]

    return ImportPreviewResponse(
        headers=headers,
        target_fields=_PREVIEW_TARGETS,
        mapping=mapping,
        total_rows=len(raw_rows),
        usable_rows=len(usable),
        skip_rows=len(raw_rows) - len(usable),
        sample=[_flatten(n) for n in usable[:SAMPLE_LIMIT]],
    )


@router.post("/imports/orders", response_model=ImportResult)
async def run_order_import(
    file: UploadFile = File(...),
    mapping: str = Form(...),
    default_channel: str | None = Form(None),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        col_map: dict[str, str] = json.loads(mapping)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="mapping must be valid JSON")

    import_limiter.check(f"acct:{user['account_id']}")
    account_id = user["account_id"]
    _, raw_rows = _read_csv(await _read_limited(file))
    result = ImportResult()

    with db.cursor() as cur:
        for i, raw in enumerate(raw_rows, start=1):
            normalized = normalize_order_row(raw, col_map)
            if not order_row_is_usable(normalized):
                result.skipped += 1
                continue
            cur.execute("SAVEPOINT order_row")
            try:
                inserted = _import_one(cur, account_id, normalized, default_channel, user["id"])
                cur.execute("RELEASE SAVEPOINT order_row")
                if inserted:
                    result.imported += 1
                else:
                    result.updated += 1
            except Exception as exc:
                cur.execute("ROLLBACK TO SAVEPOINT order_row")
                result.errors.append(f"row {i}: {exc}")
    db.commit()

    # Refresh RFM scores so imported history is reflected in grades immediately.
    if result.imported or result.updated:
        try:
            from pipeline.account_rescore import rescore_account
            rescore_account(db, account_id)
            db.commit()
        except Exception:
            log.exception("Post-import rescore failed for account %s", account_id)

    log.info("Order import for account %s: %d new, %d updated, %d skipped, %d errors",
             account_id, result.imported, result.updated, result.skipped, len(result.errors))
    return result


def _import_one(cur, account_id: int, normalized: dict, default_channel: str | None, user_id: int) -> bool:
    """Upsert the customer record and insert/update the order. Returns True when
    a new order was created (vs. an existing order_number updated)."""
    customer, order = normalized["customer"], normalized["order"]

    # Find or create the customer record by email (address-less contact index
    # from migration 018). Merge in name/phone without clobbering existing data.
    cols = ["account_id", "contact_email"]
    vals = [account_id, customer["contact_email"]]
    for c in ("contact_name", "contact_phone"):
        if customer.get(c):
            cols.append(c); vals.append(customer[c])
    set_clause = ", ".join(f"{c} = COALESCE(properties.{c}, EXCLUDED.{c})"
                           for c in cols if c not in ("account_id", "contact_email"))
    if not set_clause:
        set_clause = "contact_email = EXCLUDED.contact_email"  # no-op keeps RETURNING working
    cur.execute(
        f"INSERT INTO properties ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))}) "
        f"ON CONFLICT (account_id, lower(contact_email)) WHERE address IS NULL AND contact_email IS NOT NULL "
        f"DO UPDATE SET {set_clause} RETURNING id",
        vals,
    )
    property_id = cur.fetchone()[0]

    channel = order.get("channel") or default_channel
    status = order.get("status", "completed")
    order_number = order.get("order_number")

    if order_number:
        cur.execute(
            "INSERT INTO orders (account_id, property_id, order_number, order_date, total, "
            "item_count, channel, status, created_by) "
            "VALUES (%s,%s,%s,COALESCE(%s, CURRENT_DATE),%s,%s,%s,%s,%s) "
            "ON CONFLICT (account_id, order_number) WHERE order_number IS NOT NULL "
            "DO UPDATE SET order_date = EXCLUDED.order_date, total = EXCLUDED.total, "
            "item_count = EXCLUDED.item_count, channel = COALESCE(EXCLUDED.channel, orders.channel), "
            "status = EXCLUDED.status, property_id = EXCLUDED.property_id "
            "RETURNING (xmax = 0) AS inserted",
            (account_id, property_id, order_number, order.get("order_date"), order["total"],
             order.get("item_count"), channel, status, user_id),
        )
        return bool(cur.fetchone()[0])

    # No external id to dedup on — always insert.
    cur.execute(
        "INSERT INTO orders (account_id, property_id, order_date, total, item_count, channel, status, created_by) "
        "VALUES (%s,%s,COALESCE(%s, CURRENT_DATE),%s,%s,%s,%s,%s)",
        (account_id, property_id, order.get("order_date"), order["total"],
         order.get("item_count"), channel, status, user_id),
    )
    return True


_TEMPLATE_COLS = ["order number", "order date", "customer email", "customer name",
                  "total", "items", "channel", "status"]


@router.get("/imports/orders/template")
def download_order_template(_: dict = Depends(get_current_user)):
    """A blank CSV with headers the orders importer recognizes out of the box."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_TEMPLATE_COLS)
    writer.writerow(["1001", "2026-07-02", "jane@example.com", "Jane Doe",
                     "84.50", "3", "online", "paid"])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="axon_orders_template.csv"'},
    )
