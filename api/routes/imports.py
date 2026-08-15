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
from api.import_logic import (
    TARGET_FIELDS, detect_mapping, normalize_row, normalize_status, row_is_usable,
)
from api.models import ALLOWED_STATUSES, ImportOptions, ImportPreviewResponse, ImportResult
from api.ratelimit import import_limiter
from config import IMPORT_MAX_BYTES, IMPORT_MAX_ROWS

log = logging.getLogger(__name__)
router = APIRouter()

SAMPLE_LIMIT = 10
# Only the first few failures are worth returning; the rest of a systematically
# broken file just repeats itself and would bloat the response unboundedly.
ERROR_LIMIT = 25


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


# Byte-order marks, longest first so utf-8's doesn't shadow anything.
_BOMS = [
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xff\xfe\x00\x00", "utf-32"),
    (b"\x00\x00\xfe\xff", "utf-32"),
    (b"\xff\xfe", "utf-16"),
    (b"\xfe\xff", "utf-16"),
]


# Spreadsheets people upload instead of exporting to CSV. .xlsx/.numbers/.ods
# are ZIP containers; .xls is an OLE compound file.
_BINARY_MAGIC = {
    b"PK\x03\x04": "an .xlsx / .numbers / .ods workbook",
    b"\xd0\xcf\x11\xe0": "an .xls workbook",
    b"%PDF": "a PDF",
}


def _reject_if_binary(content: bytes) -> None:
    """Refuse a file that plainly isn't text, with a message that says what to do.

    Parsed as CSV a workbook yields a screenful of garbage "columns" and zero
    importable rows, which reads as "the importer is broken" rather than "wrong
    file".

    The fallback is deliberately a NUL *density* test, not "contains a NUL": a
    stray control byte in an otherwise fine export is common and clean_value
    already strips it, so one must not cost the user the whole file. BOM-carrying
    UTF-16 is exempt — it is legitimately full of NULs and _decode handles it.
    """
    for magic, what in _BINARY_MAGIC.items():
        if content.startswith(magic):
            raise HTTPException(
                status_code=400,
                detail=f"This looks like {what}, not a CSV. "
                       "Open it and use File → Save As / Export → CSV, then upload that.",
            )
    head = content[:8192]
    nuls = head.count(b"\x00")
    if (nuls >= 4 and nuls * 100 >= len(head)          # >=1%, with a small floor
            and not any(content.startswith(b) for b, _ in _BOMS)):
        raise HTTPException(
            status_code=400,
            detail="This file isn't readable as text — export it as CSV and upload that.",
        )


def _decode(content: bytes) -> str:
    """Decode an uploaded CSV without silently corrupting non-ASCII names.

    Excel on Windows still writes cp1252 by default and "Unicode text" writes
    UTF-16, so decoding everything as UTF-8 with errors="replace" turned "José"
    into "Jos�" — permanently, since the mojibake is what got stored. Try the
    BOM first, then strict UTF-8, then the Windows codepages, and only mangle
    characters when every one of those has failed.
    """
    for bom, encoding in _BOMS:
        if content.startswith(bom):
            try:
                return content.decode(encoding)
            except UnicodeDecodeError:
                break
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _sniff_delimiter(text: str) -> str:
    """Pick the delimiter from the header line.

    A European Excel export is semicolon-separated and a Sheets export can be
    tab-separated; parsed as comma-delimited each collapses to a single unnamed
    column, which surfaced as "0 of 400 rows look importable" with no
    explanation of why.
    """
    header = text.split("\n", 1)[0]
    if not header:
        return ","
    try:
        return csv.Sniffer().sniff(header, delimiters=",;\t|").delimiter
    except csv.Error:
        return ","


