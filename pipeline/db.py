"""Shared database connection and upsert helper."""
import threading
import time

import psycopg2
import psycopg2.extras
from config import DATABASE_URL, MAX_GARAGE_SPACES
from pipeline.addr import sql_has_situs


def get_conn():
    return psycopg2.connect(DATABASE_URL)


# ── Upsert instrumentation (opt-in) ───────────────────────────────────────────
# upsert_properties is called from nearly every pipeline step, so its cost is
# spread across the run and invisible in per-step wall-clock alone. This probe
# accumulates counters for whichever step is currently active; `groups` is the
# number of distinct column signatures the batch was split into, which is how a
# fragmented batch (many small round trips instead of a few large ones) shows up.
#
# Thread-local because APScheduler runs pipeline jobs in a pool — two concurrent
# runs would otherwise cross-contaminate each other's counters. Inactive by
# default: with no probe installed the write path costs one getattr.

_upsert_local = threading.local()


class UpsertProbe:
    """reset()/read() counter matching the probe protocol in pipeline.timing.

    Install one per thread with `install()`; it stays active for that thread
    until `uninstall()`. Counters are per-step: `reset()` zeroes them, `read()`
    returns a snapshot of what the step just did.
    """

    @staticmethod
    def install() -> "UpsertProbe":
        probe = UpsertProbe()
        _upsert_local.stats = _blank_upsert_stats()
        return probe

    @staticmethod
    def uninstall() -> None:
        _upsert_local.stats = None

    def reset(self) -> None:
        _upsert_local.stats = _blank_upsert_stats()

    def read(self) -> dict | None:
        stats = getattr(_upsert_local, "stats", None)
        if not stats or not stats["calls"]:
            return None
        return {**stats, "seconds": round(stats["seconds"], 2)}


def _blank_upsert_stats() -> dict:
    return {"calls": 0, "groups": 0, "rows": 0, "seconds": 0.0}


def _record_upsert(groups: int, rows: int, seconds: float) -> None:
    stats = getattr(_upsert_local, "stats", None)
    if stats is None:
        return
    stats["calls"] += 1
    stats["groups"] += groups
    stats["rows"] += rows
    stats["seconds"] += seconds


# Allowlist of writable columns. Used both as the upsert column set and to guard
# dynamic column references (e.g. fetch_missing_any) against SQL injection.
ALL_COLS = [
    "address", "city", "state", "zip", "latitude", "longitude", "geohash",
    "year_built", "square_footage", "garage_spaces", "garage_type", "lot_size",
    "property_type", "estimated_value", "estimated_equity",
    "last_sale_date", "last_sale_price", "owner_name", "owner_occupied",
    "ownership_years", "zip_median_income", "permit_count_24mo",
    "has_pool", "has_cracked_slab",
    "hcad_neighborhood_code", "hcad_neighborhood_name",
    "contact_name", "contact_phone", "contact_email", "mailing_address",
    "lead_score", "score_grade", "vertical", "score_updated_at",
    "enrichment_flags",
    # Geo provenance (migration 049) — RentCast leads arrive pre-geocoded
    "geocode_source", "geocode_confidence", "h3_r8",
    # Prospecting cluster key (migration 051) — RentCast subdivision name
    "subdivision",
    # Lead attribution — rep ownership + acquisition source (migration 030)
    "assigned_to", "lead_source",
    # Storm/hail enrichment (migration 027)
    "last_storm_date", "last_storm_type", "hail_size_in", "storm_count_24mo",
    # Household demographics / life-events (migration 028)
    "owner_age", "length_of_residence_years", "est_household_income", "life_stage",
    # Versium Demographic Append — scoring signals (migration 029)
    "refi_date", "home_improvement_flag", "credit_rating", "has_children", "gardening_flag",
    # Versium Demographic Append — model features (migration 029)
    "age_range", "estimated_net_worth", "loan_to_value", "marital_status", "occupation",
    "senior_in_household", "pets_flag", "decorating_flag", "credit_lines_count",
    "mortgage_rate_type",
]


# Rows sharing one INSERT statement per batched round-trip. Postgres handles
# large multi-row VALUES fine; this bounds per-statement size and memory.
UPSERT_PAGE_SIZE = 500


