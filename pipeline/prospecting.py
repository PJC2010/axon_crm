"""
Cluster-seeded prospecting (juncto geo layer, Phase 2, Section 5).

Flow: resolve a seed (cluster centroid, customer, or dropped pin) → pull a
radius of pre-geocoded, pre-enriched records from the property-data provider →
refine client-side on schema fields the vendor can't filter server-side → dedupe
against existing leads/customers → ingest as leads (geom populated,
geocode_source='rentcast', subdivision persisted) → score immediately.

Cost control: every pull is logged in prospect_pulls keyed by the seed's H3 cell;
a cell pulled within PROSPECT_SKIP_DAYS is skipped. The pure pieces (refine,
record mapping, dedupe matching) are unit-tested without a DB or network.
"""
import logging

import psycopg2.extras

from config import (
    CUSTOMER_STATUSES,
    PROSPECT_DEFAULT_RADIUS_M,
    PROSPECT_MAX_RECORDS,
    PROSPECT_SKIP_DAYS,
    PROSPECT_DEDUPE_M,
)
from pipeline import geo_h3
from pipeline.addr import normalize
from pipeline.geo_scoring import haversine_km
from pipeline.property_provider import get_provider
from pipeline.reconcile import map_record as map_rentcast_record

log = logging.getLogger(__name__)


# ── Seed resolution ───────────────────────────────────────────────────────────

def resolve_seed(conn, account_id: int, seed: dict) -> tuple[float, float, str] | None:
    """Resolve a seed to (lat, lng, seed_type).

    `seed` is one of: {"cluster_id": N}, {"customer_id": N}, or
    {"lat": .., "lng": ..} (a user-dropped pin). Cluster/customer lookups are
    account-scoped. Returns None when the seed can't be resolved.
    """
    if seed.get("lat") is not None and seed.get("lng") is not None:
        return float(seed["lat"]), float(seed["lng"]), "point"

    if seed.get("cluster_id") is not None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT centroid_lat, centroid_lng FROM customer_clusters "
                "WHERE cluster_label = %s AND account_id = %s",
                (seed["cluster_id"], account_id),
            )
            row = cur.fetchone()
        if row and row[0] is not None and row[1] is not None:
            return float(row[0]), float(row[1]), "cluster"
        return None

    if seed.get("customer_id") is not None:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT latitude, longitude FROM properties WHERE id = %s AND account_id = %s",
                (seed["customer_id"], account_id),
            )
            row = cur.fetchone()
        if row and row[0] is not None and row[1] is not None:
            return float(row[0]), float(row[1]), "customer"
        return None

    return None


# ── Cost control ──────────────────────────────────────────────────────────────

def recently_pulled(conn, account_id: int, h3_cell: str | None,
                    days: int = PROSPECT_SKIP_DAYS) -> bool:
    """True if this account already pulled the seed's H3 cell within `days`.
    Never skips when the cell is unknown (h3 not installed) — better to allow the
    pull than to silently do nothing."""
    if not h3_cell:
        return False
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM prospect_pulls "
            "WHERE account_id = %s AND h3_r8 = %s "
            "  AND pulled_at >= NOW() - (%s * INTERVAL '1 day') LIMIT 1",
            (account_id, h3_cell, days),
        )
        return cur.fetchone() is not None


# ── Client-side refinement ────────────────────────────────────────────────────

def _parse_range(spec) -> tuple[float | None, float | None]:
    """Parse a "min:max" preset value (either side optional) into (min, max)."""
    if spec is None:
        return None, None
    if isinstance(spec, (list, tuple)) and len(spec) == 2:
        lo, hi = spec
        return (float(lo) if lo not in (None, "") else None,
                float(hi) if hi not in (None, "") else None)
    lo, _, hi = str(spec).partition(":")
    return (float(lo) if lo else None, float(hi) if hi else None)


def _in_range(value, spec) -> bool:
    if value is None:
        return False
    lo, hi = _parse_range(spec)
    if lo is not None and value < lo:
        return False
    if hi is not None and value > hi:
        return False
    return True


def refine(records: list[dict], preset: dict | None) -> list[dict]:
    """Filter vendor records on fields not queryable server-side (Section 5 step 3):
    lotSize / yearBuilt ranges, ownerOccupied (absentee targeting), features.pool,
    and hoa.fee presence. An absent preset key means "don't filter on it"."""
    if not preset:
        return records
    out = []
    for r in records:
        features = r.get("features") or {}
        if "propertyType" in preset and r.get("propertyType") != preset["propertyType"]:
            continue
        if "lotSize" in preset and not _in_range(r.get("lotSize") or features.get("lotSize"), preset["lotSize"]):
            continue
        if "yearBuilt" in preset and not _in_range(r.get("yearBuilt"), preset["yearBuilt"]):
            continue
        if "ownerOccupied" in preset and bool(r.get("ownerOccupied")) != bool(preset["ownerOccupied"]):
            continue
        if "pool" in preset and bool(features.get("pool")) != bool(preset["pool"]):
            continue
        if preset.get("hoa") and not ((r.get("hoa") or {}).get("fee")):
            continue
        out.append(r)
    return out


# ── Record mapping ────────────────────────────────────────────────────────────

