"""Route-level guards for the scored-lead reveal quota (positioning plan
Phase 3). The pure logic lives in tests/test_scoring_quota.py; this pins the
wiring on the surfaces the adversarial review found leaking — the ones that
return or mutate a candidate's identity fields outside the meter."""
import pytest
from fastapi import HTTPException

from api.routes import pipeline as pipeline_route
from api.routes import data_quality as dq_route
from api.routes.pipeline import JobValueUpdate

USER = {"id": 9, "account_id": 3, "role": "rep"}


class _Cursor:
    """Pattern-matched fake cursor: canned rows keyed by a SQL substring."""
    def __init__(self, conn):
        self._conn = conn
        self._rows = []

    def __enter__(self): return self
    def __exit__(self, *exc): return False

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self._conn.executed.append(s)
        self._rows = []
        for frag, rows in self._conn.script:
            if frag in s:
                self._rows = rows() if callable(rows) else rows
                return
        raise AssertionError(f"unscripted SQL: {s[:90]}")

    @property
    def description(self):
        rows = self._rows
        if rows and isinstance(rows[0], dict):
            return [(k,) for k in rows[0].keys()]
        return []

    def fetchone(self):
        # dict_fetchone/dict_fetchall (api/deps.py) zip description with tuples,
        # so hand back tuples when the canned row is a dict.
        rows = self.fetchall()
        return rows[0] if rows else None

    def fetchall(self):
        rows = self._rows
        if rows and isinstance(rows[0], dict):
            return [tuple(r.values()) for r in rows]
        return list(rows)


class _Conn:
    def __init__(self, script):
        self.script = script          # list of (sql_substring, rows)
        self.executed = []
        self.commits = 0

    def cursor(self, *a, **k): return _Cursor(self)
    def commit(self): self.commits += 1
    def rollback(self): pass


def _dict_rows(rows):
    """dict_fetchall reads .description; simpler to hand back dicts via a shim."""
    return rows


# ── PATCH /leads/{id}/job-value ───────────────────────────────────────────────

def test_job_value_refuses_masked_candidate_past_allowance():
    # starter plan, allowance 1, already spent on another lead → this scored
    # 'new' engine candidate is past the allowance and must 403, never UPDATE.
    conn = _Conn([
        ("FROM account_plans", [("starter", 1)]),
        ("SELECT id, lead_score, status, lead_source FROM properties",
         [{"id": 55, "lead_score": 91.0, "status": "new", "lead_source": None}]),
        ("COUNT(*) FROM scoring_reveals", [(1,)]),        # allowance already spent
        ("SELECT property_id FROM scoring_reveals", []),  # this lead not revealed
    ])
    with pytest.raises(HTTPException) as exc:
        pipeline_route.update_job_value(55, JobValueUpdate(estimated_job_value=0),
                                        user=USER, db=conn)
    assert exc.value.status_code == 403
    assert exc.value.detail["quota"] is True
    assert not any("UPDATE properties" in s for s in conn.executed)


def test_job_value_allows_own_book_lead_without_consuming():
    # A csv_import lead is the tenant's own book: never a candidate, so the
    # edit goes through with no reveal check beyond the provenance short-circuit.
    card = {"id": 55, "address": "1 A St", "owner_name": "Mine", "contact_name": None,
            "contact_phone": None, "lead_score": 91.0, "score_grade": "A",
            "estimated_job_value": 0, "status": "new", "vertical": None,
            "zip": "77002", "stage_moved_at": None, "lead_source": "csv_import"}
    conn = _Conn([
        ("FROM account_plans", [("starter", 1)]),
        ("SELECT id, lead_score, status, lead_source FROM properties",
         [{"id": 55, "lead_score": 91.0, "status": "new", "lead_source": "csv_import"}]),
        ("UPDATE properties SET estimated_job_value", [card]),
    ])
    out = pipeline_route.update_job_value(55, JobValueUpdate(estimated_job_value=0),
                                          user=USER, db=conn)
    assert out["owner_name"] == "Mine"
    assert any("UPDATE properties" in s for s in conn.executed)


