"""Shared database connection and upsert helper."""
import psycopg2
import psycopg2.extras
from config import DATABASE_URL


def get_conn():
    return psycopg2.connect(DATABASE_URL)


# Allowlist of writable columns. Used both as the upsert column set and to guard
# dynamic column references (e.g. fetch_missing_any) against SQL injection.
ALL_COLS = [
    "address", "city", "state", "zip", "latitude", "longitude", "geohash",
    "year_built", "square_footage", "garage_spaces", "garage_type", "lot_size",
    "property_type", "estimated_value", "estimated_equity",
    "last_sale_date", "last_sale_price", "owner_name", "owner_occupied",
    "ownership_years", "zip_median_income", "permit_count_24mo",
    "has_pool", "has_cracked_slab",
    "contact_name", "contact_phone", "contact_email",
    "lead_score", "score_grade", "vertical", "score_updated_at",
    "enrichment_flags",
]


def upsert_properties(conn, rows: list[dict]) -> int:
    """
    Upsert a list of property dicts into the properties table.
    Conflict target is (address, zip). Only non-None values are written so
    a partial enrichment step does not clobber fields set by an earlier step.
    Returns the number of rows affected.
    """
    if not rows:
        return 0

    all_cols = ALL_COLS

    with conn.cursor() as cur:
        count = 0
        for row in rows:
            cols = [c for c in all_cols if row.get(c) is not None]
            if not cols:
                continue
            values = [
                psycopg2.extras.Json(row[c]) if c == "enrichment_flags" and isinstance(row[c], dict) else row[c]
                for c in cols
            ]
            placeholders = ", ".join(["%s"] * len(cols))
            col_names = ", ".join(cols)
            updates = ", ".join(
                f"{c} = EXCLUDED.{c}" for c in cols
                if c not in ("address", "zip")
            )
            # Merge enrichment_flags rather than overwrite
            flags_merge = (
                "enrichment_flags = properties.enrichment_flags || EXCLUDED.enrichment_flags"
                if "enrichment_flags" in cols else ""
            )
            if flags_merge and updates:
                updates = updates.replace(
                    "enrichment_flags = EXCLUDED.enrichment_flags",
                    flags_merge,
                )
            sql = f"""
                INSERT INTO properties ({col_names})
                VALUES ({placeholders})
                ON CONFLICT (address, zip) DO UPDATE SET {updates}
            """
            cur.execute(sql, values)
            count += cur.rowcount
        conn.commit()
    return count


def fetch_by_zip(conn, zip_code: str) -> list[dict]:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM properties WHERE zip = %s", (zip_code,))
        return [dict(r) for r in cur.fetchall()]


def fetch_missing_field(conn, field: str, zip_code: str | None = None,
                        selected_only: bool = False) -> list[dict]:
    """Return properties where a given field is NULL.

    When `selected_only` is True, restrict to rows the selection step picked for
    paid enrichment (enrichment_selected = TRUE). Used by capped/radius runs.
    """
    if field not in ALL_COLS:
        raise ValueError(f"Unknown field: {field}")
    where = f"WHERE {field} IS NULL"
    params = []
    if zip_code:
        where += " AND zip = %s"
        params.append(zip_code)
    if selected_only:
        where += " AND enrichment_selected = TRUE"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM properties {where}", params)
        return [dict(r) for r in cur.fetchall()]


def fetch_missing_any(conn, fields: list[str], zip_code: str | None = None,
                      selected_only: bool = False) -> list[dict]:
    """Return properties where AT LEAST ONE of `fields` is NULL.

    Column names are validated against ALL_COLS before interpolation, so this is
    safe despite building SQL from `fields`.

    When `selected_only` is True, restrict to rows the selection step picked for
    paid enrichment (enrichment_selected = TRUE). Used by capped/radius runs.
    """
    bad = [f for f in fields if f not in ALL_COLS]
    if bad:
        raise ValueError(f"Unknown field(s): {bad}")
    if not fields:
        return []
    clause = " OR ".join(f"{f} IS NULL" for f in fields)
    where = f"WHERE ({clause})"
    params = []
    if zip_code:
        where += " AND zip = %s"
        params.append(zip_code)
    if selected_only:
        where += " AND enrichment_selected = TRUE"
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(f"SELECT * FROM properties {where}", params)
        return [dict(r) for r in cur.fetchall()]
