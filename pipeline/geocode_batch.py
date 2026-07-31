"""
Census Bureau *batch* geocoding — the bulk counterpart to the one-address
CensusGeocoder in pipeline/geocode_provider.py.

Why this exists: the per-ZIP geocode step issued one Google request per property,
serially, with a 50ms sleep between them. On ZIP 77449 (41,334 parcels) that is
~2h52m and roughly $200 of Google Geocoding at $5/1,000. The Census batch
endpoint accepts up to 10,000 addresses in a single POST and is free, turning the
same work into 5 requests.

The Census batch API is CSV-in / CSV-out rather than JSON, so the payload builder
and the response parser live here as pure functions — no HTTP, no DB — and are
unit-tested directly (same split as pipeline/equity.py and pipeline/job_value.py).

Request format (no header row), one record per line:
    unique_id,street,city,state,zip

Response format (no header row), quoted fields, order NOT guaranteed to match
the request — which is exactly why records carry a unique id:
    id,input_address,status,match_type,matched_address,"lon,lat",tigerline,side

`status` is "Match" / "No_Match" / "Tie". Only "Match" carries coordinates, and
note the coordinate field is **longitude first** — the reverse of the (lat, lng)
convention used everywhere else in this codebase.
"""
import csv
import io
import logging

log = logging.getLogger(__name__)

# The documented per-request ceiling for the Census batch endpoint.
MAX_BATCH = 10_000

# Census returns a match type per record; "Exact" is a clean hit, anything else
# ("Non_Exact", "Tie") matched more loosely. Mirrors the confidence values the
# one-line CensusGeocoder already reports so the two paths stay comparable.
CONFIDENCE_EXACT = 0.9
CONFIDENCE_LOOSE = 0.6


def build_payload(records: list[dict]) -> str:
    """Render address records as the CSV the batch endpoint expects.

    `records` are dicts with an `id` plus address parts. Commas and quotes in the
    address are handled by csv.writer, so a street like "123 MAIN ST, APT 4"
    cannot shift the column layout.

    Blank city/state/zip are written as empty fields rather than omitted — the
    endpoint requires all five columns to be present on every line.
    """
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    for rec in records:
        writer.writerow([
            rec.get("id", ""),
            _clean(rec.get("address")),
            _clean(rec.get("city")),
            _clean(rec.get("state")),
            _clean(rec.get("zip")),
        ])
    return buf.getvalue()


def parse_response(text: str) -> dict[str, tuple[float, float, float]]:
    """Parse the batch response CSV into {id: (lat, lng, confidence)}.

    Only "Match" rows are returned; No_Match and Tie are dropped so the caller
    can route them to the fallback provider. Malformed or short rows are skipped
    rather than raised on — a single bad line must not lose the other 9,999
    results in the batch.
    """
    out: dict[str, tuple[float, float, float]] = {}
    if not text:
        return out

    for row in csv.reader(io.StringIO(text)):
        # id, input, status, match_type, matched_address, "lon,lat", ...
        if len(row) < 6:
            continue
        rec_id, status, match_type, coords = row[0], row[2], row[3], row[5]
        if status.strip() != "Match":
            continue
        parsed = _parse_coords(coords)
        if parsed is None:
            continue
        lng, lat = parsed
        confidence = (CONFIDENCE_EXACT if match_type.strip().lower() == "exact"
                      else CONFIDENCE_LOOSE)
        out[rec_id.strip()] = (lat, lng, confidence)
    return out


def chunk(records: list, size: int = MAX_BATCH) -> list[list]:
    """Split records into batches the endpoint will accept."""
    if size <= 0:
        raise ValueError("chunk size must be positive")
    return [records[i:i + size] for i in range(0, len(records), size)]


def _parse_coords(field: str) -> tuple[float, float] | None:
    """Census packs coordinates into one field as "lon,lat" — longitude FIRST.

    Returned in the same (lon, lat) order it was given, so the caller does the
    swap explicitly and the reversal stays visible at the call site.
    """
    parts = (field or "").split(",")
    if len(parts) != 2:
        return None
    try:
        return float(parts[0]), float(parts[1])
    except ValueError:
        return None


def _clean(value) -> str:
    """Normalize a field for the CSV payload.

    Newlines would split one record into two and silently corrupt every
    subsequent row's id alignment, so they are stripped rather than escaped.
    """
    if value is None:
        return ""
    return " ".join(str(value).split())
