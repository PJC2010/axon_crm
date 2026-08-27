"""Tests for pipeline/hcad_store.hcad_available() — the startup-guard helper."""
import pytest

import pipeline.hcad_store as hcad_store
from pipeline.hcad_store import garage_spaces_from_sqft


class _FakeCursor:
    def __init__(self, row):
        self._row = row

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, *a, **k):
        pass

    def fetchone(self):
        return self._row


class _FakeConn:
    def __init__(self, row):
        self._row = row

    def cursor(self):
        return _FakeCursor(self._row)

    def close(self):
        pass


def test_db_exists_false_for_empty_path(monkeypatch):
    """Regression: an empty PERMIT_DB_PATH means "use the Postgres mirror".

    Render sets PERMIT_DB_PATH="" on purpose (ephemeral web filesystem). Path("")
    resolves to the current directory, which exists and has a non-zero size, so
    the naive exists() check reported a DuckDB that was not there and every query
    then died in duckdb.connect("", read_only=True) — before the callers'
    fallback, taking down the whole pipeline run.
    """
    monkeypatch.setattr(hcad_store, "PERMIT_DB_PATH", "")
    assert hcad_store.db_exists() is False
    assert hcad_store.db_exists("") is False
    assert hcad_store.db_exists("   ") is False


def test_db_exists_false_for_a_directory(tmp_path, monkeypatch):
    """A directory is not a database — is_file(), not exists()."""
    monkeypatch.setattr(hcad_store, "PERMIT_DB_PATH", str(tmp_path))
    assert hcad_store.db_exists() is False


def test_db_exists_false_for_missing_and_empty_files(tmp_path, monkeypatch):
    missing = tmp_path / "nope.duckdb"
    monkeypatch.setattr(hcad_store, "PERMIT_DB_PATH", str(missing))
    assert hcad_store.db_exists() is False

    empty = tmp_path / "empty.duckdb"
    empty.write_bytes(b"")
    assert hcad_store.db_exists(str(empty)) is False


def test_db_exists_true_for_a_real_non_empty_file(tmp_path):
    real = tmp_path / "harris_county.duckdb"
    real.write_bytes(b"not really duckdb, but non-empty")
    assert hcad_store.db_exists(str(real)) is True


def test_available_true_when_duckdb_present(monkeypatch):
    # DuckDB file present → available without touching Postgres.
    monkeypatch.setattr(hcad_store, "db_exists", lambda *a, **k: True)
    assert hcad_store.hcad_available() is True


def test_available_true_when_postgres_has_rows(monkeypatch):
    monkeypatch.setattr(hcad_store, "db_exists", lambda *a, **k: False)
    import pipeline.db as db
    monkeypatch.setattr(db, "get_conn", lambda: _FakeConn(row=(1,)))
    assert hcad_store.hcad_available() is True


def test_unavailable_when_no_duckdb_and_empty_mirror(monkeypatch):
    monkeypatch.setattr(hcad_store, "db_exists", lambda *a, **k: False)
    import pipeline.db as db
    monkeypatch.setattr(db, "get_conn", lambda: _FakeConn(row=None))
    assert hcad_store.hcad_available() is False


def test_unavailable_when_db_unreachable(monkeypatch):
    # No DuckDB and Postgres connection fails → False (non-fatal for the guard).
    monkeypatch.setattr(hcad_store, "db_exists", lambda *a, **k: False)
    import pipeline.db as db

    def _boom():
        raise RuntimeError("no db")

    monkeypatch.setattr(db, "get_conn", _boom)
    assert hcad_store.hcad_available() is False


# ── garage_spaces_from_sqft ──────────────────────────────────────────────────
# HCAD extra-features store garage size as square footage (`uts`), not a space
# count. Regression tests for the "462 garage spaces" bug.

def test_garage_sqft_converts_to_spaces():
    assert garage_spaces_from_sqft(462) == 2    # the reported bug case
    assert garage_spaces_from_sqft(240) == 1
    assert garage_spaces_from_sqft(720) == 3


def test_garage_sqft_zero_and_none_mean_no_garage():
    assert garage_spaces_from_sqft(0) == 0
    assert garage_spaces_from_sqft(None) == 0


