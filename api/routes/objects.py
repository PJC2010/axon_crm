"""
GET /api/objects/kpis — dashboard aggregates over the child-object tables.

One payload powering the business-type-specific KPI tiles (Phase 6):
insurance presets read premium_in_force / active_policies / renewals_30d,
retail reads revenue_mtd / orders_30d / repeat_rate. Registered ungated —
each block is computed only when the account has that object's module, and
omitted keys simply don't render as tiles.
"""
from fastapi import APIRouter, Depends, HTTPException
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, get_current_user, require_owner
from api.entitlements import account_has_module

router = APIRouter()


@router.get("/objects/kpis")
def object_kpis(user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    acct = user["account_id"]
    out: dict = {}

    if account_has_module(acct, "policies", db):
        with db.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(premium) FILTER (WHERE status = 'active'), 0), "
                "COUNT(*) FILTER (WHERE status = 'active'), "
                "COUNT(*) FILTER (WHERE status = 'active' AND expiration_date "
                "                 BETWEEN CURRENT_DATE AND CURRENT_DATE + 30) "
                "FROM policies WHERE account_id = %s",
                (acct,),
            )
            premium_in_force, active_policies, renewals_30d = cur.fetchone()
        out.update(
            premium_in_force=float(premium_in_force or 0),
            active_policies=active_policies,
            renewals_30d=renewals_30d,
        )

    if account_has_module(acct, "orders", db):
        with db.cursor() as cur:
            cur.execute(
                "SELECT COALESCE(SUM(total) FILTER (WHERE status = 'completed' "
                "                 AND order_date >= date_trunc('month', CURRENT_DATE)), 0), "
                "COUNT(*) FILTER (WHERE status = 'completed' "
                "                 AND order_date >= CURRENT_DATE - 30) "
                "FROM orders WHERE account_id = %s",
                (acct,),
            )
            revenue_mtd, orders_30d = cur.fetchone()
            # Repeat rate: of customers with any completed order, the share
            # with more than one — the retail health number.
            cur.execute(
                "SELECT COUNT(*) FILTER (WHERE n > 1), COUNT(*) FROM ("
                "  SELECT property_id, COUNT(*) AS n FROM orders "
                "  WHERE account_id = %s AND status = 'completed' AND property_id IS NOT NULL "
                "  GROUP BY property_id"
                ") per_customer",
                (acct,),
            )
            repeaters, buyers = cur.fetchone()
        out.update(
            revenue_mtd=float(revenue_mtd or 0),
            orders_30d=orders_30d,
            repeat_rate=(repeaters / buyers) if buyers else None,
        )

    if account_has_module(acct, "appointments", db):
        with db.cursor() as cur:
            cur.execute(
                "SELECT COUNT(*) FILTER (WHERE status = 'scheduled' AND starts_at "
                "                 BETWEEN NOW() AND NOW() + INTERVAL '7 days') "
                "FROM appointments WHERE account_id = %s",
                (acct,),
            )
            out["appointments_7d"] = cur.fetchone()[0]

    return out


@router.post("/objects/rescore")
def rescore_records(current_user: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    """Recompute lead scores for this account from its child-object roll-ups.

    Only meaningful for account-wide scored business types (insurance → renewal
    proximity, retail → RFM); a 400 tells other types there's nothing to do here.
    The nightly job does this automatically; this is the manual "rescore now".
    """
    from pipeline.account_rescore import profile_key_for_account, rescore_account

    acct = current_user["account_id"]
    if not profile_key_for_account(db, acct):
        raise HTTPException(
            status_code=400,
            detail="This business type is not scored from child-object roll-ups.",
        )
    updated = rescore_account(db, acct)
    db.commit()
    return {"updated": updated}
