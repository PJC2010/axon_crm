"""HCAD state class -> property_type: the mapping, and its SQL twin.

The Python/SQL pair here follows tests/test_addr.py and tests/test_parcel_id.py:
the expression is run in a real DuckDB and compared code-for-code with the
Python function, because a pair that disagrees fails SILENTLY — one path writes
a type and the other writes NULL, and nothing errors.
"""
import duckdb
import pytest

from pipeline.property_type import (
    DWELLING_BY_STATE_CLASS,
    from_state_class,
    sql_from_state_class,
    sql_type_allowlist,
)
from pipeline.residential import NON_RESIDENTIAL_PROPERTY_TYPES, classify
from pipeline.addr import normalize


# Every code HCAD's own decode table (desc_r_01_state_class.txt) carries for
# the A/B/E/M/Z families, so a code the county publishes can never be silently
# dropped from the mapping without this list being updated too.
COUNTY_RESIDENTIAL_CODES = [
    "A1", "A2", "A3", "A4", "B1", "B2", "B3", "B4",
    "E1", "M3", "Z0", "Z1", "Z2", "Z3", "Z4", "Z5",
]


class TestMapping:
    def test_single_family_is_the_common_case(self):
        assert from_state_class("A1") == "Single Family"

    def test_condo_family_is_covered(self):
        # The Z family is invisible to residential.py's A/B/E/M prefix rule;
        # covering it here is the whole reason the decode table was loaded.
        assert from_state_class("Z1") == "Condo"
        assert from_state_class("Z4") == "Condo"
        assert from_state_class("Z5") == "Condo"

    def test_county_wording_splits_townhouse_from_condo(self):
        assert from_state_class("Z2") == "Townhouse"
        assert from_state_class("Z3") == "Townhouse"

    def test_both_mobile_home_classes_are_manufactured(self):
        # A2 owns its land, M3 rents a lot in a park. Same roof.
        assert from_state_class("A2") == "Manufactured"
        assert from_state_class("M3") == "Manufactured"

    def test_multi_family_keeps_the_county_grain(self):
        assert from_state_class("B2") == "Duplex"
        assert from_state_class("B3") == "Triplex"
        assert from_state_class("B4") == "Fourplex"

    @pytest.mark.parametrize("code", ["A1", "a1", " a1 ", "  A1"])
    def test_case_and_whitespace_are_stylistic(self, code):
        assert from_state_class(code) == "Single Family"

    @pytest.mark.parametrize("value", [None, "", "   ", "ZZ", "9999", 0])
    def test_unknown_input_is_no_opinion(self, value):
        assert from_state_class(value) is None


class TestOnlyDwellingsMap:
    """The module's central safety property, asserted rather than described."""

    @pytest.mark.parametrize(
        "code", ["F1", "F2", "J3", "J5", "L1", "S1", "C1", "C2", "C3",
                 "X1", "X2", "X3", "XJ", "D2", "G1", "O1", "O2", "1D1"]
    )
    def test_non_residential_classes_yield_nothing(self, code):
        assert from_state_class(code) is None

    def test_auxiliary_buildings_are_not_a_dwelling_type(self):
        # A3 rolls up to dept=A1, so the county calls it residential — but it
        # is a shed, with bld_ar = 0 on every one of them. Residential is not
        # the same question as "what kind of home is this".
        assert from_state_class("A3") is None

    def test_unimproved_condo_is_not_a_dwelling_type(self):
        assert from_state_class("Z0") is None

    def test_every_county_code_is_decided_deliberately(self):
        # Not an assertion about the values, but about coverage: each code the
        # county publishes for these families is either mapped or consciously
        # excluded above. A new code appearing in an HCAD export shows up here.
        for code in COUNTY_RESIDENTIAL_CODES:
            assert (code in DWELLING_BY_STATE_CLASS) == (
                from_state_class(code) is not None
            )


class TestCannotArchiveAHome:
    """No value this module emits may read as non-residential downstream.

    `non_residential_type` is an EXCLUDE-tier reason — archivable in bulk — so
    a label added here that happens to normalize into the denylist would make
    the cleanup sweep archive an account's homes. That is the failure this
    module exists to avoid, so it is pinned rather than trusted.
    """

    @pytest.mark.parametrize("label", sorted(set(DWELLING_BY_STATE_CLASS.values())))
    def test_label_is_not_on_the_non_residential_denylist(self, label):
        assert normalize(label) not in NON_RESIDENTIAL_PROPERTY_TYPES

    @pytest.mark.parametrize("code", sorted(DWELLING_BY_STATE_CLASS))
    def test_a_mapped_row_is_not_archived_for_its_type(self, code):
        row = {
            "address": "123 ASH ST",
            "state_class": code,
            "property_type": from_state_class(code),
            "square_footage": 1800,
            "owner_name": "SMITH JOHN A",
        }
        assert "non_residential_type" not in classify(row)


