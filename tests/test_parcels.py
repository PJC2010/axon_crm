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


def test_ensure_from_hcad_writes_apn_with_the_shared_expression():
    """The stored parcel_apn must be produced by pipeline/parcel_id.py::
    sql_normalize_apn — the same expression that writes
    hcad_parcel_centroids.acct — because fill_coords_from_centroids joins the
    two on plain equality. This pins the shipped SQL to the parity-tested
    expression so the two cannot drift apart silently."""
    from pipeline.parcel_id import sql_normalize_apn
    cur = _FakeCursor(rowcount=0)
    parcels.ensure_from_hcad(_FakeConn(cur), "77449")
    assert sql_normalize_apn("h.acct") in cur.sql


def test_fill_coords_from_centroids_is_fill_only_plain_equality():
    cur = _FakeCursor(rowcount=7)
    assert parcels.fill_coords_from_centroids(_FakeConn(cur), "77449") == 7
    assert cur.params == (parcels.CENTROID_CONFIDENCE, "77449")
    # Fill-only: a coordinate promoted from a tenant's geocode is never touched.
    assert "p.latitude IS NULL" in cur.sql
    # Plain equality between the two pre-normalized stored forms. Wrapping
    # either side in a function would abandon the centroid PK at join time.
    assert "p.parcel_apn = c.acct" in cur.sql
    assert "'hcad_centroid'" in cur.sql
    # Provenance merges into enrichment_flags, same convention as every writer.
    assert "|| jsonb_build_object" in cur.sql


def test_fill_coords_leaves_geohash_to_the_tenant_backfill():
    """geohash/h3 are derived from lat/lng by the per-account backfills
    (pipeline/neighborhood.py, pipeline/geo_cluster_store.py) and promoted
    back into the cache — the SQL fill must not write placeholders into them."""
    cur = _FakeCursor(rowcount=0)
    parcels.fill_coords_from_centroids(_FakeConn(cur), "77449")
    assert "geohash" not in cur.sql
    assert "h3_r8" not in cur.sql


def test_seed_account_materialization_filters_default_off():
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7)
    assert "owner_occupied IS TRUE" not in cur.sql
    assert "COALESCE(p.year_built, 0) > 0" not in cur.sql
    assert "non_residential" not in cur.sql   # the residential guard is off too


def test_seed_account_owner_occupied_filter_is_literal_sql():
    """The predicates are literal SQL so the bind-parameter shape is identical
    whether the filters are on or off."""
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7, owner_occupied_only=True)
    assert "AND p.owner_occupied IS TRUE" in cur.sql
    assert cur.params == ["77449", 7, 7, 7]


def test_seed_account_built_only_uses_the_confirmed_structure_rule():
    """HCAD writes vacant-lot building_sqft as 0, so the test is > 0 rather
    than IS NOT NULL — the same rule as pipeline/db.py's paid-candidate
    ordering."""
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7, built_only=True)
    assert "COALESCE(p.year_built, 0) > 0" in cur.sql
    assert "COALESCE(p.square_footage, 0) > 0" in cur.sql
    assert cur.params == ["77449", 7, 7, 7]


def test_seed_account_residential_only_filters_and_adds_no_params():
    """The non-residential guard, applied at materialization.

    Reads the stored verdict (parcels.non_residential, migration 0077) rather
    than inlining the ~12KB rule — see test_residential.py's
    test_seed_filter_uses_the_shared_rule for the one-rule chain. Like the
    other two filters it must be literal SQL: psycopg2 binds %s positionally by
    statement-text order and filter_sql is interpolated ahead of the claim/INSERT
    params, so a bind param added here would silently shift every later one.
    """
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7, residential_only=True)
    # NULL-safe include: an unclassified parcel is seedable, never excluded.
    assert "AND NOT COALESCE(p.non_residential, FALSE)" in cur.sql
    # A literal '%' would be read as a placeholder once params are bound.
    assert "%s" in cur.sql and "%" not in cur.sql.replace("%s", "")
    assert cur.params == ["77449", 7, 7, 7]


def test_seed_from_parcels_actually_passes_residential_only(monkeypatch):
    """Regression guard: owner_occupied_only and built_only were added as
    kwargs and never wired to a caller, so they have never once run in
    production. This filter must not join them."""
    from pipeline import seed as seed_mod

    seen = {}
    monkeypatch.setattr(seed_mod, "get_conn", lambda: _FakeConn(_FakeCursor()))
    monkeypatch.setattr(seed_mod, "SEED_RESIDENTIAL_ONLY", True)
    monkeypatch.setattr(parcels, "ensure_from_hcad", lambda c, z: 10)
    monkeypatch.setattr(parcels, "fill_coords_from_centroids", lambda c, z: 0)
    monkeypatch.setattr(parcels, "link_existing", lambda c, z, a: 0)
    monkeypatch.setattr(parcels, "coverage",
                        lambda c, z: {"parcels": 10, "geocoded": 0})
    monkeypatch.setattr(
        parcels, "seed_account",
        lambda c, z, a, limit=None, residential_only=False:
            seen.update(residential_only=residential_only) or 10)

    seed_mod._seed_from_parcels("77449", 1)
    assert seen["residential_only"] is True


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


