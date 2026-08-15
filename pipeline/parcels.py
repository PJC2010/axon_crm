"""
Shared parcel cache — the tenant-independent half of a property.

`properties` is per-tenant (uniqueness is (account_id, address, zip)), so every
account gets its own copy of a parcel and, until now, re-ran the entire
enrichment pipeline for a ZIP another account might already have enriched. On
ZIP 77449 (41,334 parcels) the seed step alone measured 8m58s, spent pulling rows
out of hcad_properties into Python and writing them straight back into the same
database.

Everything here runs server-side. No parcel data crosses the wire: seeding a
tenant is INSERT ... SELECT, and the enrichment fan-out is UPDATE ... FROM.

The four operations, and the direction data moves:

    ensure_from_hcad(zip)          hcad_properties ──► parcels     (build cache)
    seed_account(zip, account)     parcels ──► properties          (seed tenant)
    promote(zip, account)          properties ──► parcels          (share findings)
    sync(zip, account)             parcels ──► properties          (adopt findings)

`promote` is what makes the cache compound: once one account has geocoded a ZIP,
those coordinates go back into `parcels`, and every later account picks them up
through `seed_account`/`sync` without a single API call.

Only free, tenant-independent facts move. Skip-traced contacts and the
demographic append are per-account purchases that providers do not permit
redistributing, and CRM state (status, assignment, score) is tenant opinion —
neither is ever promoted. SHARED_COLS below is the allowlist that enforces it.
"""
import logging

from pipeline.addr import sql_has_situs
from pipeline.owner import sql_clean_owner_name
from pipeline.parcel_id import sql_normalize_apn

log = logging.getLogger(__name__)


# Columns that exist on BOTH parcels and properties and describe the parcel
# itself rather than a tenant's relationship to it. This list is the security
# boundary for promote(): anything absent never leaves a tenant's rows.
SHARED_COLS = [
    "city", "state",
    "latitude", "longitude", "geohash", "h3_r8",
    "geocode_source", "geocode_confidence",
    "parcel_apn",
    "year_built", "square_footage", "lot_size", "property_type", "state_class",
    "garage_spaces", "garage_type", "has_pool", "has_cracked_slab",
    "roof_type", "foundation_type", "heating_type", "cooling_type",
    "estimated_value", "estimated_equity",
    "last_sale_date", "last_sale_price",
    "owner_name", "owner_type", "owner_occupied", "ownership_years",
    "mailing_address",
    "hcad_neighborhood_code", "hcad_neighborhood_name", "subdivision",
    "zip_median_income", "permit_count_24mo",
    "last_storm_date", "last_storm_type", "hail_size_in", "storm_count_24mo",
]

# Never shareable, listed explicitly so the reason is greppable from here.
#   contact_name/phone/email  — the tenant paid a skip-trace provider for these
#   owner_age, est_household_income, life_stage, ... — paid demographic append
#   status, assigned_to, lead_score, vertical, notes — tenant CRM state
_NEVER_SHARED = frozenset({
    "contact_name", "contact_phone", "contact_email",
    "owner_age", "length_of_residence_years", "est_household_income", "life_stage",
    "status", "assigned_to", "lead_source", "vertical", "lead_score",
    "score_grade", "score_updated_at", "estimated_job_value", "archived_at",
})

assert not (set(SHARED_COLS) & _NEVER_SHARED), "shared/never-shared overlap"

# Confidence stamped on centroid-sourced coordinates. A parcel centroid is the
# actual parcel geometry, so it outranks the Census batch's street-interpolated
# "Exact" match (0.9 — pipeline/geocode_batch.py) without claiming rooftop truth.
CENTROID_CONFIDENCE = 0.95