def test_garage_sqft_floors_at_one_space():
    # Any recorded garage area implies at least a 1-car garage.
    assert garage_spaces_from_sqft(80) == 1


def test_garage_sqft_caps_at_max():
    import config
    assert garage_spaces_from_sqft(999_999) == config.MAX_GARAGE_SPACES


def test_query_extra_features_returns_spaces_not_sqft(tmp_path):
    """End-to-end through the DuckDB query: 462 sqft of garage → 2 spaces."""
    duckdb = pytest.importorskip("duckdb")
    db_file = tmp_path / "hcad.duckdb"
    con = duckdb.connect(str(db_file))
    con.execute("CREATE TABLE property_summary (acct VARCHAR, site_address VARCHAR, site_zip VARCHAR)")
    con.execute("CREATE TABLE extra_features (acct VARCHAR, bld_num VARCHAR, cd VARCHAR, s_dscr VARCHAR, l_dscr VARCHAR, uts VARCHAR)")
    con.execute("INSERT INTO property_summary VALUES ('1', '9414 SLATE STONE CT', '77064')")
    con.execute("INSERT INTO extra_features VALUES ('1', '1', 'GAR', '', 'GARAGE - ATTACHED', '462')")
    con.close()

    out = hcad_store.query_extra_features("77064", db_path=str(db_file))
    assert out["9414 slate stone ct"]["garage_spaces"] == 2


# ── site_city: the parcel's OWN city, never the owner's mail_city ────────────

def _full_summary_db(tmp_path, with_site_city: bool):
    """A minimal-but-complete property_summary for the seed queries.

    One absentee-owner parcel: sits in HOUSTON (ZIP 77073), owner gets mail in
    LAKE DALLAS — the exact shape that once put "LAKE DALLAS" on a Houston
    lead card when the seed borrowed mail_city as the city.
    """
    duckdb = pytest.importorskip("duckdb")
    db_file = tmp_path / "hcad.duckdb"
    con = duckdb.connect(str(db_file))
    site_city_col = "site_city VARCHAR," if with_site_city else ""
    con.execute(f"""
        CREATE TABLE property_summary (
            acct VARCHAR, site_address VARCHAR, {site_city_col}
            site_zip VARCHAR, year_built VARCHAR, building_sqft BIGINT,
            land_sqft BIGINT, tot_appr_val BIGINT, last_sale_date DATE,
            owner_name VARCHAR, likely_owner_occupied BOOLEAN,
            mail_addr VARCHAR, mail_city VARCHAR, mail_state VARCHAR,
            mail_zip VARCHAR, state_class VARCHAR, neighborhood_code VARCHAR
        )
    """)
    site_city_val = "'HOUSTON'," if with_site_city else ""
    con.execute(f"""
        INSERT INTO property_summary VALUES (
            '123', '21919 INVERNESS FOREST BLVD', {site_city_val}
            '77073', '2004', 15231,
            60000, 4749071, DATE '2020-01-15',
            'KSW HOLDINGS AG PROPERTIES', FALSE,
            '1851 TURBEVILLE RD', 'LAKE DALLAS', 'TX',
            '75065', 'F1', '8901.44'
        )
    """)
    con.close()
    return db_file


def test_query_parcels_for_zip_carries_situs_city_not_mail_city(tmp_path):
    db_file = _full_summary_db(tmp_path, with_site_city=True)
    out = hcad_store.query_parcels_for_zip("77073", db_path=str(db_file))
    rec = out["21919 inverness forest blvd"]
    assert rec["site_city"] == "HOUSTON"
    # The owner's mailing city reaches the seed only inside mailing_address,
    # where it belongs — never as a top-level key a mapper could mistake for
    # the property's city.
    assert "mail_city" not in rec
    assert "LAKE DALLAS" in rec["mailing_address"]


def test_query_parcels_for_zip_degrades_on_a_pre_site_city_duckdb(tmp_path):
    # A DuckDB built before migration 0079 has no site_city column — the probe
    # must degrade it to NULL, not abort the query or fall back to mail_city.
    db_file = _full_summary_db(tmp_path, with_site_city=False)
    out = hcad_store.query_parcels_for_zip("77073", db_path=str(db_file))
    rec = out["21919 inverness forest blvd"]
    assert rec["site_city"] is None
    assert "mail_city" not in rec