def test_job_value_unlimited_plan_skips_the_probe():
    card = {"id": 55, "address": "1 A St", "owner_name": "Anyone",
            "estimated_job_value": 0, "status": "new", "lead_source": None,
            "contact_name": None, "contact_phone": None, "lead_score": 91.0,
            "score_grade": "A", "vertical": None, "zip": "77002", "stage_moved_at": None}
    conn = _Conn([
        ("FROM account_plans", [("pro", None)]),
        ("UPDATE properties SET estimated_job_value", [card]),
    ])
    out = pipeline_route.update_job_value(55, JobValueUpdate(estimated_job_value=0),
                                          user=USER, db=conn)
    assert out["owner_name"] == "Anyone"
    # No candidacy probe on an unlimited plan.
    assert not any("lead_source FROM properties" in s for s in conn.executed)


# ── GET /property-data/non-residential (sample masking) ───────────────────────

def test_non_residential_masks_candidate_samples(monkeypatch):
    # audit() returns sample rows carrying account_number/address/owner_name.
    # A scored 'new' engine sample past the allowance must come back masked;
    # a worked one (status != 'new') stays visible.
    samples = [
        {"id": 201, "account_number": "C-201", "address": "10 Elm St",
         "owner_name": "Cand One", "lead_score": 80.0, "status": "new",
         "reasons": ["vacant_lot"]},
        {"id": 202, "account_number": "C-202", "address": "20 Oak St",
         "owner_name": "Worked Two", "lead_score": 75.0, "status": "contacted",
         "reasons": ["church_owner"]},
    ]
    monkeypatch.setattr(dq_route, "get_scoring_limit", lambda acct, db: 25)

    def fake_apply(db, acct, rows, limit, consume=True):
        # 201 unrevealed candidate → masked; 202 not a candidate → untouched.
        from api.scoring_quota import mask_lead_row, is_quota_candidate
        out = [mask_lead_row(r) if is_quota_candidate(r) else r for r in rows]
        return out, None
    monkeypatch.setattr(dq_route.scoring_quota, "apply_quota", fake_apply)

    import pipeline.property_audit as pa
    monkeypatch.setattr(pa, "audit",
                        lambda *a, **k: {"samples": [dict(s) for s in samples], "counts": {}})

    # The route now runs the audit under a tightened statement_timeout
    # (api/deps.py::soft_query), so the connection must at least hand out a
    # cursor. `set_config` is the only statement the route issues itself; the
    # audit behind it is monkeypatched above.
    db = _Conn([("set_config", [])])
    out = dq_route.property_data_non_residential(zip=None, sample_limit=10, user=USER, db=db, _mod=USER)
    s = {r.get("id") or r.get("_id"): r for r in out["samples"]}
    got = out["samples"]
    masked = [r for r in got if r["owner_name"] is None]
    visible = [r for r in got if r["owner_name"] is not None]
    assert len(masked) == 1 and masked[0]["account_number"] is None
    assert masked[0]["address"] == "1X Elm St"
    assert visible and visible[0]["owner_name"] == "Worked Two"
    # reasons survive masking (computed before, non-sensitive)
    assert masked[0]["reasons"] == ["vacant_lot"]


# ── GET /property-data/discrepancies (audit value masking) ────────────────────

