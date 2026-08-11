"""
Tests for pipeline/parcels.py — the shared parcel cache.

These cover the column allowlist that keeps one tenant's paid data out of
another's rows, and the SQL each operation builds. No database required.
"""
import pytest

from pipeline import parcels
from pipeline.parcels import SHARED_COLS, _NEVER_SHARED
from pipeline.db import ALL_COLS


class _FakeCursor:
    """Captures every statement a parcels function issues.

    seed_account issues two (the insert, then the refresh via sync), so the
    statements are kept as a list and `sql`/`params` report the first.
    """

    def __init__(self, rows=None, rowcount=0):
        self.statements: list[tuple] = []
        self._rows = rows or []
        self.rowcount = rowcount

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.statements.append((sql, params))

    @property
    def sql(self):
        return self.statements[0][0] if self.statements else None

    @property
    def params(self):
        return self.statements[0][1] if self.statements else None

    def all_sql(self) -> str:
        return "\n".join(s for s, _ in self.statements)

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor
        self.commits = 0

    def cursor(self, *a, **k):
        return self._cursor

    def commit(self):
        self.commits += 1

    def close(self):
        pass


# ── The tenant-isolation boundary ─────────────────────────────────────────────

def test_paid_contact_fields_are_never_shared():
    """Skip-trace results are a per-account purchase. Sharing them across
    tenants would hand one account another's paid data."""
    for field in ("contact_name", "contact_phone", "contact_email"):
        assert field not in SHARED_COLS


def test_paid_demographic_fields_are_never_shared():
    for field in ("owner_age", "est_household_income", "life_stage",
                  "length_of_residence_years"):
        assert field not in SHARED_COLS


def test_crm_state_is_never_shared():
    """Status, assignment and score are tenant opinion, not facts about the
    parcel."""
    for field in ("status", "assigned_to", "lead_score", "score_grade",
                  "vertical", "archived_at", "estimated_job_value"):
        assert field not in SHARED_COLS


def test_shared_and_never_shared_do_not_overlap():
    assert not (set(SHARED_COLS) & _NEVER_SHARED)


def test_account_id_is_not_a_shared_column():
    """It identifies the tenant; copying it through the cache is meaningless."""
    assert "account_id" not in SHARED_COLS


def test_identity_columns_are_not_in_the_shared_set():
    """address/zip are the join key and are written explicitly, not copied."""
    for field in ("address", "zip", "address_norm", "id", "parcel_id"):
        assert field not in SHARED_COLS


def test_shared_columns_all_exist_on_properties():
    """Every shared column must be a real, writable properties column, or the
    generated INSERT/UPDATE would fail at runtime."""
    unknown = [c for c in SHARED_COLS if c not in ALL_COLS]
    assert not unknown, f"not writable properties columns: {unknown}"


def test_shared_columns_are_unique():
    assert len(SHARED_COLS) == len(set(SHARED_COLS))


def test_the_valuable_free_facts_are_shared():
    """The point of the cache: this is what a later tenant inherits free."""
    for field in ("latitude", "longitude", "year_built", "square_footage",
                  "estimated_value", "owner_name", "last_storm_date",
                  "permit_count_24mo", "hcad_neighborhood_code"):
        assert field in SHARED_COLS


# ── Generated SQL ─────────────────────────────────────────────────────────────

def test_promote_only_writes_shared_columns():
    cur = _FakeCursor(rowcount=5)
    assert parcels.promote(_FakeConn(cur), "77449", 1) == 5
    assert cur.params == ("77449", 1)
    for field in _NEVER_SHARED:
        assert f"{field} =" not in cur.sql, f"{field} must not be promoted"


def test_promote_never_overwrites_an_existing_cache_value():
    """COALESCE(pc.x, src.x) keeps what the cache already knows, so one
    account's data cannot clobber another's."""
    cur = _FakeCursor(rowcount=0)
    parcels.promote(_FakeConn(cur), "77449", 1)
    assert "COALESCE(pc.latitude, src.latitude)" in cur.sql


def test_sync_never_overwrites_a_tenant_value():
    cur = _FakeCursor(rowcount=0)
    parcels.sync(_FakeConn(cur), "77449", 1)
    assert "COALESCE(p.latitude, pc.latitude)" in cur.sql
    assert cur.params == ("77449", 1)


def test_seed_account_scopes_to_the_account_and_zip():
    cur = _FakeCursor(rowcount=2)
    assert parcels.seed_account(_FakeConn(cur), "77449", 7) == 2
    assert cur.params == ["77449", 7, 7, 7]


def test_seed_account_does_not_ship_rows_back_to_count_them():
    """RETURNING here cost 19s of 43s on 41,334 rows; rowcount is exact for a
    single INSERT statement."""
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7)
    assert "RETURNING 1" not in cur.sql


def test_seed_account_claims_customer_numbers_in_one_update():
    """properties has a BEFORE INSERT trigger that runs
    `UPDATE accounts SET next_customer_no = next_customer_no + 1` per row. On a
    41,334-row seed that measured 16.3s in the trigger plus 29.3s in the
    account_id FK check walking the resulting tuple-version chain. Supplying
    account_number makes the trigger a no-op."""
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7)
    assert "account_number" in cur.sql
    assert "next_customer_no = a.next_customer_no + counted.n" in cur.sql
    # Matches the trigger's own format (migration 0054): min width 5, widening.
    assert "GREATEST(5, LENGTH(" in cur.sql


