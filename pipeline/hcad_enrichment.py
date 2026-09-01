"""
Step 4b — Harris County Appraisal District fallback enrichment.

Backfills null property fields using harris_county.duckdb when RentCast
returns nothing. Never overwrites a value that's already set.

Fields backfilled from property_summary (if null):
  year_built, square_footage, lot_size, estimated_value,
  last_sale_date, owner_name, owner_occupied, ownership_years, mailing_address

Fields backfilled from extra_features (always latest HCAD truth):
  has_pool, has_cracked_slab, garage_spaces (when still null)
"""
import logging
from datetime import date

from pipeline.backfill import record_findings
from pipeline.db import get_conn, fetch_by_zip, upsert_properties
from pipeline.equity import estimate_equity
from pipeline.parcel_id import normalize_apn
from pipeline.property_type import from_state_class as type_from_state_class
from pipeline.reconcile import parcel_finding
from pipeline import hcad_store

log = logging.getLogger(__name__)


def enrich_hcad(zip_code: str, account_id: int) -> int:
    hcad_map = hcad_store.query_properties(zip_code)
    ef_map   = hcad_store.query_extra_features(zip_code)

    if not hcad_map and not ef_map:
        log.info("[4b] HCAD: no data for ZIP %s", zip_code)
        return 0

    conn = get_conn()
    rows = fetch_by_zip(conn, zip_code, account_id)
    updates = []
    findings: list[tuple[int, dict]] = []
    mismatch_examples: list[str] = []

    for row in rows:
        addr_norm = hcad_store.normalize(row["address"])
        hcad = hcad_map.get(addr_norm)
        ef   = ef_map.get(addr_norm)

        if not hcad and not ef:
            continue

        if hcad:
            # The HCAD-direction half of shadow parcel verification: a row that
            # already carries a parcel number (e.g. RentCast's assessorID from
            # seeding) but address-matches an HCAD parcel with a different acct
            # is the same wrong-parcel signal the RentCast step measures, seen
            # from the other side. Recorded under source "hcad", never enforced.
            # Per-row lines are DEBUG — a roll-vintage change can disagree on
            # hundreds of addresses per ZIP, and at WARNING that drowned the
            # log; the summary after the loop carries the count.
            finding = parcel_finding(row.get("parcel_apn"),
                                     normalize_apn(hcad.get("parcel_apn")))
            if finding:
                log.debug("[4b] HCAD acct %r disagrees with stored parcel %r "
                          "for %r — recorded.", finding["remote"],
                          finding["stored"], row["address"])
                findings.append((row["id"], finding))
                if len(mismatch_examples) < 3:
                    mismatch_examples.append(row["address"])

        update: dict = {"address": row["address"], "zip": zip_code}
        changed = False

        def _backfill(our_field: str, val):
            nonlocal changed
            if row.get(our_field) is None and val is not None:
                update[our_field] = val
                changed = True

        if hcad:
            # The parcel number this address matched to — the identity the
            # RentCast step later verifies its assessorID against.
            _backfill("parcel_apn",              normalize_apn(hcad.get("parcel_apn")))
            # The situs city (site_addr_2, migration 0079). Fill-only, so rows
            # whose mailing-city-polluted value the 0079 repair NULLed pick up
            # the parcel's real city on their ZIP's next run.
            _backfill("city",                    hcad.get("site_city"))
            _backfill("year_built",              hcad.get("year_built"))
            _backfill("square_footage",          hcad.get("square_footage"))
            _backfill("lot_size",                hcad.get("lot_size"))
            _backfill("estimated_value",         hcad.get("estimated_value"))
            _backfill("last_sale_date",          hcad.get("last_sale_date"))
            _backfill("owner_name",              hcad.get("owner_name"))
            _backfill("owner_occupied",          hcad.get("owner_occupied"))
            _backfill("mailing_address",         hcad.get("mailing_address"))
            # The county's own residential/commercial category. Fills onto rows
            # that were seeded before migration 0072, so an existing book of
            # leads gains the class without being re-seeded.
            _backfill("state_class",             hcad.get("state_class"))
            # The dwelling type the county's class names. property_type is
            # otherwise written ONLY by RentCast, so this is the difference
            # between an HCAD-seeded book having the column and having it NULL
            # on every row. Fill-only like everything here: a type RentCast
            # already bought is never overwritten.
            _backfill("property_type",           type_from_state_class(hcad.get("state_class")))
            _backfill("hcad_neighborhood_code",  hcad.get("neighborhood_code"))
            _backfill("hcad_neighborhood_name",  hcad.get("neighborhood_name"))

            if row.get("ownership_years") is None:
                sale_date = update.get("last_sale_date") or hcad.get("last_sale_date")
                if isinstance(sale_date, date):
                    update["ownership_years"] = (date.today() - sale_date).days // 365
                    changed = True

            # Equity is otherwise only computed in the paid detail step, so an
            # HCAD-only run would leave the equity signal at 0. Derive it here
            # from the appraised value (TX is non-disclosure, so no sale price) —
            # estimate_equity falls back to value × EQUITY_FALLBACK_PCT.
            if row.get("estimated_equity") is None:
                value = update.get("estimated_value") or hcad.get("estimated_value")
                sale_date = update.get("last_sale_date") or hcad.get("last_sale_date")
                equity = estimate_equity(value, last_sale_date=sale_date)
                if equity is not None:
                    update["estimated_equity"] = equity
                    changed = True

        if ef:
            # Pool and cracked-slab are HCAD ground truth — always write them.
            if ef.get("has_pool"):
                update["has_pool"] = True
                changed = True
            if ef.get("has_cracked_slab"):
                update["has_cracked_slab"] = True
                changed = True
            # Only fill garage_spaces from HCAD if it isn't already set. HCAD
            # stores garage size in sqft; hcad_store converts it to a space count.
            garage_spaces = ef.get("garage_spaces") or 0
            if row.get("garage_spaces") is None and garage_spaces > 0:
                update["garage_spaces"] = garage_spaces
                changed = True

        if changed:
            update["enrichment_flags"] = {"hcad": "assessor"}
            updates.append(update)

    n = upsert_properties(conn, updates, account_id)
    record_findings(conn, account_id, findings, source="hcad")
    conn.close()
    if findings:
        log.warning("[4b] HCAD acct disagrees with the stored parcel_apn on "
                    "%d row(s) in ZIP %s — recorded to property_field_audits "
                    "(e.g. %s)", len(findings), zip_code,
                    ", ".join(repr(a) for a in mismatch_examples))
    log.info("[4b] HCAD: backfilled %d properties in ZIP %s", n, zip_code)
    return n
