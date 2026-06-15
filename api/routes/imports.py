"""
Contact / lead CSV import.

POST /api/imports/contacts/preview  — parse an uploaded file, auto-detect the
                                       column mapping, return sample rows + counts
POST /api/imports/contacts          — commit an import with a confirmed mapping
GET  /api/imports/contacts/template — download a sample CSV to fill in

Handles both address-based leads (deduped on (account_id, address, zip)) and
address-less people contacts (deduped on email). Imported rows are tagged
enrichment_flags = {"source": "csv_import"} and left unscored.
"""
import csv
import io
import json
import logging

import psycopg2.extras
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, get_current_user
from api.import_logic import TARGET_FIELDS, detect_mapping, normalize_row, row_is_usable
from api.models import ALLOWED_STATUSES, ImportOptions, ImportPreviewResponse, ImportResult
from api.ratelimit import import_limiter
from config import IMPORT_MAX_BYTES

log = logging.getLogger(__name__)
router = APIRouter()

SAMPLE_LIMIT = 10


async def _read_limited(file: UploadFile) -> bytes:
    """Read an upload, rejecting anything over IMPORT_MAX_BYTES before it can
    exhaust worker memory."""
    content = await file.read(IMPORT_MAX_BYTES + 1)
    if len(content) > IMPORT_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File too large — imports are limited to {IMPORT_MAX_BYTES // (1024 * 1024)} MB",
        )
    return content

# Columns an imported row may write, beyond the account_id key.
WRITABLE = TARGET_FIELDS + ["enrichment_flags", "lead_source"]


def _read_csv(content: bytes) -> tuple[list[str], list[dict]]:
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    headers = reader.fieldnames or []
    return headers, list(reader)


@router.post("/imports/contacts/preview", response_model=ImportPreviewResponse)
async def preview_import(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
):
    import_limiter.check(f"acct:{user['account_id']}")
    headers, raw_rows = _read_csv(await _read_limited(file))
    if not headers:
        raise HTTPException(status_code=400, detail="No columns found in file")

    mapping = detect_mapping(headers)
    normalized = [normalize_row(r, mapping) for r in raw_rows]
    usable = [r for r in normalized if row_is_usable(r)]

    return ImportPreviewResponse(
        headers=headers,
        target_fields=TARGET_FIELDS,
        mapping=mapping,
        total_rows=len(raw_rows),
        usable_rows=len(usable),
        skip_rows=len(raw_rows) - len(usable),
        sample=usable[:SAMPLE_LIMIT],
    )


@router.post("/imports/contacts", response_model=ImportResult)
async def run_import(
    file: UploadFile = File(...),
    mapping: str = Form(...),                 # JSON: {csv_header: field}
    default_vertical: str | None = Form(None),
    default_status: str = Form("new"),
    db: PGConn = Depends(get_db),
    user: dict = Depends(get_current_user),
):
    try:
        col_map: dict[str, str] = json.loads(mapping)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="mapping must be valid JSON")

    import_limiter.check(f"acct:{user['account_id']}")
    opts = ImportOptions(default_vertical=default_vertical, default_status=default_status)
    status = opts.default_status if opts.default_status in ALLOWED_STATUSES else "new"

    _, raw_rows = _read_csv(await _read_limited(file))
    result = ImportResult()

    with db.cursor() as cur:
        for i, raw in enumerate(raw_rows, start=1):
            row = normalize_row(raw, col_map)
            if not row_is_usable(row):
                result.skipped += 1
                continue
            row.setdefault("status", status)
            if opts.default_vertical and "vertical" not in row:
                row["vertical"] = opts.default_vertical
            row["enrichment_flags"] = {"source": "csv_import"}
            row["lead_source"] = "csv_import"
            # Savepoint per row so one bad row doesn't discard the whole import.
            cur.execute("SAVEPOINT import_row")
            try:
                inserted = _upsert_row(cur, user["account_id"], row)
                cur.execute("RELEASE SAVEPOINT import_row")
                if inserted:
                    result.imported += 1
                else:
                    result.updated += 1
            except Exception as exc:  # keep importing the rest of the file
                cur.execute("ROLLBACK TO SAVEPOINT import_row")
                result.errors.append(f"row {i}: {exc}")
    db.commit()

    log.info(
        "Contact import for account %s: %d new, %d updated, %d skipped, %d errors",
        user["account_id"], result.imported, result.updated, result.skipped, len(result.errors),
    )
    return result


def _upsert_row(cur, account_id: int, row: dict) -> bool:
    """Insert or update one imported row. Returns True if a new row was inserted.

    Dedup target depends on the row shape:
      - has address  -> (account_id, address, zip)
      - else has email -> partial unique index on (account_id, lower(contact_email))
      - else           -> plain insert (no key to dedup on)
    """
    data_cols = [c for c in WRITABLE if row.get(c) is not None]
    cols = ["account_id"] + data_cols
    values = [account_id] + [
        psycopg2.extras.Json(row[c]) if c == "enrichment_flags" else row[c]
        for c in data_cols
    ]
    col_names = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))

    if row.get("address"):
        key_cols = {"address", "zip"}
        conflict = "(account_id, address, zip)"
    elif row.get("contact_email"):
        key_cols = {"contact_email"}
        conflict = ("(account_id, lower(contact_email)) "
                    "WHERE address IS NULL AND contact_email IS NOT NULL")
    else:
        cur.execute(
            f"INSERT INTO properties ({col_names}) VALUES ({placeholders})",
            values,
        )
        return True

    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in data_cols if c not in key_cols)
    if "enrichment_flags" in data_cols:
        updates = updates.replace(
            "enrichment_flags = EXCLUDED.enrichment_flags",
            "enrichment_flags = properties.enrichment_flags || EXCLUDED.enrichment_flags",
        )
    cur.execute(
        f"INSERT INTO properties ({col_names}) VALUES ({placeholders}) "
        f"ON CONFLICT {conflict} DO UPDATE SET {updates} "
        f"RETURNING (xmax = 0) AS inserted",
        values,
    )
    return bool(cur.fetchone()[0])


_TEMPLATE_COLS = [
    "name", "phone", "email", "owner", "address", "city", "state", "zip",
    "estimated_value", "vertical", "status",
]


@router.get("/imports/contacts/template")
def download_template(_: dict = Depends(get_current_user)):
    """A blank CSV with generic headers the importer recognizes out of the box."""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_TEMPLATE_COLS)
    writer.writerow([
        "Jane Doe", "555-123-4567", "jane@example.com", "Jane Doe",
        "123 Main St", "Houston", "TX", "77002", "15000", "epoxy_flooring", "new",
    ])
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="axon_import_template.csv"'},
    )