def test_ensure_from_hcad_city_is_situs_never_mail_city():
    """parcels.city is the parcel's own city (h.site_city, migration 0079).
    h.mail_city is where the OWNER gets mail: cached as the city once, an
    absentee owner's mailing city fanned out to every tenant's lead card and
    geocode query ("LAKE DALLAS" on a Houston lead). It may appear only inside
    the mailing_address concat."""
    cur = _FakeCursor(rowcount=0)
    parcels.ensure_from_hcad(_FakeConn(cur), "77449")
    assert "h.site_city" in cur.sql
    # Bare "h.mail_city," is the select-list form the bug used; the sanctioned
    # occurrence is wrapped as NULLIF(TRIM(h.mail_city), '') in the concat.
    assert "h.mail_city," not in cur.sql
    assert "TRIM(h.mail_city)" in cur.sql


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
    monkeypatch.setattr(parcels, "fill_coords_from_centroids",
                        lambda c, z: calls.append("fill") or 0)
    monkeypatch.setattr(parcels, "link_existing",
                        lambda c, z, a: calls.append("link") or 0)
    monkeypatch.setattr(parcels, "seed_account",
                        lambda c, z, a, limit=None, residential_only=False:
                            calls.append("seed") or 10)
    monkeypatch.setattr(parcels, "coverage",
                        lambda c, z: {"parcels": 10, "geocoded": 0})

    seed_mod._seed_from_parcels("77449", 1)
    # ensure → fill → link → seed: coordinates land in the cache before the
    # tenant materializes, so even a ZIP's first seed copies them into
    # properties; link precedes seed for the parcel_id join in sync().
    assert calls.index("ensure") < calls.index("fill") < calls.index("link") \
        < calls.index("seed"), f"wrong order: {calls}"


# ── Change guards + stored residential verdict (migration 0077) ──────────────

def test_ensure_from_hcad_skips_rows_that_would_not_change():
    """A re-run over an already-complete ZIP must write nothing: before the
    guard it rewrote all 47,531 rows of ZIP 77433 in 5.5s and left as many dead
    tuples. A row updates only when a fill lands or the flags merge adds a key."""
    cur = _FakeCursor(rowcount=0)
    parcels.ensure_from_hcad(_FakeConn(cur), "77449")
    sql = " ".join(cur.sql.split())
    assert "WHERE (parcels.city IS NULL AND EXCLUDED.city IS NOT NULL)" in sql
    # Every fill column is guarded — the list drives both SET and guard.
    for c in parcels._HCAD_FILL_COLS:
        assert f"(parcels.{c} IS NULL AND EXCLUDED.{c} IS NOT NULL)" in sql, c
    assert "NOT parcels.enrichment_flags @> EXCLUDED.enrichment_flags" in sql


def test_ensure_from_hcad_reclassifies_when_rows_changed():
    """New or changed parcels must get a residential verdict in the same
    transaction — the county build's only classification point."""
    cur = _FakeCursor(rowcount=500)
    conn = _FakeConn(cur)
    parcels.ensure_from_hcad(conn, "77449")
    all_sql = cur.all_sql()
    assert "non_residential = v.verdict" in all_sql
    assert "IS DISTINCT FROM v.verdict" in all_sql
    assert conn.commits == 1, "classification must share the upsert's commit"


class _SeqCursor(_FakeCursor):
    """_FakeCursor whose fetchone() returns each queued result once, so a test
    can express different answers for consecutive SELECTs (stamp lookup, then
    NULL probe)."""

    def __init__(self, results, rowcount=0):
        super().__init__(rowcount=rowcount)
        self._seq = list(results)

    def fetchone(self):
        return self._seq.pop(0) if self._seq else None


def test_ensure_from_hcad_self_heals_unclassified_rows():
    """rowcount=0 (nothing changed) and the rule stamp is FRESH, but a NULL
    verdict survives in the ZIP: the probe must find it and the classification
    must still run, so a future writer that forgets the pass cannot silently
    disable the seed filter."""
    cur = _SeqCursor([(parcels._rule_hash(),), (1,)], rowcount=0)
    parcels.ensure_from_hcad(_FakeConn(cur), "77449")
    assert "non_residential IS NULL" in cur.all_sql()
    assert "non_residential = v.verdict" in cur.all_sql()


