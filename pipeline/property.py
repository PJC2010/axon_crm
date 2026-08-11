"""
Step — Property detail enrichment via RentCast.

Free HCAD runs upstream and fills what it can. This step then fills the
remaining NULL holes from the paid source(s) in PROPERTY_FIELD_SOURCES.

Fill-only, enforced here: fields the row already has are dropped from each
update before it is written. upsert_properties skips None but *overwrites* any
non-None value it is handed (SET col = EXCLUDED.col), so without this filter a
row queued for one gap would get every other field it already held — including
HCAD's assessor facts — replaced by the vendor's copy. Overwriting stays where
it belongs: the opt-in refresh mode of the account-wide sweep
(pipeline/backfill.py).
"""
import logging
import time
from datetime import date

from config import (
    RENTCAST_API_KEY, RENTCAST_BASE_URL,
    PROPERTY_FIELD_SOURCES, SOURCE_FIELDS, PROPERTY_RECHECK_DAYS,
)
from pipeline.backfill import record_findings
from pipeline.db import get_conn, fetch_missing_any, upsert_properties
from pipeline.http import get_json_result
from pipeline.reconcile import map_detail, parcel_finding, verify_record

log = logging.getLogger(__name__)

# Per-source detail fetchers and the metadata each one needs.
_SOURCE_CONFIG = {
    "rentcast": {
        "key": RENTCAST_API_KEY,
        "flag": {"property": "rentcast"},
        "delay": 0.05,
        "cap": None,
    },
}


def enrich_property(zip_code: str, account_id: int, selected_only: bool = False) -> dict:
    """Run each configured source in priority order.

    When `selected_only` is True (capped/radius runs), only rows the selection
    step marked enrichment_selected = TRUE are enriched, keeping paid calls
    bounded to the chosen subset.

    Returns per-source counters: {source: {"ok", "fail", "unanswered",
    "updated", "parcel_mismatch", "skipped_no_key"}}. `fail` is "the source
    answered but had no record"; `unanswered` is "the lookup never got through"
    — those rows are left unstamped so a vendor outage does not disqualify them
    from the next run. `parcel_mismatch` counts accepted records whose
    assessorID disagreed with the row's stored parcel number (shadow-recorded,
    not rejected — see pipeline/reconcile.py::parcel_finding).
    """
    conn = get_conn()
    counters: dict[str, dict] = {}
    fetchers = {"rentcast": _rentcast_detail}

    try:
        for source in PROPERTY_FIELD_SOURCES:
            cfg = _SOURCE_CONFIG[source]
            counter = {"ok": 0, "fail": 0, "unanswered": 0, "updated": 0,
                       "parcel_mismatch": 0, "skipped_no_key": False}
            counters[source] = counter

            if not cfg["key"]:
                counter["skipped_no_key"] = True
                log.warning("%s key not set — skipping %s property enrichment.",
                            source.upper(), source)
                continue

            checked_flag = f"{source}_checked"
            rows = fetch_missing_any(conn, SOURCE_FIELDS[source], account_id, zip_code,
                                     selected_only=selected_only,
                                     checked_flag=checked_flag,
                                     recheck_days=PROPERTY_RECHECK_DAYS)
            if cfg["cap"]:
                rows = rows[: cfg["cap"]]
            if not rows:
                log.info("%s: no properties due for enrichment.", source)
                continue

            log.info("%s enriching %d properties…", source, len(rows))
            today = date.today().isoformat()
            updates = []
            findings: list[tuple[int, dict]] = []
            for row in rows:
                data, answered = fetchers[source](row["address"], row.get("zip", ""))
                if not answered:
                    # The lookup never got through (timeout, outage). Leave the
                    # row unstamped so it stays eligible — stamping here would
                    # let one vendor outage disqualify the batch from being
                    # retried for PROPERTY_RECHECK_DAYS.
                    counter["unanswered"] += 1
                    time.sleep(cfg["delay"])
                    continue
                # Stamp every row the source answered for, match or not. Some
                # fields a source is queried for can never be filled — RentCast
                # has no sale price in non-disclosure states — so without this
                # marker the row stays "missing" and is re-billed forever.
                flags = {**cfg["flag"], checked_flag: today} if data else {checked_flag: today}
                update = {"address": row["address"], "zip": row["zip"],
                          "enrichment_flags": flags}
                if data:
                    counter["ok"] += 1
                    # The address echo check passed, but does the vendor's
                    # parcel number agree with the one HCAD gave this row?
                    # Recorded, not enforced — measure the false-accept rate
                    # before same_parcel becomes a gate.
                    finding = parcel_finding(row.get("parcel_apn"),
                                             data.get("parcel_apn"))
                    if finding:
                        counter["parcel_mismatch"] += 1
                        log.warning("%s assessorID %r disagrees with stored "
                                    "parcel %r for %r — recorded.",
                                    source, finding["remote"], finding["stored"],
                                    row["address"])
                        findings.append((row["id"], finding))
                    # Fill-only: drop what the row already has, so the paid
                    # source only ever lands in genuine gaps.
                    update.update({k: v for k, v in data.items()
                                   if row.get(k) is None})
                else:
                    counter["fail"] += 1
                updates.append(update)
                time.sleep(cfg["delay"])
            counter["updated"] = upsert_properties(conn, updates, account_id)
            record_findings(conn, account_id, findings)
    finally:
        conn.close()

    return counters


def _rentcast_detail(address: str, zip_code: str) -> tuple[dict | None, bool]:
    """Fetch one property and map it to the columns this step writes.

    Returns ``(data, answered)``. `answered` is False only when the lookup never
    got a response, which the caller needs in order to tell "RentCast has no
    record here" (stamp the row, stop asking) from "RentCast was unreachable"
    (leave it eligible). A fetcher added to `fetchers` must honour the same
    contract.

    The mapping lives in pipeline/reconcile.py so this step and the account-wide
    backfill sweep read a RentCast record the same way. `map_detail` returns
    more than SOURCE_FIELDS["rentcast"] queues rows for — subdivision,
    parcel_apn, roof/foundation/heating/cooling types, owner_type and the rest
    ride along on a call already being paid for without ever *triggering* one —
    but deliberately excludes coordinates, which belong to the geocode step
    (see reconcile.DETAIL_FIELDS).
    """
    data, answered = get_json_result(
        f"{RENTCAST_BASE_URL}/properties",
        headers={"X-Api-Key": RENTCAST_API_KEY},
        params={"address": address, "zipCode": zip_code, "limit": 1},
        timeout=15,
    )
    if not data:
        return None, answered
    record = data[0] if isinstance(data, list) else data

    # RentCast resolves the address string itself and `limit=1` hides any
    # ambiguity, so confirm it answered about the property we asked about before
    # writing a stranger's year built and owner onto this row.
    wrong = verify_record(record, address)
    if wrong:
        log.warning("RentCast answered %r for %r — record rejected.", wrong, address)
        return None, True

    return map_detail(record), True