def _upsert_sql(data_cols: tuple) -> str:
    """Build the INSERT ... ON CONFLICT statement for one column signature.

    `data_cols` is the ordered tuple of non-None columns shared by every row in
    a batch. account_id is prepended (it is part of the conflict key). Uses the
    ``VALUES %s`` placeholder that psycopg2's execute_values expands.
    """
    col_names = ", ".join(["account_id", *data_cols])
    updates = ", ".join(
        f"{c} = EXCLUDED.{c}" for c in data_cols if c not in ("address", "zip")
    )
    # Merge enrichment_flags rather than overwrite so earlier steps' flags survive.
    if "enrichment_flags" in data_cols:
        updates = updates.replace(
            "enrichment_flags = EXCLUDED.enrichment_flags",
            "enrichment_flags = properties.enrichment_flags || EXCLUDED.enrichment_flags",
        )
    # A row whose only non-key columns are address/zip has nothing to update; skip
    # the write on conflict rather than emit an invalid empty SET clause.
    conflict = f"DO UPDATE SET {updates}" if updates else "DO NOTHING"
    return (
        f"INSERT INTO properties ({col_names}) VALUES %s "
        f"ON CONFLICT (account_id, address, zip) {conflict} RETURNING 1"
    )


def clamp_garage_spaces(value):
    """Defense-in-depth cap on garage_spaces at write time. Sources occasionally
    confuse garage square footage for a space count (HCAD's `uts` units were the
    canonical case); no residence legitimately exceeds MAX_GARAGE_SPACES."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if value > MAX_GARAGE_SPACES:
            return MAX_GARAGE_SPACES
        if value < 0:
            return 0
    return value


def upsert_properties(conn, rows: list[dict], account_id: int) -> int:
    """
    Upsert a list of property dicts into the properties table for one org.
    Conflict target is (account_id, address, zip) so each org keeps its own
    copy of a property. Only non-None values are written so a partial
    enrichment step does not clobber fields set by an earlier step.
    Returns the number of rows affected.

    Rows are grouped by their set of non-None columns and each group is written
    with a single batched multi-row INSERT (execute_values), so a ZIP of N
    properties costs a handful of round-trips instead of N.
    """
    if not rows:
        return 0

    # Group by column signature: rows with the same non-None columns share one
    # INSERT statement. account_id is written first and is part of the conflict key.
    groups: dict[tuple, list[list]] = {}
    for row in rows:
        data_cols = tuple(c for c in ALL_COLS if row.get(c) is not None)
        if not data_cols:
            continue
        values = [account_id] + [
            psycopg2.extras.Json(row[c])
            if c == "enrichment_flags" and isinstance(row[c], dict)
            else clamp_garage_spaces(row[c]) if c == "garage_spaces"
            else row[c]
            for c in data_cols
        ]
        groups.setdefault(data_cols, []).append(values)

    count = 0
    started = time.perf_counter()
    with conn.cursor() as cur:
        for data_cols, argslist in groups.items():
            # fetch=True aggregates the RETURNING rows across all internal pages,
            # so len() is an exact affected-row count (insert + update) even when
            # execute_values splits the batch by page_size.
            returned = psycopg2.extras.execute_values(
                cur, _upsert_sql(data_cols), argslist,
                page_size=UPSERT_PAGE_SIZE, fetch=True,
            )
            count += len(returned)
        conn.commit()
    _record_upsert(len(groups), count, time.perf_counter() - started)
    return count


def fetch_by_zip(conn, zip_code: str, account_id: int) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT * FROM properties WHERE zip = %s AND account_id = %s",
            (zip_code, account_id),
        )
        return [dict(r) for r in cur.fetchall()]


def fetch_missing_field(conn, field: str, account_id: int, zip_code: str | None = None,
                        selected_only: bool = False) -> list[dict]:
    """Return this org's properties where a given field is NULL.

    When `selected_only` is True, restrict to rows the selection step picked for
    paid enrichment (enrichment_selected = TRUE). Used by capped/radius runs.
    """
    if field not in ALL_COLS:
        raise ValueError(f"Unknown field: {field}")
    # Every caller of the fetch_missing_* pair is a paid, address-keyed vendor
    # lookup (RentCast, skip-trace, demographics). A parcel with no situs
    # address — HCAD stamps those with a zero house number, "0 TRUXTON ST" —
    # can never be matched by any of them, so it never earns a call.
    where = f"WHERE {field} IS NULL AND account_id = %s AND {sql_has_situs('address')}"
    params = [account_id]
    if zip_code:
        where += " AND zip = %s"
        params.append(zip_code)
    if selected_only:
        where += " AND enrichment_selected = TRUE"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM properties {where}", params)
        return [dict(r) for r in cur.fetchall()]


def fetch_missing_any(conn, fields: list[str], account_id: int, zip_code: str | None = None,
                      selected_only: bool = False, checked_flag: str | None = None,
                      recheck_days: int | None = None,
                      limit: int | None = None) -> list[dict]:
    """Return this org's properties where AT LEAST ONE of `fields` is NULL.

    Column names are validated against ALL_COLS before interpolation, so this is
    safe despite building SQL from `fields`.

    When `selected_only` is True, restrict to rows the selection step picked for
    paid enrichment (enrichment_selected = TRUE). Used by capped/radius runs.

    `checked_flag` names an enrichment_flags key holding the ISO date a paid
    source was last asked about this row; rows carrying one newer than
    `recheck_days` are excluded. Without it a "gap" the source structurally
    cannot fill — last_sale_price in non-disclosure states like Texas, say —
    keeps every row eligible on every run, so the whole ZIP is re-billed forever.
    Dates are stored and compared as YYYY-MM-DD text, which sorts chronologically
    and avoids a timestamp cast that a malformed value could fail on.

    `limit` caps the result in SQL, ordered so a capped, paid run spends its
    budget where a vendor is likeliest to answer: rows with evidence of a
    building (year_built or square_footage on file) first, emptiest rows first
    within each class. The ordering only matters when the result is being
    truncated, so it is applied only alongside a limit, leaving unlimited
    callers' plans untouched. Without it an account-wide caller would pull its
    entire book into memory to throw most of it away.

    Rows whose address has no situs (zero house number — vacant land, easements)
    are excluded outright: no address-keyed vendor can answer for them, at any
    budget.
    """
    bad = [f for f in fields if f not in ALL_COLS]
    if bad:
        raise ValueError(f"Unknown field(s): {bad}")
    if not fields:
        return []
    clause = " OR ".join(f"{f} IS NULL" for f in fields)
    # No-situs parcels never earn a paid call — see fetch_missing_field.
    where = f"WHERE ({clause}) AND account_id = %s AND {sql_has_situs('address')}"
    params: list = [account_id]
    if zip_code:
        where += " AND zip = %s"
        params.append(zip_code)
    if selected_only:
        where += " AND enrichment_selected = TRUE"
    if checked_flag:
        if recheck_days and recheck_days > 0:
            where += (" AND (enrichment_flags->>%s IS NULL"
                      "      OR enrichment_flags->>%s"
                      "         < to_char(NOW() - make_interval(days => %s), 'YYYY-MM-DD'))")
            params.extend([checked_flag, checked_flag, recheck_days])
        else:
            where += " AND enrichment_flags->>%s IS NULL"
            params.append(checked_flag)
    order = ""
    if limit is not None:
        # Confirmed structures first: on a county-seeded book the rows with the
        # most NULLs are disproportionately vacant lots and new construction no
        # vendor has a record of, so pure emptiest-first spends a capped budget
        # on the least-matchable rows. Evidence of a building (a year built or
        # a square footage on file) is the best available predictor that the
        # paid lookup will actually answer; within each class, emptiest first
        # still buys the most data per call.
        gaps = " + ".join(f"({f} IS NULL)::int" for f in fields)
        order = (" ORDER BY (year_built IS NOT NULL OR square_footage IS NOT NULL) DESC,"
                 f" ({gaps}) DESC, id LIMIT %s")
        params.append(limit)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM properties {where}{order}", params)
        return [dict(r) for r in cur.fetchall()]