def test_ensure_from_hcad_reclassifies_when_the_rule_changed():
    """A stale (or missing) rule stamp forces reclassification even when no
    parcel data changed — editing residential.py's token lists or overriding a
    threshold must reach already-classified ZIPs on their next touch, exactly
    the freshness the old inline-per-seed filter had."""
    cur = _SeqCursor([("stale-hash",)], rowcount=0)
    parcels.ensure_from_hcad(_FakeConn(cur), "77449")
    all_sql = cur.all_sql()
    assert "non_residential = v.verdict" in all_sql
    assert "parcel_rule_stamps" in all_sql, "must re-stamp after classifying"


def test_ensure_from_hcad_skips_classification_when_all_fresh():
    """Steady state — nothing changed, stamp fresh, no NULLs: the whole pass
    is two index-only glances and zero writes."""
    cur = _SeqCursor([(parcels._rule_hash(),), None], rowcount=0)
    parcels.ensure_from_hcad(_FakeConn(cur), "77449")
    assert "non_residential = v.verdict" not in cur.all_sql()


def test_promote_skips_rows_it_cannot_fill():
    """promote() is fill-only, so a row can change only where the cache is NULL
    and the tenant has a value — the guard says exactly that, and stops every
    pipeline run rewriting a whole ZIP's parcels for nothing."""
    cur = _FakeCursor(rowcount=0)
    parcels.promote(_FakeConn(cur), "77449", 1)
    sql = " ".join(cur.sql.split())
    assert "(pc.latitude IS NULL AND src.latitude IS NOT NULL)" in sql
    assert "(pc.owner_name IS NULL AND src.owner_name IS NOT NULL)" in sql


def test_promote_reclassifies_only_when_something_landed():
    """Promoted facts (property_type, owner_name, ...) are verdict inputs."""
    cur = _FakeCursor(rowcount=3)
    parcels.promote(_FakeConn(cur), "77449", 1)
    assert "non_residential = v.verdict" in cur.all_sql()
    assert "parcel_rule_stamps" in cur.all_sql()

    cur = _FakeCursor(rowcount=0)
    parcels.promote(_FakeConn(cur), "77449", 1)
    assert "non_residential" not in cur.all_sql()


def test_sync_skips_rows_it_cannot_fill():
    """Every skipped row keeps updated_at honest (inbound SMS matching orders
    by it) and skips maintenance on all of properties' ~30 indexes."""
    cur = _FakeCursor(rowcount=0)
    parcels.sync(_FakeConn(cur), "77449", 1)
    sql = " ".join(cur.sql.split())
    assert "(p.latitude IS NULL AND pc.latitude IS NOT NULL)" in sql


def test_uncapped_seed_does_not_sort():
    """Ordering exists to pick WHICH parcels a capped seed takes; an uncapped
    seed takes all of them, so both sorts (selection + window numbering) were
    pure waste — two ~13MB external merges per seed at default work_mem."""
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7)
    assert "ORDER BY" not in cur.sql
    assert "ROW_NUMBER() OVER ()" in cur.sql


def test_capped_seed_still_sorts_deterministically():
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7, limit=50)
    assert "ORDER BY" in cur.sql
    assert "ROW_NUMBER() OVER (ORDER BY np.address_norm)" in cur.sql


def test_seed_statements_raise_work_mem_locally(monkeypatch):
    """SET LOCAL in the same statement string: scoped to the seed transaction,
    invisible to API request connections, and the FakeCursor first-statement
    convention keeps holding (it is a prefix, not a separate execute)."""
    import config
    monkeypatch.setattr(config, "SEED_WORK_MEM_MB", 64)
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7)
    assert cur.sql.lstrip().startswith("SET LOCAL work_mem = '64MB';")

    cur = _FakeCursor(rowcount=0)
    parcels.ensure_from_hcad(_FakeConn(cur), "77449")
    assert cur.sql.lstrip().startswith("SET LOCAL work_mem = '64MB';")


def test_work_mem_override_can_be_disabled(monkeypatch):
    import config
    monkeypatch.setattr(config, "SEED_WORK_MEM_MB", 0)
    cur = _FakeCursor(rowcount=1)
    parcels.seed_account(_FakeConn(cur), "77449", 7)
    assert "SET LOCAL" not in cur.sql


@pytest.mark.parametrize("call,expected_commits", [
    (lambda c: parcels.ensure_from_hcad(c, "77449"), 1),
    (lambda c: parcels.fill_coords_from_centroids(c, "77449"), 1),
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
