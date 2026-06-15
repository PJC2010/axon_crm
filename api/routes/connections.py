"""
Connectors / connections — connect a digital-presence source and import its data.

GET    /api/connections                       — list the account's connections
POST   /api/connections                       — register a connection (file auth)
DELETE /api/connections/{id}                  — disconnect (cascades its data)
POST   /api/connections/{id}/preview          — parse an upload, return counts/sample
POST   /api/connections/{id}/import           — commit a parsed Meta export

File imports today (Meta Business Suite / Ads Manager CSV, "Download Your
Information" JSON); the connection's auth_type leaves room for live OAuth sync
later, which would write the same social_* tables. Mirrors the contact-import
flow in api/routes/imports.py (size guard, preview→commit, per-row savepoints).
"""
import logging

import psycopg2.extras
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from psycopg2.extensions import connection as PGConn

from api.connectors import PROVIDER_LABELS, get_parser
from api.deps import dict_fetchall, dict_fetchone, get_current_user, get_db, require_owner
from api.models import (
    ConnectionCreate, ConnectionOut, SOCIAL_PROVIDERS,
    SocialImportPreview, SocialImportResult,
)
from api.ratelimit import import_limiter
from api.routes.imports import _read_limited

log = logging.getLogger(__name__)
router = APIRouter()

SAMPLE_LIMIT = 10

# social_metrics columns an imported metric row may populate (beyond the keys).
_METRIC_OPTIONAL = [
    "reach", "impressions", "profile_views", "followers", "follower_delta",
    "engagements", "link_clicks", "ad_spend", "ad_impressions", "ad_clicks",
    "ad_cpc", "ad_cpa", "ad_roas", "ad_results", "campaign_name",
]
# social_posts columns an imported post row may populate.
_POST_OPTIONAL = [
    "external_id", "posted_at", "content_type", "caption", "permalink",
    "reach", "impressions", "likes", "comments", "shares", "saves",
    "engagements", "link_clicks",
]


def _load_connection(db: PGConn, account_id: int, conn_id: int) -> dict:
    """Fetch a connection, enforcing tenant ownership (404 otherwise)."""
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, provider, display_name, status, auth_type, last_synced_at, created_at "
            "FROM connections WHERE id = %s AND account_id = %s",
            (conn_id, account_id),
        )
        row = dict_fetchone(cur)
    if not row:
        raise HTTPException(status_code=404, detail="Connection not found")
    return row


# ── Connection CRUD ───────────────────────────────────────────────────────────

@router.get("/connections", response_model=list[ConnectionOut])
def list_connections(user: dict = Depends(get_current_user), db: PGConn = Depends(get_db)):
    with db.cursor() as cur:
        cur.execute(
            "SELECT id, provider, display_name, status, auth_type, last_synced_at, created_at "
            "FROM connections WHERE account_id = %s ORDER BY created_at DESC",
            (user["account_id"],),
        )
        return dict_fetchall(cur)


@router.post("/connections", response_model=ConnectionOut)
def create_connection(
    body: ConnectionCreate,
    user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
):
    if body.provider not in SOCIAL_PROVIDERS:
        raise HTTPException(status_code=400, detail=f"Unsupported provider '{body.provider}'")
    name = body.display_name or PROVIDER_LABELS.get(body.provider, body.provider)
    with db.cursor() as cur:
        # Re-connecting the same provider just refreshes the existing row.
        cur.execute(
            """
            INSERT INTO connections (account_id, provider, display_name, auth_type, status, created_by)
            VALUES (%s, %s, %s, 'file', 'connected', %s)
            ON CONFLICT (account_id, provider) DO UPDATE
              SET display_name = EXCLUDED.display_name, status = 'connected'
            RETURNING id, provider, display_name, status, auth_type, last_synced_at, created_at
            """,
            (user["account_id"], body.provider, name, user["id"]),
        )
        row = dict_fetchone(cur)
    db.commit()
    return row


@router.delete("/connections/{conn_id}", status_code=204)
def delete_connection(
    conn_id: int,
    user: dict = Depends(require_owner),
    db: PGConn = Depends(get_db),
):
    _load_connection(db, user["account_id"], conn_id)
    with db.cursor() as cur:
        cur.execute(
            "DELETE FROM connections WHERE id = %s AND account_id = %s",
            (conn_id, user["account_id"]),
        )
    db.commit()


# ── File import (preview / commit) ────────────────────────────────────────────