def ensure_from_hcad(conn, zip_code: str) -> int:
    """Populate `parcels` for a ZIP from the free HCAD mirror. Idempotent.

    Existing rows are gap-filled, never overwritten: COALESCE keeps whatever the
    cache already knows (e.g. coordinates promoted by an earlier account) and
    only supplies what is still NULL.

    Returns the number of parcel rows inserted or updated.
    """
    with conn.cursor() as cur:
        cur.execute(
            f"""
            INSERT INTO parcels (
                address, zip, city, state, parcel_apn,
                year_built, square_footage, lot_size, estimated_value,
                last_sale_date, owner_name, owner_occupied, mailing_address,
                state_class,
                hcad_neighborhood_code, hcad_neighborhood_name,
                enrichment_flags, enriched_at
            )
            SELECT
                h.site_address,
                h.site_zip,
                h.mail_city,
                'TX',
                -- Storage form of pipeline/parcel_id.py::normalize_apn:
                -- alphanumerics only, uppercased, and — load-bearing — NULL for
                -- empty and ALL-ZERO placeholders. A zero-filled acct stored
                -- here would be copied to every tenant, then read as a real
                -- identity: spurious parcel_mismatch findings on every RentCast
                -- answer, and (being non-NULL) it would block the genuine
                -- assessorID from ever filling. Cross-vendor comparisons still
                -- go through same_parcel in Python, but this stored form IS a
                -- join key within HCAD's own data: the same expression writes
                -- hcad_parcel_centroids.acct, which is what lets
                -- fill_coords_from_centroids join on plain equality.
                {sql_normalize_apn("h.acct")},
                NULLIF(h.year_built, '')::INTEGER,
                h.building_sqft,
                h.land_sqft,
                h.tot_appr_val,
                h.last_sale_date,
                {sql_clean_owner_name("h.owner_name")},
                h.likely_owner_occupied,
                NULLIF(CONCAT_WS(', ',
                    NULLIF(TRIM(h.mail_addr), ''),
                    NULLIF(TRIM(h.mail_city), ''),
                    NULLIF(TRIM(CONCAT_WS(' ', NULLIF(TRIM(h.mail_state), ''),
                                               NULLIF(TRIM(h.mail_zip), ''))), '')
                ), ''),
                h.state_class,
                h.neighborhood_code,
                h.neighborhood_name,
                jsonb_build_object('seed', 'hcad'),
                NOW()
            FROM (
                -- HCAD keeps one row per account, and several accounts can share
                -- a site address (condo units, split parcels, duplicate records).
                -- Feeding both to ON CONFLICT DO UPDATE raises "cannot affect row
                -- a second time", so collapse to one row per parcel identity
                -- first, preferring the most-valued then lowest acct so the pick
                -- is deterministic across runs.
                SELECT DISTINCT ON (axon_normalize_address(site_address), site_zip) *
                FROM hcad_properties
                WHERE site_zip = %s
                  AND site_address IS NOT NULL
                  AND axon_normalize_address(site_address) <> ''
                ORDER BY axon_normalize_address(site_address), site_zip,
                         tot_appr_val DESC NULLS LAST, acct
            ) h
            ON CONFLICT (address_norm, zip) DO UPDATE SET
                city                   = COALESCE(parcels.city, EXCLUDED.city),
                state                  = COALESCE(parcels.state, EXCLUDED.state),
                parcel_apn             = COALESCE(parcels.parcel_apn, EXCLUDED.parcel_apn),
                year_built             = COALESCE(parcels.year_built, EXCLUDED.year_built),
                square_footage         = COALESCE(parcels.square_footage, EXCLUDED.square_footage),
                lot_size               = COALESCE(parcels.lot_size, EXCLUDED.lot_size),
                estimated_value        = COALESCE(parcels.estimated_value, EXCLUDED.estimated_value),
                last_sale_date         = COALESCE(parcels.last_sale_date, EXCLUDED.last_sale_date),
                owner_name             = COALESCE(parcels.owner_name, EXCLUDED.owner_name),
                owner_occupied         = COALESCE(parcels.owner_occupied, EXCLUDED.owner_occupied),
                mailing_address        = COALESCE(parcels.mailing_address, EXCLUDED.mailing_address),
                state_class            = COALESCE(parcels.state_class, EXCLUDED.state_class),
                hcad_neighborhood_code = COALESCE(parcels.hcad_neighborhood_code, EXCLUDED.hcad_neighborhood_code),
                hcad_neighborhood_name = COALESCE(parcels.hcad_neighborhood_name, EXCLUDED.hcad_neighborhood_name),
                enrichment_flags       = parcels.enrichment_flags || EXCLUDED.enrichment_flags,
                enriched_at            = NOW()
            """,
            (zip_code,),
        )
        n = cur.rowcount
    conn.commit()
    log.info("parcels: %d cached for ZIP %s from HCAD", n, zip_code)
    return n


