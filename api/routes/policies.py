"""
GET    /api/policies         — list (filters: status, property_id, page) + roll-ups
POST   /api/policies         — create
GET    /api/policies/{id}    — single
PATCH  /api/policies/{id}    — update
DELETE /api/policies/{id}    — delete (owner only)

Policies are the insurance book of business (Phase 5 associated object). Their
expiration_date drives date_offset workflow rules (renewal/X-date automation —
see DATE_TRIGGER_SOURCES in api/workflow_engine.py). Lifecycle events (created /
status changes) fire policy_event rules and log to the lead's activity feed.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, dict_fetchall, dict_fetchone, get_current_user, require_owner
from api.models import Policy, PolicyCreate, PolicyUpdate, POLICY_STATUSES

log = logging.getLogger(__name__)

router = APIRouter()

_FIELDS = ("property_id", "policy_number", "carrier", "policy_type", "premium",
           "billing_frequency", "effective_date", "expiration_date", "status",
           "commission_rate", "notes")


def _get_policy_or_404(db: PGConn, policy_id: int, account_id: int) -> dict:
    with db.cursor() as cur:
        cur.execute("SELECT * FROM policies WHERE id = %s AND account_id = %s", (policy_id, account_id))
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Policy not found")
    return row


def _fire_policy_event(db: PGConn, policy: dict, event: str, user_id: int) -> None:
    """Run policy_event workflow rules; never let automation break the request."""
    from api.workflow_engine import execute_object_event_rules
    try:
        execute_object_event_rules(
            db, account_id=policy["account_id"], lead_id=policy["property_id"],
            object_type="policy", event=event, user_id=user_id,
        )
    except Exception:
        log.exception("policy_event rules failed for policy %d (%s)", policy["id"], event)


def _log_policy_history(db: PGConn, policy: dict, action: str, user_id: int) -> None:
    """Surface lifecycle events in the linked lead's activity feed."""
    if not policy.get("property_id"):
        return
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO contact_history (property_id, action, outcome, created_by) "
            "VALUES (%s, %s, %s, %s)",
            (policy["property_id"], action, policy.get("status"), user_id),
        )


def _describe(policy: dict) -> str:
    bits = [b for b in (policy.get("carrier"), policy.get("policy_type")) if b]
    return " ".join(bits) if bits else (policy.get("policy_number") or f"#{policy['id']}")


@router.get("/policies", response_model=dict)
def list_policies(
    status: Optional[str] = Query(None),
    property_id: Optional[int] = Query(None),
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
    where = "WHERE " + " AND ".join(conditions)
    offset = (page - 1) * page_size

    with db.cursor() as cur:
        cur.execute(f"SELECT COUNT(*) FROM policies {where}", params)
        total = cur.fetchone()[0]
        # Roll-ups over the same scope minus the status filter, so the header
        # numbers stay stable while the user flips status tabs.
        rollup_where = "WHERE account_id = %s" + (" AND property_id = %s" if property_id is not None else "")
        rollup_params = [user["account_id"]] + ([property_id] if property_id is not None else [])
        cur.execute(
            f"SELECT COALESCE(SUM(premium) FILTER (WHERE status = 'active'), 0), "
            f"COUNT(*) FILTER (WHERE status = 'active'), "
            f"MIN(expiration_date) FILTER (WHERE status = 'active' AND expiration_date >= CURRENT_DATE) "
            f"FROM policies {rollup_where}",
            rollup_params,
        )
        premium_in_force, active_count, next_expiration = cur.fetchone()
        cur.execute(
            f"SELECT * FROM policies {where} ORDER BY expiration_date ASC NULLS LAST, id DESC "
            f"LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = dict_fetchall(cur)

    return {
        "items": [Policy(**r).model_dump() for r in rows],
        "total": total,
        "page": page,
        "page_size": page_size,
        "premium_in_force": float(premium_in_force or 0),
        "active_count": active_count,
        "next_expiration": next_expiration.isoformat() if next_expiration else None,
    }


@router.post("/policies", response_model=Policy, status_code=201)
def create_policy(body: PolicyCreate, current_user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    if body.status not in POLICY_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO policies (property_id, policy_number, carrier, policy_type, premium, "
            "billing_frequency, effective_date, expiration_date, status, commission_rate, notes, "
            "created_by, account_id) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
            (body.property_id, body.policy_number, body.carrier, body.policy_type, body.premium,
             body.billing_frequency, body.effective_date, body.expiration_date, body.status,
             body.commission_rate, body.notes, current_user["id"], current_user["account_id"]),
        )
        row = dict_fetchone(cur)
    _log_policy_history(db, row, f"Policy created — {_describe(row)}", current_user["id"])
    db.commit()
    _fire_policy_event(db, row, "created", current_user["id"])
    return Policy(**row)


@router.get("/policies/{policy_id}", response_model=Policy)
def get_policy(policy_id: int, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    return Policy(**_get_policy_or_404(db, policy_id, user["account_id"]))


@router.patch("/policies/{policy_id}", response_model=Policy)
def update_policy(policy_id: int, body: PolicyUpdate, user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    existing = _get_policy_or_404(db, policy_id, user["account_id"])
    if body.status is not None and body.status not in POLICY_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status")

    sets, params = ["updated_at = NOW()"], []
    for field in _FIELDS:
        val = getattr(body, field)
        if val is not None:
            sets.append(f"{field} = %s"); params.append(val)
    if len(sets) == 1:
        raise HTTPException(status_code=400, detail="Nothing to update")

    params.extend([policy_id, user["account_id"]])
    with db.cursor() as cur:
        cur.execute(
            f"UPDATE policies SET {', '.join(sets)} WHERE id = %s AND account_id = %s RETURNING *",
            params,
        )
        row = dict_fetchone(cur)
    status_changed = body.status is not None and body.status != existing["status"]
    if status_changed:
        _log_policy_history(db, row, f"Policy {body.status} — {_describe(row)}", user["id"])
    db.commit()
    if status_changed:
        _fire_policy_event(db, row, body.status, user["id"])
    return Policy(**row)


@router.delete("/policies/{policy_id}", status_code=204)
def delete_policy(policy_id: int, current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute("DELETE FROM policies WHERE id = %s AND account_id = %s RETURNING id",
                    (policy_id, current_user["account_id"]))
        deleted = cur.fetchone()
        db.commit()
    if not deleted:
        raise HTTPException(status_code=404, detail="Policy not found")