class TestSqlParity:
    """The SQL twin must agree with Python on every input, or it fails silently."""

    def _sql_value(self, con, value):
        expr = sql_from_state_class("sc")
        rows = con.execute(
            f"SELECT {expr} FROM (SELECT ? AS sc)", [value]
        ).fetchall()
        return rows[0][0]

    @pytest.mark.parametrize(
        "value",
        COUNTY_RESIDENTIAL_CODES
        + ["F1", "F2", "J5", "C1", "X1", "1D1", "ZZ", "", "   ", "a1", " z3 ", None],
    )
    def test_sql_matches_python(self, value):
        con = duckdb.connect(":memory:")
        try:
            assert self._sql_value(con, value) == from_state_class(value)
        finally:
            con.close()

    def test_sql_rejects_a_non_identifier(self):
        # The identifier check IS the injection guard, same as
        # pipeline/parcel_id.py and pipeline/db.py's allowlist.
        for bad in ["h.state_class; DROP TABLE parcels", "1", "", "a b", None]:
            with pytest.raises(ValueError):
                sql_from_state_class(bad)

    def test_sql_accepts_a_qualified_column(self):
        assert "h.state_class" in sql_from_state_class("h.state_class")


class TestSeedAllowlist:
    """config.SEED_PROPERTY_TYPES as a SQL filter, for the shared-cache seed."""

    ALLOW = ["Single Family", "Townhouse", "Manufactured"]

    def test_builds_an_in_clause(self):
        sql = sql_type_allowlist("p.property_type", self.ALLOW)
        assert "p.property_type IN (" in sql
        for t in self.ALLOW:
            assert f"'{t}'" in sql

    def test_null_is_kept(self):
        # Load-bearing: property_type is derived from state_class, so it is NULL
        # for every parcel outside a county whose mirror carries that column.
        # Dropping NULLs would make those ZIPs seed zero rows and look empty.
        assert "IS NULL OR" in sql_type_allowlist("p.property_type", self.ALLOW)

    @pytest.mark.parametrize("allowed", [None, [], ["*"], ["*", "Condo"], ["  "]])
    def test_no_allowlist_means_no_filter(self, allowed):
        # Matches seed._wanted_type's treatment of the same config value.
        assert sql_type_allowlist("p.property_type", allowed) == ""

    def test_label_allowlist_is_the_injection_guard(self):
        for bad in ["x'; DROP TABLE parcels--", "Single Family'", 'a"b', "a;b", "--x"]:
            with pytest.raises(ValueError):
                sql_type_allowlist("p.property_type", [bad])

    def test_column_must_be_an_identifier(self):
        with pytest.raises(ValueError):
            sql_type_allowlist("p.property_type; DROP TABLE parcels", self.ALLOW)

    def test_filter_matches_python_on_real_rows(self):
        """The SQL filter keeps exactly the rows seed._wanted_type would keep."""
        from pipeline.seed import _wanted_type
        import pipeline.seed as seed_mod

        con = duckdb.connect(":memory:")
        try:
            con.execute("CREATE TABLE p (property_type VARCHAR)")
            values = ["Single Family", "Condo", "Townhouse", "Manufactured",
                      "Duplex", "Triplex", "Fourplex", "Multi-Family", None]
            con.executemany("INSERT INTO p VALUES (?)", [(v,) for v in values])
            sql = sql_type_allowlist("property_type", self.ALLOW)
            kept_sql = {r[0] for r in
                        con.execute(f"SELECT property_type FROM p WHERE {sql}").fetchall()}

            orig = seed_mod.SEED_PROPERTY_TYPES
            seed_mod.SEED_PROPERTY_TYPES = self.ALLOW
            try:
                kept_py = {v for v in values if _wanted_type(v)}
            finally:
                seed_mod.SEED_PROPERTY_TYPES = orig

            assert kept_sql == kept_py
            assert "Condo" not in kept_sql and "Multi-Family" not in kept_sql
            assert None in kept_sql          # NULL survives both paths
            assert "Single Family" in kept_sql
        finally:
            con.close()


class TestSeedAccountWiring:
    """The filter has to actually reach the statement, not just exist."""

    def _sql(self, **kwargs):
        import inspect
        from pipeline import parcels
        captured = {}

        class FakeCur:
            def __enter__(self): return self
            def __exit__(self, *a): return False
            def execute(self, sql, params=None): captured["sql"] = sql
            def fetchone(self): return [0]
            @property
            def rowcount(self): return 0

        class FakeConn:
            def cursor(self, *a, **k): return FakeCur()

        try:
            parcels.seed_account(FakeConn(), "77396", 1, **kwargs)
        except Exception:
            pass  # we only need the first statement's text
        return captured.get("sql", "")

    def test_types_reach_the_statement(self):
        sql = self._sql(dwelling_types=["Single Family", "Townhouse"])
        assert "'Single Family'" in sql and "'Townhouse'" in sql
        assert "'Condo'" not in sql

    def test_absent_by_default(self):
        # Existing callers are unchanged: no dwelling_types, no clause.
        assert "property_type IN" not in self._sql()

    def test_star_adds_no_clause(self):
        assert "property_type IN" not in self._sql(dwelling_types=["*"])