def test_seed_account_only_inserts_parcels_the_account_lacks():
    """NOT EXISTS rather than ON CONFLICT, so a re-seed inserts nothing and
    burns no customer numbers from the block claim."""
    cur = _FakeCursor(rowcount=0)
    parcels.seed_account(_FakeConn(cur), "77449", 7)
    assert "NOT EXISTS" in cur.sql


def test_seed_account_applies_an_optional_limit_deterministically():
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7, limit=50)
    assert cur.params == ["77449", 7, 50, 7, 7]
    assert "LIMIT %s" in cur.sql
    # address_norm remains the tiebreak, so a repeated capped run takes the
    # same set — it is just no longer the *first* ordering term.
    assert "p.address_norm" in cur.sql


def test_capped_seed_takes_real_addresses_before_no_situs_parcels():
    """HCAD addresses vacant land with a zero house number, and "0 ACKLEY DR"
    sorts above "1 …" — so ordering by address_norm alone made a capped seed
    take nothing but parcels no vendor can enrich and nobody lives at."""
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7, limit=50)
    sql = " ".join(cur.sql.split())
    assert "!~ '^0+(\\s|$)'" in sql, "no-situs test missing from the seed order"
    assert "DESC, p.address_norm" in sql, "situs rank must precede the tiebreak"


@pytest.mark.parametrize("limit", [None, 0, -1])
def test_seed_account_ignores_a_missing_or_nonsense_limit(limit):
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7, limit=limit)
    assert cur.params == ["77449", 7, 7, 7]
    assert "LIMIT" not in cur.sql


def test_seed_account_refreshes_rows_the_account_already_had():
    """Existing rows are gap-filled by the sync UPDATE, which never overwrites a
    tenant's own value."""
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7)
    assert len(cur.statements) == 2, "expected the insert plus the sync refresh"
    assert "COALESCE(p.owner_name, pc.owner_name)" in cur.statements[1][0]


def test_ensure_from_hcad_collapses_duplicate_addresses():
    """Several HCAD accounts can share a site address; feeding both to
    ON CONFLICT DO UPDATE raises 'cannot affect row a second time'."""
    cur = _FakeCursor(rowcount=500)
    assert parcels.ensure_from_hcad(_FakeConn(cur), "77449") == 500
    assert "DISTINCT ON" in cur.sql
    assert cur.params == ("77449",)


def test_ensure_from_hcad_gap_fills_rather_than_overwrites():
    cur = _FakeCursor(rowcount=0)
    parcels.ensure_from_hcad(_FakeConn(cur), "77449")
    assert "COALESCE(parcels.year_built, EXCLUDED.year_built)" in cur.sql


def test_ensure_from_hcad_skips_blank_normalized_addresses():
    cur = _FakeCursor(rowcount=0)
    parcels.ensure_from_hcad(_FakeConn(cur), "77449")
    assert "axon_normalize_address(site_address) <> ''" in cur.sql


def test_link_existing_matches_on_normalized_address():
    cur = _FakeCursor(rowcount=3)
    assert parcels.link_existing(_FakeConn(cur), "77449", 1) == 3
    assert "axon_normalize_address(p.address) = pc.address_norm" in cur.sql
    assert "p.parcel_id IS NULL" in cur.sql


def test_seed_links_pre_existing_rows_before_seeding_them(monkeypatch):
    """Order matters: seed_account gap-fills existing rows via sync(), which
    joins on parcel_id. Linking after the seed makes that join match nothing, so
    a ZIP seeded by an older build would not pick up cached data until a second
    run — exactly the state a killed run leaves behind."""
    from pipeline import seed as seed_mod

    calls = []
    monkeypatch.setattr(seed_mod, "get_conn", lambda: _FakeConn(_FakeCursor()))
    monkeypatch.setattr(parcels, "ensure_from_hcad",
                        lambda c, z: calls.append("ensure") or 10)
    monkeypatch.setattr(parcels, "link_existing",
                        lambda c, z, a: calls.append("link") or 0)
    monkeypatch.setattr(parcels, "seed_account",
                        lambda c, z, a, limit=None: calls.append("seed") or 10)
    monkeypatch.setattr(parcels, "coverage",
                        lambda c, z: {"parcels": 10, "geocoded": 0})

    seed_mod._seed_from_parcels("77449", 1)
    assert calls.index("link") < calls.index("seed"), f"link must precede seed: {calls}"


@pytest.mark.parametrize("call,expected_commits", [
    (lambda c: parcels.ensure_from_hcad(c, "77449"), 1),
    (lambda c: parcels.promote(c, "77449", 1), 1),
    (lambda c: parcels.sync(c, "77449", 1), 1),
    (lambda c: parcels.link_existing(c, "77449", 1), 1),
    # seed_account commits its insert, then delegates the refresh to sync.
    (lambda c: parcels.seed_account(c, "77449", 1), 2),
])
def test_every_operation_commits(call, expected_commits):
    conn = _FakeConn(_FakeCursor(rows=[], rowcount=0))
    call(conn)
    assert conn.commits == expected_commits