@router.post("/connections/{conn_id}/preview", response_model=SocialImportPreview)
async def preview_social_import(
    conn_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    import_limiter.check(f"acct:{user['account_id']}")
    conn = _load_connection(db, user["account_id"], conn_id)
    parser = get_parser(conn["provider"])
    if parser is None:
        raise HTTPException(status_code=400, detail="This connection cannot import files")

    content = await _read_limited(file)
    parsed = parser(content, file.filename or "")
    return SocialImportPreview(
        export_kind=parsed.export_kind,
        metric_rows=len(parsed.metrics),
        post_rows=len(parsed.posts),
        period_start=parsed.period_start,
        period_end=parsed.period_end,
        sample_metrics=[_jsonable(m) for m in parsed.metrics[:SAMPLE_LIMIT]],
        sample_posts=[_jsonable(p) for p in parsed.posts[:SAMPLE_LIMIT]],
        errors=parsed.errors[:SAMPLE_LIMIT],
    )


@router.post("/connections/{conn_id}/import", response_model=SocialImportResult)
async def run_social_import(
    conn_id: int,
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
    db: PGConn = Depends(get_db),
):
    import_limiter.check(f"acct:{user['account_id']}")
    account_id = user["account_id"]
    conn = _load_connection(db, account_id, conn_id)
    provider = conn["provider"]
    parser = get_parser(provider)
    if parser is None:
        raise HTTPException(status_code=400, detail="This connection cannot import files")

    content = await _read_limited(file)
    parsed = parser(content, file.filename or "")
    result = SocialImportResult(import_id=0, errors=list(parsed.errors))

    with db.cursor() as cur:
        # 1. Open the audit batch row.
        cur.execute(
            """
            INSERT INTO social_imports
              (account_id, connection_id, provider, source, export_kind, file_name,
               period_start, period_end, status, created_by)
            VALUES (%s, %s, %s, 'file', %s, %s, %s, %s, 'completed', %s)
            RETURNING id
            """,
            (account_id, conn_id, provider, parsed.export_kind, file.filename,
             parsed.period_start, parsed.period_end, user["id"]),
        )
        import_id = cur.fetchone()[0]
        result.import_id = import_id

        # 2. Upsert metrics, then posts — per-row savepoint isolates bad rows.
        for i, row in enumerate(parsed.metrics, start=1):
            cur.execute("SAVEPOINT social_row")
            try:
                _upsert_metric(cur, account_id, conn_id, import_id, provider, row)
                cur.execute("RELEASE SAVEPOINT social_row")
                result.metrics_imported += 1
            except Exception as exc:
                cur.execute("ROLLBACK TO SAVEPOINT social_row")
                result.skipped += 1
                result.errors.append(f"metric row {i}: {exc}")

        for i, row in enumerate(parsed.posts, start=1):
            cur.execute("SAVEPOINT social_row")
            try:
                _insert_post(cur, account_id, conn_id, import_id, provider, row)
                cur.execute("RELEASE SAVEPOINT social_row")
                result.posts_imported += 1
            except Exception as exc:
                cur.execute("ROLLBACK TO SAVEPOINT social_row")
                result.skipped += 1
                result.errors.append(f"post row {i}: {exc}")

        # 3. Finalize the batch + connection sync state.
        cur.execute(
            "UPDATE social_imports SET rows_imported = %s, errors = %s, "
            "status = %s WHERE id = %s",
            (result.metrics_imported + result.posts_imported,
             psycopg2.extras.Json(result.errors) if result.errors else None,
             "partial" if result.errors else "completed", import_id),
        )
        cur.execute(
            "UPDATE connections SET last_synced_at = NOW(), status = 'connected' "
            "WHERE id = %s AND account_id = %s",
            (conn_id, account_id),
        )
    db.commit()

    log.info(
        "Social import for account %s connection %s: %d metrics, %d posts, %d skipped, %d errors",
        account_id, conn_id, result.metrics_imported, result.posts_imported,
        result.skipped, len(result.errors),
    )
    return result


# ── Row writers ───────────────────────────────────────────────────────────────

def _upsert_metric(cur, account_id, conn_id, import_id, provider, row: dict) -> None:
    cols = ["account_id", "connection_id", "import_id", "provider", "source", "metric_date"]
    vals = [account_id, conn_id, import_id, provider, "file", row["metric_date"]]
    for c in _METRIC_OPTIONAL:
        if row.get(c) is not None:
            cols.append(c)
            vals.append(row[c])
    cols.append("raw")
    vals.append(psycopg2.extras.Json(row.get("raw") or {}))

    placeholders = ", ".join(["%s"] * len(cols))
    # campaign_name is part of the conflict key, so it is never in the update set.
    update_cols = [c for c in cols if c not in ("account_id", "connection_id", "metric_date", "campaign_name")]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
    cur.execute(
        f"INSERT INTO social_metrics ({', '.join(cols)}) VALUES ({placeholders}) "
        f"ON CONFLICT (connection_id, metric_date, COALESCE(campaign_name, '')) "
        f"DO UPDATE SET {set_clause}",
        vals,
    )


def _insert_post(cur, account_id, conn_id, import_id, provider, row: dict) -> None:
    cols = ["account_id", "connection_id", "import_id", "provider", "source"]
    vals = [account_id, conn_id, import_id, provider, "file"]
    for c in _POST_OPTIONAL:
        if row.get(c) is not None:
            cols.append(c)
            vals.append(row[c])
    cols.append("raw")
    vals.append(psycopg2.extras.Json(row.get("raw") or {}))

    placeholders = ", ".join(["%s"] * len(cols))
    if row.get("external_id"):
        update_cols = [c for c in cols if c not in ("account_id", "connection_id", "external_id")]
        set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update_cols)
        cur.execute(
            f"INSERT INTO social_posts ({', '.join(cols)}) VALUES ({placeholders}) "
            f"ON CONFLICT (connection_id, external_id) WHERE external_id IS NOT NULL "
            f"DO UPDATE SET {set_clause}",
            vals,
        )
    else:
        cur.execute(
            f"INSERT INTO social_posts ({', '.join(cols)}) VALUES ({placeholders})",
            vals,
        )


def _jsonable(row: dict) -> dict:
    """Make a parsed row JSON-serializable for the preview sample (dates -> str)."""
    out = {}
    for k, v in row.items():
        if k == "raw":
            continue
        out[k] = v.isoformat() if hasattr(v, "isoformat") else v
    return out