def fill_coords_from_centroids(conn, zip_code: str) -> int:
    """Fill missing coordinates for a ZIP's parcels from the county centroid
    mirror (hcad_parcel_centroids, migration 0070). Free, idempotent, fill-only.

    This is the "shared geocode pass" that idx_parcels_zip_ungeocoded
    (migration 0065) was built for, and its first consumer. Both join sides are
    stored pre-normalized by pipeline/parcel_id.py::sql_normalize_apn, so plain
    equality is exact — no expression runs at join time. A row that already has
    coordinates (promoted from a tenant's geocode) is never touched.

    geohash/h3 stay NULL here deliberately: tenants backfill both from lat/lng
    (pipeline/neighborhood.py::backfill_geohashes,
    pipeline/geo_cluster_store.py::backfill_h3) and promote() carries them back
    into the cache — the compounding path this module already runs on.

    Returns the number of parcels that gained coordinates.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE parcels p SET
                latitude           = c.latitude,
                longitude          = c.longitude,
                geocode_source     = 'hcad_centroid',
                geocode_confidence = %s,
                enrichment_flags   = p.enrichment_flags
                                     || jsonb_build_object('geocode', 'hcad_centroid'),
                enriched_at        = NOW()
            FROM hcad_parcel_centroids c
            WHERE p.zip = %s
              AND p.latitude IS NULL
              AND p.parcel_apn = c.acct
            """,
            (CENTROID_CONFIDENCE, zip_code),
        )
        n = cur.rowcount
    conn.commit()
    log.info("parcels: %d coords filled from centroids for ZIP %s", n, zip_code)
    return n


