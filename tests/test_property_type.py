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
