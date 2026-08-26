"""
Property-data provider interface (juncto geo layer, Phase 2 prospecting).

Wraps RentCast behind a `PropertyDataProvider` interface — mirroring the
GeocodeProvider pattern in pipeline/geocode_provider.py — so BatchData / ATTOM /
BigDBM can slot in later without touching the prospecting flow, dedupe, or
scoring. Providers return raw vendor records (dicts); mapping into the property
row shape lives in pipeline/prospecting.py.
"""
import logging
from abc import ABC, abstractmethod

from config import (
    PROPERTY_PROVIDER,
    RENTCAST_API_KEY,
    RENTCAST_BASE_URL,
    PROSPECT_MAX_RECORDS,
)
from pipeline.http import get_json, get_json_result

log = logging.getLogger(__name__)

_METERS_PER_MILE = 1609.34
_RENTCAST_PAGE = 500  # RentCast max records per request


class PropertyDataProvider(ABC):
    """Radius search + single-address lookup over a property-data vendor."""

    name: str = "base"

    @abstractmethod
    def search_radius(self, lat: float, lng: float, radius_m: int,
                      filters: dict | None = None,
                      max_records: int = PROSPECT_MAX_RECORDS) -> tuple[list[dict], int]:
        """Return (records, api_requests) for properties within `radius_m` of the
        point, applying whatever server-side filters the vendor supports."""

    @abstractmethod
    def get_by_address(self, address: str, zip_code: str | None = None,
                       state: str | None = None) -> dict | None:
        ...

    def get_by_address_result(self, address: str, zip_code: str | None = None,
                              state: str | None = None) -> tuple[dict | None, bool]:
        """As get_by_address, plus whether the vendor actually answered.

        Returns ``(record, answered)``. `answered` is False only when the lookup
        never got a response — a timeout or an outage — as opposed to a clean
        "no record for this address". Callers that stamp a row so it is not
        re-billed need the difference; see pipeline/backfill.py.

        `state` is part of the address, not an optional filter: RentCast 404s a
        lookup that omits it even for an address it holds (see RentCastProvider).
        Pass the row's state whenever there is one.

        The default is the conservative one: providers that cannot tell the two
        apart report every completed call as answered, which is the behaviour
        this interface had before the distinction existed.
        """
        return self.get_by_address(address, zip_code, state), True


class RentCastProvider(PropertyDataProvider):
    """RentCast `/properties`: circular geo search (lat/lng + radius in miles),
    server-side `propertyType` filter, up to 500 records per request with offset
    pagination. Records arrive pre-geocoded and pre-enriched."""

    name = "rentcast"

    def _headers(self) -> dict:
        return {"X-Api-Key": RENTCAST_API_KEY, "Accept": "application/json"}

    def search_radius(self, lat, lng, radius_m, filters=None, max_records=PROSPECT_MAX_RECORDS):
        if not RENTCAST_API_KEY:
            log.warning("RENTCAST_API_KEY not set — prospecting radius search skipped.")
            return [], 0

        filters = filters or {}
        base_params = {
            "latitude": lat,
            "longitude": lng,
            "radius": round(radius_m / _METERS_PER_MILE, 3),  # RentCast wants miles
        }
        # Only propertyType is reliably server-side; everything else is refined
        # client-side (pipeline/prospecting.refine) against the record schema.
        if filters.get("propertyType"):
            base_params["propertyType"] = filters["propertyType"]

        records: list[dict] = []
        requests_made = 0
        offset = 0
        while len(records) < max_records:
            page = min(_RENTCAST_PAGE, max_records - len(records))
            data = get_json(
                f"{RENTCAST_BASE_URL}/properties",
                headers=self._headers(),
                params={**base_params, "limit": page, "offset": offset},
                timeout=30,
            )
            requests_made += 1
            if not data:
                break
            records.extend(data)
            if len(data) < page:
                break
            offset += page
        return records[:max_records], requests_made

    def get_by_address(self, address, zip_code=None, state=None):
        return self.get_by_address_result(address, zip_code, state)[0]

    def get_by_address_result(self, address, zip_code=None, state=None):
        if not RENTCAST_API_KEY:
            return None, False   # never asked — nothing to record as checked
        params = {"address": address, "limit": 1}
        if zip_code:
            params["zipCode"] = zip_code
        # `state` is required, not decorative. Measured against the live API on
        # one address RentCast demonstrably holds:
        #     address + zipCode                 -> 404
        #     address + city + zipCode          -> 404
        #     address + state + zipCode         -> 200
        #     address + state (no zip, no city) -> 200
        #     address + WRONG city + state      -> 200
        # Every 200 carries state; every 404 omits it. Without it this endpoint
        # 404s on addresses the vendor returns from its own ZIP scan, which is
        # why a 500-property run of ZIP 77007 reported 0 matches on all 181
        # lookups and left property_type and garage_spaces at 0% everywhere.
        #
        # City is deliberately NOT sent. It is not required, and a wrong one is
        # tolerated — and the value we hold may still be wrong or NULL:
        # HCAD-seeded rows once took `city` from the owner's MAILING city
        # (fixed in seed._normalize_hcad, repaired by migration 0079), and rows
        # awaiting the situs-city refill hold NULL. Sending nothing beats
        # sending either.
        if state:
            params["state"] = state
        data, answered = get_json_result(
            f"{RENTCAST_BASE_URL}/properties",
            headers=self._headers(),
            params=params,
            timeout=15,
        )
        if not data:
            return None, answered
        return (data[0] if isinstance(data, list) else data), True


_PROVIDERS: dict[str, type[PropertyDataProvider]] = {
    "rentcast": RentCastProvider,
}


def get_provider(name: str | None = None) -> PropertyDataProvider:
    """Resolve the configured property-data provider (default PROPERTY_PROVIDER)."""
    key = (name or PROPERTY_PROVIDER or "rentcast").strip().lower()
    provider_cls = _PROVIDERS.get(key, RentCastProvider)
    return provider_cls()