def seed_account(conn, zip_code: str, account_id: int, limit: int | None = None,
                 owner_occupied_only: bool = False,
                 built_only: bool = False,
                 residential_only: bool = False) -> int:
    """Create this account's `properties` rows for a ZIP straight from `parcels`.

    The whole seed is one statement: no parcel data is read into Python. An
    account that already holds some of the ZIP gets only the gaps filled, and
    its own edits are never overwritten (COALESCE keeps the tenant's value).

    `limit` caps how many of the ZIP's parcels this tenant takes — the shared
    cache itself is always built in full, since a partial cache would make later
    accounts think the ZIP was already covered. A capped seed takes parcels with
    a real street address first (see the ordering below); without that it took
    HCAD's no-situs parcels and nothing else.

    `owner_occupied_only` / `built_only` / `residential_only` narrow what this
    tenant materializes (home-services accounts want owner-occupied homes with a
    structure) while the full county cache stays available to others
    (tax-delinquent/investor angles). All default off — existing callers are
    unchanged.

    `residential_only` is the one wired to a caller: the county roll is every
    parcel, not every house, so an unfiltered ZIP seed takes the shopping
    centres and school-district land with it. See pipeline/residential.py.

    Returns rows inserted or updated.
    """
    # Literal SQL, no bind params, so the parameter shape is identical when the
    # filters are off. This matters: psycopg2 binds %s positionally by statement
    # text order, and filter_sql is interpolated ahead of the claim/INSERT
    # params — a bind param added here would silently shift all of them.
    filter_sql = ""
    if owner_occupied_only:
        filter_sql += "\n                  AND p.owner_occupied IS TRUE"
    if built_only:
        # HCAD writes vacant-lot building_sqft as 0, so > 0 rather than
        # IS NOT NULL — the same confirmed-structure rule as pipeline/db.py's
        # paid-candidate ordering.
        filter_sql += ("\n                  AND (COALESCE(p.year_built, 0) > 0"
                       " OR COALESCE(p.square_footage, 0) > 0)")
    if residential_only:
        # Same rule the audit and the bulk archive apply to rows already
        # materialized, so what a seed refuses and what a cleanup removes can
        # never drift apart. Imported here rather than at module scope because
        # residential imports config, and parcels is imported during startup
        # checks before the environment is necessarily complete.
        from pipeline.residential import sql_non_residential
        filter_sql += (f"\n                  AND NOT "
                       f"{sql_non_residential('p.')}")

    shared = ", ".join(SHARED_COLS)
    params: list = [zip_code, account_id]
    limit_sql = ""
    if limit and limit > 0:
        # Deterministic so a repeated capped run takes the same parcels.
        limit_sql = "LIMIT %s"
        params.append(limit)

    # Real street addresses first. Ordering by address_norm alone sorted HCAD's
    # no-situs parcels — vacant land and easements, which it addresses with a
    # zero house number — to the very top ("0 ACKLEY DR" < "1 …"), so a capped
    # seed took nothing else: a 50-parcel seed of ZIP 77024 bought 50 parcels
    # no vendor can enrich and nobody lives at, out of 12,403 available. The
    # tiebreak stays address_norm, so a repeated capped run still takes the
    # same set.
    order_sql = f"ORDER BY {sql_has_situs('p.address')} DESC, p.address_norm"
    params.extend([account_id, account_id])

    with conn.cursor() as cur:
        cur.execute(
            f"""
            WITH new_parcels AS (
                -- Only parcels this account does not already hold. Selecting
                -- these up front (rather than leaning on ON CONFLICT) means a
                -- re-seed inserts nothing and burns no customer numbers.
                SELECT p.*
                FROM parcels p
                WHERE p.zip = %s
                  AND NOT EXISTS (
                      SELECT 1 FROM properties x
                      WHERE x.account_id = %s AND x.address = p.address AND x.zip = p.zip
                  ){filter_sql}
                {order_sql}
                {limit_sql}
            ),
            numbered AS (
                SELECT np.*, ROW_NUMBER() OVER (ORDER BY np.address_norm) - 1 AS offset_n
                FROM new_parcels np
            ),
            counted AS (SELECT COUNT(*) AS n FROM numbered),
            claim AS (
                -- Claim the whole block of customer numbers in ONE update.
                -- properties has a BEFORE INSERT trigger (assign_account_number,
                -- migration 0054) that otherwise runs this same UPDATE once per
                -- row: 41,334 serialized updates to a single accounts row inside
                -- one transaction, each leaving a tuple version the subsequent
                -- FK checks must walk. Measured on a 41,334-row seed that was
                -- 16.3s in the trigger plus 29.3s in properties_account_id_fkey.
                -- Supplying account_number here makes the trigger a no-op.
                UPDATE accounts a
                   SET next_customer_no = a.next_customer_no + counted.n
                  FROM counted
                 WHERE a.id = %s
             RETURNING a.next_customer_no - counted.n AS start
            )
            INSERT INTO properties (account_id, address, zip, parcel_id,
                                    account_number, {shared}, enrichment_flags)
            SELECT %s, n.address, n.zip, n.id,
                   -- Same format the trigger produces: min width 5, widening
                   -- rather than truncating for longer numbers.
                   'C-' || LPAD((claim.start + n.offset_n)::TEXT,
                                GREATEST(5, LENGTH((claim.start + n.offset_n)::TEXT)), '0'),
                   {", ".join("n." + c for c in SHARED_COLS)},
                   n.enrichment_flags
            FROM numbered n, claim
            """,
            params,
        )
        # rowcount is exact for a single INSERT statement (unlike execute_values,
        # which pages and reports only the last page). Measured on 41,334 rows,
        # adding RETURNING 1 and materializing the result cost 19s of 43s — 41k
        # rows shipped back only to be counted and discarded.
        inserted = cur.rowcount
    conn.commit()

    # Rows this account already had are refreshed from the cache separately,
    # which is a plain UPDATE and involves neither the trigger nor a number.
    updated = sync(conn, zip_code, account_id)
    log.info("parcels: seeded %d new + refreshed %d existing properties for "
             "account %s in ZIP %s", inserted, updated, account_id, zip_code)
    return inserted


