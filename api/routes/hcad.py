"""
HCAD data management — upload county CSV data and query it from Postgres.

POST /api/hcad/upload     — upload properties + permits CSVs for a ZIP (platform admin)
GET  /api/hcad/status     — show loaded ZIPs and row counts
DELETE /api/hcad/{zip}    — remove county data for a ZIP (platform admin)

hcad_properties / hcad_permits are SHARED reference tables (no account_id):
they seed every tenant's pipeline and the shared parcels cache. Mutations are
therefore platform-admin-only — a tenant owner must not be able to wipe or
poison data every other tenant depends on. Status stays tenant-owner readable.
"""
import csv
import io
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from psycopg2.extensions import connection as PGConn

from api.deps import get_db, require_owner, require_platform_admin

log = logging.getLogger(__name__)
router = APIRouter()


@router.post("/hcad/upload")
async def upload_hcad(
    zip_code: str = Form(...),
    properties_csv: UploadFile = File(...),
    permits_csv: UploadFile = File(...),
    _: dict = Depends(require_platform_admin),
    db: PGConn = Depends(get_db),
):
    """Upload HCAD CSV exports for a single ZIP code."""
    # Load properties
    props_content = await properties_csv.read()
    props_reader = csv.DictReader(io.StringIO(props_content.decode("utf-8")))
    props_count = 0
    with db.cursor() as cur:
        # Clear old data for this ZIP
        cur.execute("DELETE FROM hcad_properties WHERE site_zip = %s", (zip_code,))
        for row in props_reader:
            cur.execute(
                """INSERT INTO hcad_properties
                   (acct, site_address, site_zip, year_built, building_sqft, land_sqft,
                    tot_appr_val, last_sale_date, owner_name, likely_owner_occupied,
                    mail_addr, mail_city, mail_state, mail_zip, state_class)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (acct) DO UPDATE SET
                     site_address = EXCLUDED.site_address,
                     site_zip = EXCLUDED.site_zip,
                     year_built = EXCLUDED.year_built,
                     building_sqft = EXCLUDED.building_sqft,
                     land_sqft = EXCLUDED.land_sqft,
                     tot_appr_val = EXCLUDED.tot_appr_val,
                     last_sale_date = EXCLUDED.last_sale_date,
                     owner_name = EXCLUDED.owner_name,
                     likely_owner_occupied = EXCLUDED.likely_owner_occupied,
                     mail_addr = EXCLUDED.mail_addr,
                     mail_city = EXCLUDED.mail_city,
                     mail_state = EXCLUDED.mail_state,
                     mail_zip = EXCLUDED.mail_zip,
                     -- Fill-only, for the one case that reaches this branch:
                     -- an acct whose site_zip changed between exports, so the
                     -- DELETE above (scoped to the uploaded ZIP) did not remove
                     -- it. Within a ZIP the DELETE runs first, so re-uploading a
                     -- pre-0072 CSV DOES clear state_class for that ZIP — rebuild
                     -- the DuckDB before re-uploading, or reload via
                     -- tools/load_hcad_to_postgres.py.
                     state_class = COALESCE(EXCLUDED.state_class, hcad_properties.state_class)
                """,
                (
                    row["acct"],
                    row.get("site_address"),
                    row.get("site_zip") or zip_code,
                    row.get("year_built") or None,
                    int(row["building_sqft"]) if row.get("building_sqft") else None,
                    int(row["land_sqft"]) if row.get("land_sqft") else None,
                    int(row["tot_appr_val"]) if row.get("tot_appr_val") else None,
                    row.get("last_sale_date") or None,
                    row.get("owner_name"),
                    row.get("likely_owner_occupied", "").lower() in ("true", "1", "t"),
                    row.get("mail_addr"),
                    row.get("mail_city"),
                    row.get("mail_state"),
                    row.get("mail_zip"),
                    row.get("state_class") or None,
                ),
            )
            props_count += 1

    # Load permits
    permits_content = await permits_csv.read()
    permits_reader = csv.DictReader(io.StringIO(permits_content.decode("utf-8")))
    permits_count = 0
    with db.cursor() as cur:
        # Get all accts for this ZIP to clean up old permits
        cur.execute("SELECT acct FROM hcad_properties WHERE site_zip = %s", (zip_code,))
        zip_accts = {row[0] for row in cur.fetchall()}
        if zip_accts:
            cur.execute(
                "DELETE FROM hcad_permits WHERE acct = ANY(%s)",
                (list(zip_accts),),
            )
        for row in permits_reader:
            cur.execute(
                """INSERT INTO hcad_permits
                   (acct, permit_id, status, issue_date, permit_type, description)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (acct, permit_id) DO NOTHING
                """,
                (
                    row["acct"],
                    int(row["permit_id"]) if row.get("permit_id") else None,
                    row.get("status"),
                    row.get("issue_date") or None,
                    row.get("permit_type"),
                    row.get("description"),
                ),
            )
            permits_count += 1

    db.commit()
    log.info("Uploaded HCAD data for ZIP %s: %d properties, %d permits", zip_code, props_count, permits_count)
    return {"zip": zip_code, "properties": props_count, "permits": permits_count}


@router.get("/hcad/status")
def hcad_status(_: dict = Depends(require_owner), db: PGConn = Depends(get_db)):
    """Show the active HCAD source and which ZIPs have data loaded."""
    from pipeline import hcad_store
    source = "duckdb" if hcad_store.db_exists() else (
        "postgres" if hcad_store.hcad_available() else "none"
    )
    with db.cursor() as cur:
        cur.execute("""
            SELECT site_zip, COUNT(*) AS properties,
                   (SELECT COUNT(*) FROM hcad_permits hp
                    WHERE hp.acct IN (SELECT acct FROM hcad_properties WHERE site_zip = hp2.site_zip))
            FROM hcad_properties hp2
            GROUP BY site_zip ORDER BY site_zip
        """)
        # Simpler query
        cur.execute("""
            SELECT hp.site_zip,
                   COUNT(DISTINCT hp.acct) AS properties,
                   COUNT(DISTINCT hm.permit_id) AS permits
            FROM hcad_properties hp
            LEFT JOIN hcad_permits hm ON hm.acct = hp.acct
            GROUP BY hp.site_zip
            ORDER BY hp.site_zip
        """)
        cols = [d[0] for d in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    return {"source": source, "zips": rows}


@router.delete("/hcad/{zip_code}", status_code=204)
def delete_hcad_zip(zip_code: str, _: dict = Depends(require_platform_admin), db: PGConn = Depends(get_db)):
    """Remove all HCAD data for a ZIP."""
    with db.cursor() as cur:
        cur.execute("SELECT acct FROM hcad_properties WHERE site_zip = %s", (zip_code,))
        accts = [row[0] for row in cur.fetchall()]
        if accts:
            cur.execute("DELETE FROM hcad_permits WHERE acct = ANY(%s)", (accts,))
        cur.execute("DELETE FROM hcad_properties WHERE site_zip = %s", (zip_code,))
    db.commit()
