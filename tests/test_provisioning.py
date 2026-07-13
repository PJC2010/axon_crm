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
    # Insurance seeds its 2 default message templates first (INSERT … RETURNING
    # id each), then its 5 rules (name-exists check + INSERT each).
    def test_seeds_all_when_none_exist(self):
        conn = _ScriptedConn([
            [(201,)], [(202,)],                          # template inserts return ids
            [], [], [], [], [], [], [], [], [], [],     # 5 × (exists-check + insert)
        ])
        created = seed_business_type_workflows(conn, 11, "insurance_agency", user_id=9)
        assert created == 5
        inserts = [p for sql, p in conn.executed if "INSERT INTO workflow_rules" in sql]
        assert len(inserts) == 5
        assert all(p[-2:] == [9, 11] for p in inserts)   # created_by, account_id

    def test_skips_existing_names(self):
        conn = _ScriptedConn([
            [(201,)], [(202,)], [(203,)],   # template inserts (incl. website auto-reply)
            [(1,)],    # rule 1 exists
            [], [],    # rule 2 missing → insert
            [(1,)],    # rule 3 exists
            [], [],    # rule 4 missing → insert
            [(1,)],    # rule 5 exists
        ])
        created = seed_business_type_workflows(conn, 11, "insurance_agency", user_id=9)
        assert created == 2

    def test_template_names_resolve_to_account_ids(self):
        import json
        conn = _ScriptedConn([
            [(201,)], [(202,)], [(203,)],   # sms 201, email 202, auto-reply 203
            [], [], [], [], [], [], [], [], [], [],
        ])
        seed_business_type_workflows(conn, 11, "insurance_agency", user_id=9)
        inserts = [p for sql, p in conn.executed if "INSERT INTO workflow_rules" in sql]
        send_rules = [p for p in inserts if p[3] == "send_template"]
        assert len(send_rules) == 1
        cfg = json.loads(send_rules[0][4])
        assert cfg["templates"] == {"sms": 201, "email": 202}
        assert cfg["delivery"] == "sms_first"
        assert "template_names" not in cfg

    def test_existing_template_reused_not_duplicated(self):
        import json
        conn = _ScriptedConn([
            [],          # sms template insert conflicts (already exists)
            [(301,)],    # …fetch existing id
            [(302,)],    # email template inserted fresh
            [(303,)],    # website auto-reply inserted fresh
            [], [], [], [], [], [], [], [], [], [],
        ])
        seed_business_type_workflows(conn, 11, "insurance_agency", user_id=9)
        template_inserts = [sql for sql, _ in conn.executed if "INSERT INTO message_templates" in sql]
        assert len(template_inserts) == 3
        assert all("ON CONFLICT" in sql for sql in template_inserts)
        inserts = [p for sql, p in conn.executed if "INSERT INTO workflow_rules" in sql]
        cfg = json.loads(next(p for p in inserts if p[3] == "send_template")[4])
        assert cfg["templates"] == {"sms": 301, "email": 302}


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