def promote(conn, zip_code: str, account_id: int) -> int:
    """Push tenant-independent facts this account has learned back into `parcels`.

    This is what makes the cache compound: coordinates one account paid to
    geocode, or storm matches it computed, become free for every later account.
    Only fills gaps in the cache — a parcel value already set is left alone, so
    one account's data can never overwrite another's.

    Restricted to SHARED_COLS, so paid contact/demographic data and CRM state
    are structurally incapable of leaking between tenants.
    """
    sets = ",\n                ".join(
        f"{c} = COALESCE(pc.{c}, src.{c})" for c in SHARED_COLS
    )
    cols = ", ".join(f"p.{c}" for c in SHARED_COLS)
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE parcels pc SET
                {sets},
                enriched_at = NOW()
            FROM (
                SELECT p.parcel_id, {cols}
                FROM properties p
                WHERE p.zip = %s AND p.account_id = %s AND p.parcel_id IS NOT NULL
            ) AS src
            WHERE pc.id = src.parcel_id
            """,
            (zip_code, account_id),
        )
        n = cur.rowcount
    conn.commit()
    log.info("parcels: promoted findings from %d properties in ZIP %s", n, zip_code)
    return n


def sync(conn, zip_code: str, account_id: int) -> int:
    """Pull cached parcel facts down into this account's rows, filling gaps only.

    Lets an account adopt enrichment another account paid for (or that a later
    HCAD refresh added) without re-running any step. Never overwrites a value the
    tenant already has.
    """
    sets = ",\n                ".join(
        f"{c} = COALESCE(p.{c}, pc.{c})" for c in SHARED_COLS
    )
    with conn.cursor() as cur:
        cur.execute(
            f"""
            UPDATE properties p SET
                {sets}
            FROM parcels pc
            WHERE p.parcel_id = pc.id
              AND p.zip = %s AND p.account_id = %s
            """,
            (zip_code, account_id),
        )
        n = cur.rowcount
    conn.commit()
    log.info("parcels: synced %d properties in ZIP %s for account %s",
             n, zip_code, account_id)
    return n


def link_existing(conn, zip_code: str, account_id: int) -> int:
    """Attach parcel_id to this account's rows that predate the cache.

    Matches on the normalized address, so it is unaffected by punctuation and
    spacing differences between the sources.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE properties p SET parcel_id = pc.id
            FROM parcels pc
            WHERE p.parcel_id IS NULL
              AND p.zip = pc.zip
              AND axon_normalize_address(p.address) = pc.address_norm
              AND p.zip = %s AND p.account_id = %s
            """,
            (zip_code, account_id),
        )
        n = cur.rowcount
    conn.commit()
    if n:
        log.info("parcels: linked %d pre-existing properties in ZIP %s", n, zip_code)
    return n


def coverage(conn, zip_code: str) -> dict:
    """How much of a ZIP the shared cache already knows — used to report whether
    a seed will be free."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*), COUNT(latitude), COUNT(year_built), COUNT(estimated_value) "
            "FROM parcels WHERE zip = %s",
            (zip_code,),
        )
        total, geocoded, built, valued = cur.fetchone()
    return {"parcels": total, "geocoded": geocoded,
            "year_built": built, "estimated_value": valued}
