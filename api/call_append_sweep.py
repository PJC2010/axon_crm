"""
Backfill sweep — reverse-append the callers the voice webhook couldn't.

api/routes/twilio_voice.py appends a caller's address inline, inside Twilio's
15s webhook window, with an 8s timeout and no retries. That budget is right for
keeping calls connecting but wrong for reliability: a slow provider, a transport
blip, or a number that arrived before PHONE_APPEND_PROVIDER was configured all
leave a missed-call lead with nothing but a phone number.

This sweep picks those up. It is a batch play — BatchData's Reverse Skip Trace
takes 100 numbers per request — so a whole backlog costs a handful of HTTP
calls instead of one per lead. Scheduled daily from api/scheduler.py.

Cost discipline, in keeping with the rest of the enrichment pipeline:
  - off by default: PHONE_APPEND_SWEEP_MAX=0 means "never spend", so deploying
    this file changes nobody's bill until an operator opts in
  - PHONE_APPEND_SWEEP_MAX caps lookups per run, PHONE_APPEND_SWEEP_DAYS bounds
    how far back it reaches
  - one candidate per (account, caller) — the newest missed call wins
  - enrichment_flags.phone_append is stamped after any completed attempt, so a
    no-match is never re-queried on the next run
"""
import logging

import psycopg2.extras

from config import (
    PHONE_APPEND_API_KEY, PHONE_APPEND_PROVIDER,
    PHONE_APPEND_SWEEP_DAYS, PHONE_APPEND_SWEEP_MAX,
)
from api.phone_append_logic import merge_append, merge_flags

log = logging.getLogger(__name__)

# Missed-call leads still lacking an address, never appended before, newest
# call per caller. Scoped per account: the same number calling two businesses
# is two independent leads, and each gets its own row updated.
_CANDIDATES_SQL = """
    SELECT DISTINCT ON (c.account_id, c.from_digits)
           c.account_id, c.from_digits, c.property_id,
           p.address, p.city, p.state, p.zip,
           p.contact_name, p.contact_email, p.enrichment_flags
    FROM calls c
    JOIN properties p
      ON p.id = c.property_id AND p.account_id = c.account_id
    WHERE c.outcome IN ('missed', 'busy')
      AND c.started_at >= NOW() - (%s * INTERVAL '1 day')
      AND c.from_digits IS NOT NULL
      AND length(c.from_digits) = 10
      AND COALESCE(p.address, '') = ''
      AND p.enrichment_flags->>'phone_append' IS NULL
    ORDER BY c.account_id, c.from_digits, c.started_at DESC
    LIMIT %s
"""


def run_sweep(conn, *, limit: int | None = None, days: int | None = None) -> dict:
    """Reverse-append missed-call leads that the inbound webhook left bare.

    Returns a counter dict: {"candidates", "queried", "matched", "updated",
    "skipped_no_provider"}. `queried` counts leads the provider answered for
    (matched or not — both were billed); the gap between it and `candidates` is
    lookups that never completed and will be retried next run.
    """
    counter = {"candidates": 0, "queried": 0, "matched": 0, "updated": 0,
               "skipped_no_provider": False}

    limit = PHONE_APPEND_SWEEP_MAX if limit is None else limit
    days = PHONE_APPEND_SWEEP_DAYS if days is None else days
    if not PHONE_APPEND_PROVIDER or not PHONE_APPEND_API_KEY or limit <= 0:
        counter["skipped_no_provider"] = True
        return counter

    from pipeline.contact import (  # late import: api <-> pipeline
        BATCHDATA_REVERSE_MAX_BATCH, PHONE_APPEND_PROVIDERS, phone_append_batch,
    )
    if PHONE_APPEND_PROVIDER not in PHONE_APPEND_PROVIDERS:
        log.warning("Unknown PHONE_APPEND_PROVIDER %r — skipping append sweep.",
                    PHONE_APPEND_PROVIDER)
        counter["skipped_no_provider"] = True
        return counter

    with conn.cursor() as cur:
        cur.execute(_CANDIDATES_SQL, (days, limit))
        candidates = cur.fetchall()
    counter["candidates"] = len(candidates)
    if not candidates:
        return counter

    log.info("Append sweep: %d missed-call lead(s) via %s…",
             len(candidates), PHONE_APPEND_PROVIDER)

    # Chunk so results land in the DB as they arrive — a crash mid-run keeps
    # what it already paid for instead of re-querying the whole backlog.
    for start in range(0, len(candidates), BATCHDATA_REVERSE_MAX_BATCH):
        chunk = candidates[start:start + BATCHDATA_REVERSE_MAX_BATCH]
        # One lookup per distinct number even when two accounts share a caller:
        # the response is applied to each tenant's own lead, and no tenant reads
        # another's row, so paying twice would buy nothing.
        results = phone_append_batch([row[1] for row in chunk])
        counter.update(_apply_chunk(conn, chunk, results, counter))

    log.info("Append sweep finished: %s", counter)
    return counter


def _apply_chunk(conn, chunk, results: dict, counter: dict) -> dict:
    """Write one chunk's results back onto their leads. Commits once."""
    queried = counter["queried"]
    matched = counter["matched"]
    updated = counter["updated"]

    with conn.cursor() as cur:
        for (account_id, digits, property_id, addr, city, state, zip_code,
             name, email, flags) in chunk:
            if digits not in results:
                continue  # never asked (transport failure) — leave unflagged
            queried += 1
            data = results[digits]
            if data:
                matched += 1

            updates = merge_append(data, {
                "address": addr, "city": city, "state": state, "zip": zip_code,
                "contact_name": name, "contact_email": email,
            })
            sets = [f"{column} = %s" for column in updates]
            cur.execute(
                f"UPDATE properties SET {', '.join(sets + ['enrichment_flags = %s'])} "
                "WHERE id = %s AND account_id = %s",
                (*updates.values(),
                 psycopg2.extras.Json(merge_flags(data, flags, PHONE_APPEND_PROVIDER)),
                 property_id, account_id),
            )
            if updates:
                updated += 1
                log.info("Append sweep: account=%s lead=%s filled=%s",
                         account_id, property_id, sorted(updates))
    conn.commit()
    return {"queried": queried, "matched": matched, "updated": updated}
