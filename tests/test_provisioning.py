"""Tests for business-type pack provisioning (api/accounts.py): stage/field/
workflow seeding, plan-bounded module maps, and idempotent re-seeding.
Fake-conn style — no live DB."""
from api.accounts import (
    DEFAULT_STAGES, create_account,
    seed_business_type_fields, seed_business_type_stages, seed_business_type_workflows,
)


class _ScriptedCursor:
    def __init__(self, conn):
        self._conn = conn
        self._current = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, list(params) if params is not None else None))
        self._current = self._conn.responses.pop(0) if self._conn.responses else []

    def executemany(self, sql, seq):
        self._conn.executed.append((sql, [list(p) for p in seq]))
        self._current = []

    def fetchall(self):
        return list(self._current)

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None


class _ScriptedConn:
    def __init__(self, responses):
        self.responses = list(responses)
        self.executed = []

    def cursor(self):
        return _ScriptedCursor(self)

    def commit(self):
        pass


class TestCreateAccount:
    def test_insurance_account_gets_pack_stages_and_fields(self):
        conn = _ScriptedConn([
            [(11,)],   # accounts INSERT RETURNING id
            [],        # pipeline_stages executemany
            [],        # account_plans INSERT
            [(1,)], [(2,)], [(3,)],   # three field-def inserts (RETURNING id)
        ])
        account_id = create_account(conn, "Acme Insurance", business_type="insurance_agency")
        assert account_id == 11

        stages_sql, stage_rows = conn.executed[1]
        assert "pipeline_stages" in stages_sql
        assert [r[1] for r in stage_rows] == ["prospect", "quoted", "bound", "renewal", "lost"]

        field_sqls = [sql for sql, _ in conn.executed if "record_field_defs" in sql]
        assert len(field_sqls) == 3
        assert all("ON CONFLICT (account_id, key) DO NOTHING" in s for s in field_sqls)

    def test_home_services_keeps_classic_stages(self):
        conn = _ScriptedConn([[(12,)], [], []])
        create_account(conn, "Acme Epoxy")   # default business type, no fields
        _, stage_rows = conn.executed[1]
        assert [r[1] for r in stage_rows] == [s[0] for s in DEFAULT_STAGES]
        assert not any("record_field_defs" in sql for sql, _ in conn.executed)

    def test_modules_bounded_by_plan(self):
        conn = _ScriptedConn([[(13,)], [], [], [(1,)], [(2,)], [(3,)]])
        create_account(conn, "Acme Insurance", plan_name="starter", business_type="insurance_agency")
        plans_sql, plans_params = conn.executed[2]
        assert "account_plans" in plans_sql
        modules = plans_params[2].adapted   # psycopg2 Json wrapper
        # starter grants nothing, so even wanted modules stay off.
        assert not any(modules.values())


class TestSeedWorkflows:
    def test_seeds_all_when_none_exist(self):
        # For each of the 4 insurance rules: name-exists check (empty) + INSERT.
        conn = _ScriptedConn([[], [], [], [], [], [], [], []])
        created = seed_business_type_workflows(conn, 11, "insurance_agency", user_id=9)
        assert created == 4
        inserts = [p for sql, p in conn.executed if "INSERT INTO workflow_rules" in sql]
        assert len(inserts) == 4
        assert all(p[-2:] == [9, 11] for p in inserts)   # created_by, account_id

    def test_skips_existing_names(self):
        conn = _ScriptedConn([
            [(1,)],    # rule 1 exists
            [], [],    # rule 2 missing → insert
            [(1,)],    # rule 3 exists
            [], [],    # rule 4 missing → insert
        ])
        created = seed_business_type_workflows(conn, 11, "insurance_agency", user_id=9)
        assert created == 2


class TestSeedStages:
    def test_only_missing_keys_added_never_default(self):
        conn = _ScriptedConn([
            [(1,)],    # prospect exists
            [], [],    # quoted missing → insert
            [(1,)],    # bound exists
            [], [],    # renewal missing → insert
            [(1,)],    # lost exists
        ])
        created = seed_business_type_stages(conn, 11, "insurance_agency")
        assert created == 2
        inserts = [(sql, p) for sql, p in conn.executed if "INSERT INTO pipeline_stages" in sql]
        assert all("FALSE" in sql for sql, _ in inserts)   # never a second default

    def test_fields_idempotent_count(self):
        # Two of three fields already exist (RETURNING id yields nothing).
        conn = _ScriptedConn([[], [(5,)], []])
        created = seed_business_type_fields(conn, 11, "insurance_agency")
        assert created == 1
