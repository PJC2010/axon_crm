"""
Harris County parcel centroids — request building and response parsing for the
county's public ArcGIS parcels layer (config.HCAD_PARCELS_ARCGIS_URL).

Why this exists: hcad_properties (the assessor mirror) carries no coordinates,
so filling parcels.latitude used to need a per-address geocoder. The county GIS
layer already knows every parcel's geometry, keyed by the same 13-digit HCAD
account; asking for returnCentroid=true&outSR=4326 yields a free WGS84 point
per parcel. ~1.53M features at maxRecordCount 2000 is a ~770-request pull —
free, keyless, and done once for every tenant.

Pure functions only — no HTTP, no DB — unit-tested directly
(tests/test_parcel_centroids.py; same split as pipeline/geocode_batch.py). The
HTTP/DB shell is tools/load_parcel_centroids.py.

Two service quirks the parsers absorb:

  * Errors arrive as HTTP 200 with an {"error": ...} JSON body, so transport
    success proves nothing — parse_count/parse_page raise ArcGISError instead
    of letting a bad page pass as an empty one.
  * The layer's NATIVE spatial reference is Texas State Plane feet (EPSG 2278),
    not WGS84. outSR=4326 is what makes centroids come back as lon/lat, so a
    coordinate outside plausible Harris County bounds means the request was
    built wrong — that is a run-stopping error, never a per-feature skip,
    because every subsequent feature would be equally poisoned.
"""

ARCGIS_PAGE_SIZE = 2000   # the layer's maxRecordCount

# Generous bounds around Harris County (~29.5–30.2 N, ~94.8–96.0 W), mirroring
# the CHECK constraints on hcad_parcel_centroids (migration 0070): wide enough
# that any real parcel passes, tight enough that State-Plane feet or a swapped
# lat/lon cannot.
LAT_RANGE = (25.0, 34.0)
LON_RANGE = (-100.0, -90.0)


class ArcGISError(RuntimeError):
    """The service answered, but not with data we can use."""


def count_params() -> dict:
    """Query params asking the layer for its total feature count."""
    return {"where": "1=1", "returnCountOnly": "true", "f": "json"}


def query_params(last_objectid: int, page_size: int = ARCGIS_PAGE_SIZE) -> dict:
    """Query params for one keyset page: features with OBJECTID strictly greater
    than `last_objectid`, ordered so the page's last row is the next cursor.

    Keyset (WHERE OBJECTID > n) rather than resultOffset: offsets get slow and
    unstable deep into 1.5M rows, and the cursor doubles as the checkpoint an
    interrupted download resumes from. Note a short page is NOT the end —
    hosted layers can cap below resultRecordCount (exceededTransferLimit) — so
    the caller stops only on an EMPTY page.

    `last_objectid`/`page_size` are int()-coerced: they are interpolated into
    the where clause, and the coercion is what keeps that injection-proof.
    """
    return {
        "where": f"OBJECTID > {int(last_objectid)}",
        "orderByFields": "OBJECTID",
        "outFields": "OBJECTID,acct_num",
        "returnGeometry": "false",
        "returnCentroid": "true",
        "outSR": 4326,
        "resultRecordCount": int(page_size),
        "f": "json",
    }


def parse_count(data) -> int:
    """The layer's total feature count, or ArcGISError."""
    _raise_on_error(data)
    count = data.get("count")
    if not isinstance(count, int):
        raise ArcGISError(f"no count in response: {_head(data)}")
    return count


def parse_page(data) -> tuple[list[tuple[int, str, float, float]], dict]:
    """Parse one query page into [(objectid, acct_raw, lon, lat), ...] + meta.

    meta: features (count on the page), no_acct / no_centroid (skipped —
    ~0.8% of real features carry no account), last_objectid (cursor for the
    next keyset request; None on an empty page).

    A feature without an account or centroid is that feature's defect: skip it
    and count it. A coordinate outside LAT_RANGE/LON_RANGE is OUR defect
    (outSR dropped, or axes swapped) and poisons the whole pull: raise.
    """
    _raise_on_error(data)
    features = data.get("features")
    if features is None:
        raise ArcGISError(f"no features array in response: {_head(data)}")

    rows: list[tuple[int, str, float, float]] = []
    meta = {"features": len(features), "no_acct": 0, "no_centroid": 0,
            "last_objectid": None}
    for feature in features:
        attrs = feature.get("attributes") or {}
        oid = attrs.get("OBJECTID")
        if oid is None:
            raise ArcGISError("feature has no OBJECTID — the request must ask "
                              "for outFields=OBJECTID,acct_num or keyset "
                              "paging cannot advance")
        oid = int(oid)
        if meta["last_objectid"] is None or oid > meta["last_objectid"]:
            meta["last_objectid"] = oid

        acct = attrs.get("acct_num")
        if acct is None or not str(acct).strip():
            meta["no_acct"] += 1
            continue
        centroid = feature.get("centroid") or {}
        lon, lat = centroid.get("x"), centroid.get("y")
        if lon is None or lat is None:
            meta["no_centroid"] += 1
            continue
        lon, lat = float(lon), float(lat)
        if not (LAT_RANGE[0] <= lat <= LAT_RANGE[1]
                and LON_RANGE[0] <= lon <= LON_RANGE[1]):
            raise ArcGISError(
                f"centroid ({lat}, {lon}) is outside Harris County bounds — "
                f"was outSR=4326 dropped, or lat/lon swapped? (OBJECTID {oid})")
        rows.append((oid, str(acct), lon, lat))
    return rows, meta


def _raise_on_error(data) -> None:
    if data is None:
        raise ArcGISError("empty response")
    error = data.get("error") if isinstance(data, dict) else None
    if error is not None:
        raise ArcGISError(f"service error: {_head(error)}")
    if not isinstance(data, dict):
        raise ArcGISError(f"unexpected response shape: {_head(data)}")


def _head(value) -> str:
    return str(value)[:200]
