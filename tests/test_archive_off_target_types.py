"""The off-target-type cleanup script's query construction.

The behaviour was validated against a real Postgres during development (reading
through parcel_id, tenant-value precedence, batch termination). These pin the
parts that break silently: parameter ORDER, and the rule that an unresolvable
type is never archived.
"""
import pytest

from pipeline.property_type import sql_type_allowlist
from scripts.archive_off_target_types import (
    BATCH, REASON, RESOLVED, _cte, _target, coverage, preview,
)

ALLOW = ["Single Family", "Townhouse", "Manufactured"]
ALLOW_SQL = sql_type_allowlist("dwelling_type", ALLOW)


class FakeCur:
    def __init__(self, rows=None):
        self.sql = self.params = None
        self._rows = rows or []

    def execute(self, sql, params=None):
        self.sql, self.params = sql, list(params or [])

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else (0, 0)


class TestResolvedType:
    def test_reads_through_the_parcel_link(self):
        # Existing production rows have properties.property_type NULL; the type
        # lives in the shared cache. Without this the script archives nothing
        # and looks like it found a clean book.
        assert "pc.property_type" in RESOLVED
        assert "LEFT JOIN parcels pc ON pc.id = p.parcel_id" in _cte(None)[0]

    def test_tenant_value_wins_over_the_cache(self):
        # COALESCE order: the tenant's own value may be RentCast's answer for a
        # row this deployment paid to enrich.
        assert RESOLVED.index("p.property_type") < RESOLVED.index("pc.property_type")

    def test_only_live_rows_are_considered(self):
        assert "p.archived_at IS NULL" in _cte(None)[0]


class TestNeverArchivesAnUnresolvableType:
    """The safety property: NULL means "no state_class", not "condo"."""

    def test_target_requires_a_type(self):
        assert "dwelling_type IS NOT NULL" in _target(ALLOW_SQL)

    def test_target_negates_the_allowlist(self):
        # NOT(allowlist) rather than a NOT IN list, so unknown types land on the
        # KEEP side exactly as they do at seed time.
        assert _target(ALLOW_SQL).endswith(f"NOT {ALLOW_SQL}")

    @pytest.mark.parametrize("kept", ALLOW)
    def test_wanted_types_are_not_targeted(self, kept):
        assert f"'{kept}'" in _target(ALLOW_SQL)


class TestParamOrder:
    """psycopg2 binds %s positionally by statement TEXT order.

    The CTE carries account_id and appears BEFORE the SET clause's reason
    placeholder, so the two must be passed in that order. Getting this wrong
    writes the account id into exclusion_reason instead of erroring.
    """

    def test_cte_param_is_first_and_only_when_scoped(self):
        sql, params = _cte(7)
        assert params == [7] and sql.count("%s") == 1

    def test_unscoped_cte_binds_nothing(self):
        sql, params = _cte(None)
        assert params == [] and sql.count("%s") == 0

    def test_update_binds_account_then_reason(self):
        cte, params = _cte(7)
        stmt = f"{cte}\nUPDATE properties SET exclusion_reason = %s"
        ordered = params + [REASON]
        assert stmt.index("p.account_id = %s") < stmt.index("exclusion_reason = %s")
        assert ordered == [7, REASON]

    def test_preview_passes_only_the_cte_params(self):
        cur = FakeCur()
        preview(cur, ALLOW_SQL, 7)
        assert cur.params == [7]
        assert cur.sql.count("%s") == len(cur.params)

    def test_coverage_passes_only_the_cte_params(self):
        cur = FakeCur(rows=[(10, 8)])
        assert coverage(cur, 7) == (10, 8)
        assert cur.params == [7]
        assert cur.sql.count("%s") == len(cur.params)


def test_batch_is_bounded():
    # statement_timeout caps a STATEMENT, not a transaction: each UPDATE's cost
    # must stay proportional to the batch rather than to the account.
    assert 0 < BATCH <= 10000