def map_record(r: dict, vertical: str | None) -> dict:
    """Map a RentCast record to the upsert_properties row shape.

    Field extraction is delegated to reconcile.map_record — the one canonical
    RentCast-record → properties-column mapping — so a prospected record is
    read exactly like a seeded or detail-fetched one (taxAssessments →
    estimated_value, assessorID → parcel_apn, nested owner/features shapes).
    Reading everything off the record we already paid for is what keeps a
    prospect from immediately re-queueing for a second paid lookup. This layer
    adds row identity plus prospecting provenance (vertical, lead_source).
    Records arrive pre-geocoded, so geocode_source='rentcast'.
    """
    row = map_rentcast_record(r)
    if row["latitude"] is not None and row["longitude"] is not None:
        row["geocode_source"] = "rentcast"
    row.update({
        "address":          r.get("addressLine1") or r.get("formattedAddress") or "",
        "zip":              r.get("zipCode"),
        "vertical":         vertical,
        "lead_source":      "prospecting",
        "enrichment_flags": {"seed": "rentcast", "source": "prospecting"},
    })
    return row


# ── Dedupe ────────────────────────────────────────────────────────────────────

def _load_existing(conn, account_id: int) -> tuple[set[str], list[tuple[float, float]]]:
    """Existing properties for the account: normalized addresses + coordinates,
    for address-first / geometry-fallback dedupe."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT address, latitude, longitude FROM properties WHERE account_id = %s",
            (account_id,),
        )
        rows = cur.fetchall()
    addrs = {normalize(a) for a, _, _ in rows if a}
    coords = [(lat, lng) for _, lat, lng in rows if lat is not None and lng is not None]
    return addrs, coords


def is_duplicate(row: dict, existing_addrs: set[str], existing_coords: list[tuple[float, float]],
                 dedupe_m: float = PROSPECT_DEDUPE_M) -> bool:
    """A record is a duplicate if its normalized address already exists, or (when
    addresses don't match) it sits within `dedupe_m` of an existing property."""
    if row.get("address") and normalize(row["address"]) in existing_addrs:
        return True
    lat, lng = row.get("latitude"), row.get("longitude")
    if lat is None or lng is None:
        return False
    dedupe_km = dedupe_m / 1000.0
    return any(haversine_km(lat, lng, elat, elng) <= dedupe_km for elat, elng in existing_coords)


def dedupe(rows: list[dict], existing_addrs: set[str],
           existing_coords: list[tuple[float, float]],
           dedupe_m: float = PROSPECT_DEDUPE_M) -> list[dict]:
    """Drop rows matching existing properties, and collapse duplicates within the
    pull itself (accumulating accepted rows into the comparison sets)."""
    addrs = set(existing_addrs)
    coords = list(existing_coords)
    kept = []
    for row in rows:
        if is_duplicate(row, addrs, coords, dedupe_m):
            continue
        kept.append(row)
        if row.get("address"):
            addrs.add(normalize(row["address"]))
        if row.get("latitude") is not None and row.get("longitude") is not None:
            coords.append((row["latitude"], row["longitude"]))
    return kept


# ── Orchestration ─────────────────────────────────────────────────────────────

def prospect(conn, account_id: int, seed: dict, *, radius_m: int | None = None,
             preset: dict | None = None, vertical: str | None = None,
             user_id: int | None = None, provider=None) -> dict:
    """Run the full Section 5 flow for one seed. Returns a summary dict; the caller
    owns the transaction. Skips (without an API call) when the seed's H3 cell was
    pulled recently."""
    from pipeline.db import upsert_properties
    from pipeline.geo_score_store import rescore_leads

    radius_m = radius_m or PROSPECT_DEFAULT_RADIUS_M
    resolved = resolve_seed(conn, account_id, seed)
    if not resolved:
        return {"status": "unresolved_seed"}
    lat, lng, seed_type = resolved

    h3_cell = geo_h3.to_cell(lat, lng)
    if recently_pulled(conn, account_id, h3_cell):
        return {"status": "skipped_recent_cell", "h3": h3_cell}

    provider = provider or get_provider()
    records, api_requests = provider.search_radius(
        lat, lng, radius_m, preset, max_records=PROSPECT_MAX_RECORDS
    )
    refined = refine(records, preset)
    rows = [map_record(r, vertical) for r in refined]

    existing_addrs, existing_coords = _load_existing(conn, account_id)
    fresh = dedupe(rows, existing_addrs, existing_coords)

    ingested = upsert_properties(conn, fresh, account_id) if fresh else 0

    # Which of the fresh rows actually landed, so we score exactly those.
    new_ids: list[int] = []
    if fresh:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM properties WHERE account_id = %s AND lead_source = 'prospecting' "
                "AND (address, zip) IN %s",
                (account_id, tuple((r["address"], r.get("zip")) for r in fresh)),
            )
            new_ids = [r[0] for r in cur.fetchall()]

    scored = rescore_leads(conn, account_id, property_ids=new_ids) if new_ids else 0

    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO prospect_pulls "
            "(account_id, h3_r8, center_lat, center_lng, radius_m, filters, "
            " records_returned, records_ingested, api_requests, seed_type, pulled_by) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (account_id, h3_cell, lat, lng, radius_m,
             psycopg2.extras.Json(preset or {}), len(records), ingested,
             api_requests, seed_type, user_id),
        )
    conn.commit()

    return {
        "status": "ok",
        "seed_type": seed_type,
        "center": [lng, lat],
        "h3": h3_cell,
        "records_returned": len(records),
        "after_refine": len(refined),
        "after_dedupe": len(fresh),
        "ingested": ingested,
        "scored": scored,
        "api_requests": api_requests,
    }
