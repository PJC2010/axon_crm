"""
GET    /api/orders         — list (filters: status, property_id, channel, page) + roll-ups
POST   /api/orders         — create
GET    /api/orders/{id}    — single
PATCH  /api/orders/{id}    — update
DELETE /api/orders/{id}    — delete (owner only)

Orders are retail purchase history (Phase 5 associated object): summary rows
(total, item_count, items JSONB), not composed documents like quotes — they
feed lifetime-spend roll-ups and, later, RFM scoring. Lifecycle events fire
order_event rules and log to the lead's activity feed.
"""
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn
from psycopg2.extras import Json

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner
from api.models import Order, OrderCreate, OrderUpdate, ORDER_STATUSES

log = logging.getLogger(__name__)

router = APIRouter()

_FIELDS = ("property_id", "order_number", "order_date", "total", "item_count",
           "items", "channel", "status", "notes")


def _row_to_order(row: dict) -> dict:
    if isinstance(row.get("items"), str):
        row["items"] = json.loads(row["items"])
    return row


def _assert_property(db: PGConn, property_id: int | None, account_id: int) -> None:
    """A client-supplied property_id must belong to the caller's account —
    contact_history has no account_id of its own, so an unchecked id here
    would write into another tenant's lead timeline."""
    if property_id is None:
        return
    with db.cursor() as cur:
        cur.execute("SELECT 1 FROM properties WHERE id = %s AND account_id = %s",
                    (property_id, account_id))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="Lead not found")


def _get_order_or_404(db: PGConn, order_id: int, account_id: int) -> dict:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM orders WHERE id = %s AND account_id = %s", (order_id, account_id))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Order not found")
    return _row_to_order(row)


def _fire_order_event(db: PGConn, order: dict, event: str, user_id: int) -> None:
    """Run order_event workflow rules; never let automation break the request."""
    from api.workflow_engine import execute_object_event_rules
    try:
        execute_object_event_rules(
            db, account_id=order["account_id"], lead_id=order["property_id"],
            object_type="order", event=event, user_id=user_id,
        )
    except Exception:
        log.exception("order_event rules failed for order %d (%s)", order["id"], event)


def _log_order_history(db: PGConn, order: dict, action: str, user_id: int) -> None:
    if not order.get("property_id"):
        return
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, created_by) "
            "VALUES (%s, %s, %s, %s)",
            (order["property_id"], action, order.get("status"), user_id),
        )


def _describe(order: dict) -> str:
    label = order.get("order_number") or f"#{order['id']}"
    return f"{label} (${float(order.get('total') or 0):,.2f})"


@router.get("/orders", response_model=dict)
def list_orders(
    status: Optional[str] = Query(None),
    property_id: Optional[int] = Query(None),
    channel: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    conditions, params = ["account_id = %s"], [user["account_id"]]
    if status:
        conditions.append("status = %s"); params.append(status)
    if property_id is not None:
        conditions.append("property_id = %s"); params.append(property_id)
    if channel:
        conditions.append("channel = %s"); params.append(channel)
    where = "WHERE " + " AND ".join(conditions)
    offset = (page - 1) * page_size

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM orders {where}", params)
        total = cur.fetchone()[0]
        # Lifetime roll-ups ignore the status/channel filters (refunds and
        # cancellations are excluded from spend) but respect the record scope.
        rollup_where = "WHERE account_id = %s" + (" AND property_id = %s" if property_id is not None else "")
        rollup_params = [user["account_id"]] + ([property_id] if property_id is not None else [])
        cur.execute(
            f"SELECT COALESCE(SUM(total) FILTER (WHERE status = 'completed'), 0), "
            f"COUNT(*) FILTER (WHERE status = 'completed'), "
            f"MAX(order_date) FILTER (WHERE status = 'completed') "
            f"FROM orders {rollup_where}",
            rollup_params,
        )
        lifetime_total, completed_count, last_order_date = cur.fetchone()
        cur.execute(
            f"SELECT * FROM orders {where} ORDER BY order_date DESC, id DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = dict_fetchall(cur)

    return {
        "items": [Order(**_row_to_order(r)).model_dump() for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "lifetime_total": float(lifetime_total or 0),
        "completed_count": completed_count,
        "last_order_date": last_order_date.isoformat() if last_order_date else None,
    }


@router.post("/orders", response_model=Order, status_code=201)
def create_order(body: OrderCreate, current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    if body.status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    _assert_property(db, body.property_id, current_user["account_id"])
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO orders (property_id, order_number, order_date, total, item_count, items, "
            "channel, status, notes, created_by, account_id) "
            "VALUES (%s,%s,COALESCE(%s, CURRENT_DATE),%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (body.property_id, body.order_number, body.order_date, body.total, body.item_count,
             Json(body.items), body.channel, body.status, body.notes,
             current_user["id"], current_user["account_id"]),
        )
        row = _row_to_order(dict_fetchone(cur))
    _log_order_history(db, row, f"Order recorded — {_describe(row)}", current_user["id"])
    db.commit()
    _fire_order_event(db, row, "created", current_user["id"])
    return Order(**row)


@router.get("/orders/{order_id}", response_model=Order)
def get_order(order_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    return Order(**_get_order_or_404(db, order_id, user["account_id"]))


@router.patch("/orders/{order_id}", response_model=Order)
def update_order(order_id: int, body: OrderUpdate, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    existing = _get_order_or_404(db, order_id, user["account_id"])
    if body.status is not None and body.status not in ORDER_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    _assert_property(db, body.property_id, user["account_id"])

    sets, params = ["updated_at = NOW()"], []
    for field in _FIELDS:
        val = getattr(body, field)
        if val is not None:
            sets.append(f"{field} = %s")
            params.append(Json(val) if field == "items" else val)
    if len(sets) == 1:
        raise HTTPException(status_code=400, detail="Nothing to update")

    params.extend([order_id, user["account_id"]])
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE orders SET {', '.join(sets)} WHERE id = %s AND account_id = %s RETURNING *",
            params,
        )
        row = _row_to_order(dict_fetchone(cur))
    status_changed = body.status is not None and body.status != existing["status"]
    if status_changed:
        _log_order_history(db, row, f"Order {body.status} — {_describe(row)}", user["id"])
    db.commit()
    if status_changed:
        _fire_order_event(db, row, body.status, user["id"])
    return Order(**row)


@router.delete("/orders/{order_id}", status_code=204)
def delete_order(order_id: int, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM orders WHERE id = %s AND account_id = %s RETURNING id",
                    (order_id, current_user["account_id"]))
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Order not found")
