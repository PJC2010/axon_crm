"""
Store-level proof that HCAD ZIP lookups tolerate a ZIP+4 site_zip.

HCAD's site ZIP (real_acct.site_addr_3) may be stored as "77008-2317" rather
than a clean "77008". A 5-digit query must still find those parcels, otherwise a
covered Harris County ZIP looks unsupported. Builds a tiny temp DuckDB so the
real SQL runs (no Postgres needed).
"""
import duckdb
import pytest

from pipeline import hcad_store


@pytest.fixture
def duck(tmp_path):
    path = tmp_path / "hcad.duckdb"
    con = duckdb.connect(str(path))
    con.execute("""
        CREATE TABLE property_summary (
            acct VARCHAR, site_address VARCHAR, site_zip VARCHAR,
            year_built INTEGER, building_sqft BIGINT, land_sqft BIGINT,
            tot_appr_val BIGINT, last_sale_date DATE, owner_name VARCHAR,
            likely_owner_occupied BOOLEAN, mail_addr VARCHAR, mail_city VARCHAR,
            mail_state VARCHAR, mail_zip VARCHAR, neighborhood_code VARCHAR
        )
    """)
    con.execute("""
        INSERT INTO property_summary VALUES
            ('1', '100 CLEAN ST', '77008', 1960, 1500, 6000, 300000, NULL,
             'OWNER A', true, '100 CLEAN ST', 'HOUSTON', 'TX', '77008', 'N1'),
            ('2', '200 PLUS4 ST', '77008-2317', 1975, 1800, 6500, 350000, NULL,
             'OWNER B', true, '200 PLUS4 ST', 'HOUSTON', 'TX', '77008', 'N1'),
            ('3', '300 OTHER ST', '77009', 1980, 1600, 6200, 320000, NULL,
             'OWNER C', true, '300 OTHER ST', 'HOUSTON', 'TX', '77009', 'N1')
    """)
    con.close()
    return str(path)


def test_zip_query_matches_both_clean_and_plus4(duck):
    parcels = hcad_store.query_parcels_for_zip("77008", db_path=duck)
    addrs = {p["site_address"] for p in parcels.values()}
    # Both the clean and the ZIP+4 parcel are returned; the 77009 one is not.
    assert addrs == {"100 CLEAN ST", "200 PLUS4 ST"}


def test_properties_query_matches_plus4(duck):
    props = hcad_store.query_properties("77008", db_path=duck)
    assert len(props) == 2


def test_region_zips_are_canonicalized(duck):
    # Region ZIP listing must collapse the ZIP+4 into the 5-digit form so the
    # clean and ZIP+4 parcels don't split into two separate "ZIPs".
    zips = hcad_store.region_zips("N1", db_path=duck)
    assert set(zips) == {"77008", "77009"}