def test_discrepancies_masks_stored_and_remote_of_candidates(monkeypatch):
    # The audit's own stored_value/remote_value carry the withheld identity when
    # the audited field is owner_name/address; they must be nulled for a masked
    # candidate, not just the joined p.address/p.owner_name.
    items = [
        {"id": 1, "property_id": 501, "field": "owner_name",
         "stored_value": "SMITH JOHN", "remote_value": "John Smith",
         "resolution": "kept", "checked_at": None, "address": "1842 Westheimer Rd",
         "zip": "77006", "owner_name": "SMITH JOHN",
         "lead_score": 92.0, "status": "new", "lead_source": None},          # engine candidate
        {"id": 2, "property_id": 502, "field": "estimated_value",
         "stored_value": "100000", "remote_value": "120000",
         "resolution": "kept", "checked_at": None, "address": "9 Mine Ave",
         "zip": "77006", "owner_name": "My Own",
         "lead_score": 88.0, "status": "new", "lead_source": "csv_import"},   # own book
    ]
    monkeypatch.setattr(dq_route, "get_scoring_limit", lambda acct, db: 25)

    def fake_apply(db, acct, rows, limit, consume=True):
        from api.scoring_quota import mask_lead_row, is_quota_candidate
        return [mask_lead_row(r) if is_quota_candidate(r) else r for r in rows], None
    monkeypatch.setattr(dq_route.scoring_quota, "apply_quota", fake_apply)

    import pipeline.backfill as bf
    monkeypatch.setattr(bf, "list_discrepancies", lambda *a, **k: [dict(i) for i in items])
    monkeypatch.setattr(bf, "discrepancy_summary", lambda *a, **k: {})

    out = dq_route.property_data_discrepancies(field=None, zip=None, limit=100,
                                               user=USER, db=object(), _mod=USER)
    cand = next(i for i in out["items"] if i["property_id"] == 501)
    own = next(i for i in out["items"] if i["property_id"] == 502)
    # masked engine candidate: audit values AND joined identity all withheld
    assert cand["stored_value"] is None and cand["remote_value"] is None
    assert cand["owner_name"] is None and cand["address"] == "18XX Westheimer Rd"
    # own-book row untouched (provenance)
    assert own["stored_value"] == "100000" and own["owner_name"] == "My Own"
    # candidacy helper columns stripped from the response
    assert "lead_source" not in cand and "status" not in cand and "lead_score" not in cand


# ── GET /leads/{id}/score-explanation ─────────────────────────────────────────

def test_score_explanation_refuses_masked_candidate():
    # The factor text embeds the property facts the mask withholds (year
    # built, equity, sale recency), so past the allowance the breakdown must
    # 403 with the upgrade shape rather than explain a masked lead.
    from api.routes import leads as leads_route
    conn = _Conn([
        ("SELECT * FROM properties", [{"id": 55, "lead_score": 91.0, "status": "new",
                                       "lead_source": None, "zip": "77002",
                                       "state": "TX", "vertical": None}]),
        ("FROM account_plans", [("starter", 1)]),
        ("COUNT(*) FROM scoring_reveals", [(1,)]),        # allowance already spent
        ("SELECT property_id FROM scoring_reveals", []),  # this lead not revealed
    ])
    with pytest.raises(HTTPException) as exc:
        leads_route.get_score_explanation(55, db=conn, user=USER)
    assert exc.value.status_code == 403
    assert exc.value.detail["quota"] is True
    assert exc.value.detail["upgrade"] is True


# ── GET /map/properties (pin dropping) ────────────────────────────────────────

def test_map_properties_drops_masked_candidates(monkeypatch):
    from api.routes import map as map_route
    pins = [
        {"id": 1, "address": "1 A St", "latitude": 29.7, "longitude": -95.4,
         "lead_score": 90.0, "score_grade": "A", "status": "new",
         "lead_source": None, "signals": []},                       # engine candidate
        {"id": 2, "address": "2 B St", "latitude": 29.8, "longitude": -95.5,
         "lead_score": 80.0, "score_grade": "B", "status": "new",
         "lead_source": "csv_import", "signals": []},               # own book
    ]
    conn = _Conn([("SELECT id, address, latitude, longitude", pins)])
    monkeypatch.setattr(map_route, "get_scoring_limit", lambda acct, db: 25)

    def fake_apply(db, acct, rows, limit, consume=True):
        from api.scoring_quota import mask_lead_row, is_quota_candidate
        return [mask_lead_row(r) if is_quota_candidate(r) else r for r in rows], None
    monkeypatch.setattr(map_route.scoring_quota, "apply_quota", fake_apply)

    out = map_route.map_properties(min_lat=29.0, min_lng=-96.0, max_lat=30.0, max_lng=-95.0,
                                   vertical=None, status=None, signal_days=60, limit=500,
                                   db=conn, user={"account_id": 3})
    # Engine candidate past allowance is dropped; own-book pin survives.
    ids = {p.id for p in out}
    assert ids == {2}