def test_query_properties_carries_situs_city_for_enrichment(tmp_path):
    # The enrichment path (hcad_enrichment._backfill("city", ...)) heals rows
    # whose polluted city the 0079 repair NULLed — it needs site_city too.
    db_file = _full_summary_db(tmp_path, with_site_city=True)
    out = hcad_store.query_properties("77073", db_path=str(db_file))
    assert out["21919 inverness forest blvd"]["site_city"] == "HOUSTON"


# ── Duplicate situs addresses: one account wins, deterministically ───────────

def _dup_address_db(tmp_path):
    """Two situs addresses that each appear on two HCAD accounts.

    In both pairs the row that must win comes FIRST in insertion order, so a
    dict built last-write-wins (what these queries did before they ordered)
    picks the other account — the assertions distinguish the real rule from
    both insertion order and accident.
    """
    duckdb = pytest.importorskip("duckdb")
    db_file = tmp_path / "hcad_dup.duckdb"
    con = duckdb.connect(str(db_file))
    con.execute("""
        CREATE TABLE property_summary (
            acct VARCHAR, site_address VARCHAR, site_city VARCHAR,
            site_zip VARCHAR, year_built VARCHAR, building_sqft BIGINT,
            land_sqft BIGINT, tot_appr_val BIGINT, last_sale_date DATE,
            owner_name VARCHAR, likely_owner_occupied BOOLEAN,
            mail_addr VARCHAR, mail_city VARCHAR, mail_state VARCHAR,
            mail_zip VARCHAR, state_class VARCHAR, neighborhood_code VARCHAR
        )
    """)
    # Present so the joined (non-fallback) query paths run.
    con.execute("CREATE TABLE neighborhood_codes (cd VARCHAR, dscr VARCHAR)")
    rows = [
        # Most-valued account first: the value decides.
        ("0051740000014", "2316 WASHINGTON AVE", 900_000, "1968"),
        ("0051740000001", "2316 WASHINGTON AVE", 150_000, "2001"),
        # A value tie: the lowest acct decides.
        ("1224460010011", "232 KNOX ST", 500_000, "1950"),
        ("1224460010012", "232 KNOX ST", 500_000, "1955"),
    ]
    for acct, addr, val, yr in rows:
        con.execute(
            "INSERT INTO property_summary VALUES "
            "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [acct, addr, "HOUSTON", "77007", yr, 1500, 5000, val, None,
             "SMITH JOHN", True, "1 MAIN ST", "HOUSTON", "TX", "77007",
             "A1", "8901"],
        )
    con.close()
    return db_file


def test_duplicate_situs_address_winner_matches_the_parcels_cache(tmp_path):
    """HCAD carries several accounts at one situs address (multi-tract lots,
    condo-style developments, replats). parcels.ensure_from_hcad keeps one per
    address — DISTINCT ON … ORDER BY tot_appr_val DESC NULLS LAST, acct — and
    a seeded row's parcel_apn comes from that cache, so these dicts must pick
    the SAME account. They used to keep whichever row the engine emitted last,
    and every disagreeing address produced a phantom "[4b] HCAD acct …
    disagrees with stored parcel" warning and property_field_audits row on
    every single run.
    """
    db_file = _dup_address_db(tmp_path)

    for query in (hcad_store.query_properties, hcad_store.query_parcels_for_zip):
        out = query("77007", db_path=str(db_file))
        assert out["2316 washington ave"]["parcel_apn"] == "0051740000014", query
        assert out["232 knox st"]["parcel_apn"] == "1224460010011", query
        # The whole row rides with the winning account, not just its number.
        assert out["2316 washington ave"]["year_built"] == 1968, query

    out = hcad_store.query_properties_for_region("8901", "77007",
                                                 db_path=str(db_file))
    assert out["2316 washington ave"]["parcel_apn"] == "0051740000014"
    assert out["232 knox st"]["parcel_apn"] == "1224460010011"