def _read_csv(content: bytes) -> tuple[list[str], list[dict]]:
    """Parse an upload into (headers, rows), raising 400 on anything unreadable.

    csv.Error is a normal outcome here — an .xlsx dropped on the picker, or a
    cell over the 128 KB field limit — and it used to escape as a 500.
    """
    _reject_if_binary(content)
    text = _decode(content)
    try:
        reader = csv.DictReader(io.StringIO(text, newline=""),
                                delimiter=_sniff_delimiter(text))
        headers = reader.fieldnames or []
        rows = []
        for row in reader:
            rows.append(row)
            if len(rows) > IMPORT_MAX_ROWS:
                raise HTTPException(
                    status_code=400,
                    detail=(f"File has more than {IMPORT_MAX_ROWS:,} rows — "
                            "split it and import the parts separately"),
                )
    except csv.Error as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Could not read this file as CSV ({exc}). "
                   "Export it as CSV — .xlsx and .numbers files aren't supported yet.",
        )
    return headers, rows


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
    # Count as we go and keep only the sample: a preview runs in the same
    # process that serves the API, so it must not hold a second normalized copy
    # of the whole file in memory alongside the parsed one.
    usable_rows = 0
    sample: list[dict] = []
    for raw in raw_rows:
        row = normalize_row(raw, mapping)
        if not row_is_usable(row):
            continue
        usable_rows += 1
        if len(sample) < SAMPLE_LIMIT:
            sample.append(row)

    return ImportPreviewResponse(
        headers=headers,
        target_fields=TARGET_FIELDS,
        mapping=mapping,
        total_rows=len(raw_rows),
        usable_rows=usable_rows,
        skip_rows=len(raw_rows) - usable_rows,
        sample=sample,
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
        col_map = json.loads(mapping)
    except (json.JSONDecodeError, TypeError):
        raise HTTPException(status_code=400, detail="mapping must be valid JSON")
    if not isinstance(col_map, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in col_map.items()):
        raise HTTPException(
            status_code=400, detail="mapping must be a JSON object of {column: field}")

    import_limiter.check(f"acct:{user['account_id']}")
    opts = ImportOptions(default_vertical=default_vertical, default_status=default_status)

    # Parse before touching the database, so an unreadable file costs a 400 and
    # not a connection.
    _, raw_rows = _read_csv(await _read_limited(file))

    valid_statuses = _account_statuses(db, user["account_id"])
    status = normalize_status(opts.default_status or "")
    if status not in valid_statuses:
        status = "new"

    result = ImportResult()
    new_lead_ids: list[int] = []

    with db.cursor() as cur:
        for i, raw in enumerate(raw_rows, start=1):
            row = normalize_row(raw, col_map)
            if not row_is_usable(row):
                result.skipped += 1
                continue
            # A status the account has no stage for would leave the lead out of
            # every Kanban column, so fall back to the import's default.
            if row.get("status") not in valid_statuses:
                if row.get("status"):
                    result.coerced_statuses += 1
                row["status"] = status
            if opts.default_vertical and "vertical" not in row:
                row["vertical"] = opts.default_vertical
            row["enrichment_flags"] = {"source": "csv_import"}
            row["lead_source"] = "csv_import"
            # Savepoint per row so one bad row doesn't discard the whole import.
            cur.execute("SAVEPOINT import_row")
            try:
                inserted, lead_id = _upsert_row(cur, user["account_id"], row)
                cur.execute("RELEASE SAVEPOINT import_row")
                if inserted:
                    result.imported += 1
                    if lead_id is not None:
                        new_lead_ids.append(lead_id)
                else:
                    result.updated += 1
            except Exception as exc:  # keep importing the rest of the file
                cur.execute("ROLLBACK TO SAVEPOINT import_row")
                result.error_count += 1
                if len(result.errors) < ERROR_LIMIT:
                    result.errors.append(f"row {i}: {exc}")
    db.commit()

    # Fire lead_imported automations for the freshly created leads (e.g. an
    # "initial outreach" follow-up task), so imported lists land on a rep's radar.
    if new_lead_ids:
        try:
            from api.workflow_engine import execute_import_rules
            execute_import_rules(db, user["account_id"], new_lead_ids, user["id"])
        except Exception:
            log.exception("lead_imported rules failed for account %s", user["account_id"])

    log.info(
        "Contact import for account %s: %d new, %d updated, %d skipped, %d errors, "
        "%d statuses coerced",
        user["account_id"], result.imported, result.updated, result.skipped,
        result.error_count, result.coerced_statuses,
    )
    return result


def _account_statuses(db: PGConn, account_id: int) -> set[str]:
    """Status keys an imported row may carry: the account's own pipeline stages,
    plus the built-in set so an account that has never customized its board (or
    whose stages failed to load) still accepts the standard statuses."""
    statuses = set(ALLOWED_STATUSES)
    with db.cursor() as cur:
        cur.execute("SELECT key FROM pipeline_stages WHERE account_id = %s", (account_id,))
        statuses.update(r[0] for r in cur.fetchall() if r[0])
    return statuses


def _find_existing_by_address(cur, account_id: int, address: str,
                              zip_code: str | None) -> tuple[int, str | None] | None:
    """Find this account's existing row for `address`, or None.

    Matching goes through axon_normalize_address (db/migrations/0065) — the same
    rule pipeline/addr.py applies everywhere else — so "12 Ash St", "12 ash st"
    and "12 Ash St." resolve to one lead instead of three. It also covers the
    case ON CONFLICT structurally cannot: Postgres treats NULLs as distinct, so
    a row with an address but no ZIP never matched the (account_id, address, zip)
    key and every re-import of the same file inserted it again.

    A row whose ZIP is NULL matches an incoming row that carries one, so the ZIP
    fills in rather than forking the lead. Prefer an exact ZIP match when both
    kinds exist, and the oldest row when several still tie.
    """
    cur.execute(
        "SELECT id, zip FROM properties "
        "WHERE account_id = %s "
        "  AND axon_normalize_address(address) = axon_normalize_address(%s) "
        "  AND (zip IS NOT DISTINCT FROM %s OR zip IS NULL) "
        "ORDER BY (zip IS NOT DISTINCT FROM %s) DESC, id "
        "LIMIT 1",
        (account_id, address, zip_code, zip_code),
    )
    return cur.fetchone()


def _update_existing(cur, account_id: int, lead_id: int, row: dict,
                     skip: set[str]) -> None:
    """Apply an imported row to an existing lead, leaving `skip` columns alone."""
    cols = [c for c in WRITABLE if row.get(c) is not None and c not in skip]
    sets, values = [], []
    for c in cols:
        if c == "enrichment_flags":
            sets.append("enrichment_flags = properties.enrichment_flags || %s")
            values.append(psycopg2.extras.Json(row[c]))
        else:
            sets.append(f"{c} = %s")
            values.append(row[c])
    if not sets:
        return
    cur.execute(
        f"UPDATE properties SET {', '.join(sets)} WHERE id = %s AND account_id = %s",
        values + [lead_id, account_id],
    )


# The stored half of the phone key, byte-compatible with
# api/routes/twilio_inbound.py::normalize_phone (last 10 digits) — the one rule
# this codebase compares phone numbers by.
_SQL_PHONE_KEY = "right(regexp_replace(coalesce(contact_phone, ''), '[^0-9]', '', 'g'), 10)"


def _find_existing_by_phone(cur, account_id: int, phone: str,
                            name: str | None) -> int | None:
    """Find an address-less contact with this phone *and* this name, or None.

    A phone-only row has no address to key on and no email either, so before
    this every re-import of the same list inserted the whole contact again.

    The name has to match too, which is the conservative half: an email
    identifies one person, but a household or shop landline is shared, so
    matching on the number alone would collapse two people into one and lose a
    contact. Same person twice in a file matches; two people on one line don't.
    """
    from api.routes.twilio_inbound import normalize_phone

    key = normalize_phone(phone)
    if not key:
        return None
    cur.execute(
        f"SELECT id FROM properties "
        f"WHERE account_id = %s AND address IS NULL AND {_SQL_PHONE_KEY} = %s "
        f"  AND lower(btrim(coalesce(contact_name, ''))) = %s "
        f"ORDER BY id LIMIT 1",
        (account_id, key, (name or "").strip().lower()),
    )
    found = cur.fetchone()
    return found[0] if found else None


def _upsert_row(cur, account_id: int, row: dict) -> tuple[bool, int | None]:
    """Insert or update one imported row. Returns (inserted, lead_id) where
    `inserted` is True when a new row was created (vs. an existing one updated).

    Dedup target depends on the row shape:
      - has address  -> normalized address + ZIP within the account, falling
                        back to the (account_id, address, zip) key as the
                        insert-race guard
      - else has email -> partial unique index on (account_id, lower(contact_email))
      - else has phone -> that phone *and* that name, among address-less rows
      - else           -> plain insert (a bare name is not an identity)
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
        existing = _find_existing_by_address(cur, account_id, row["address"], row.get("zip"))
        if existing:
            lead_id, existing_zip = existing
            # Never rewrite the address we matched on; fill the ZIP only when
            # the stored row hasn't got one.
            skip = {"address"} | ({"zip"} if existing_zip else set())
            _update_existing(cur, account_id, lead_id, row, skip)
            return False, lead_id
        key_cols = {"address", "zip"}
        conflict = "(account_id, address, zip)"
    elif row.get("contact_email"):
        key_cols = {"contact_email"}
        conflict = ("(account_id, lower(contact_email)) "
                    "WHERE address IS NULL AND contact_email IS NOT NULL")
    else:
        if row.get("contact_phone"):
            lead_id = _find_existing_by_phone(
                cur, account_id, row["contact_phone"], row.get("contact_name"))
            if lead_id is not None:
                _update_existing(cur, account_id, lead_id, row, skip=set())
                return False, lead_id
        cur.execute(
            f"INSERT INTO properties ({col_names}) VALUES ({placeholders}) RETURNING id",
            values,
        )
        return True, cur.fetchone()[0]

    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in data_cols if c not in key_cols)
    if "enrichment_flags" in data_cols:
        updates = updates.replace(
            "enrichment_flags = EXCLUDED.enrichment_flags",
            "enrichment_flags = properties.enrichment_flags || EXCLUDED.enrichment_flags",
        )
    cur.execute(
        f"INSERT INTO properties ({col_names}) VALUES ({placeholders}) "
        f"ON CONFLICT {conflict} DO UPDATE SET {updates} "
        f"RETURNING id, (xmax = 0) AS inserted",
        values,
    )
    lead_id, inserted = cur.fetchone()
    return bool(inserted), lead_id


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
