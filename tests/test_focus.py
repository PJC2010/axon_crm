"""Focus view (pipeline/focus.py + the GET /leads wiring): the adaptive
grade-band cutoff, the candidate-shaped query predicate, the recompute writer,
and the list endpoint's default-on / show-all behavior. Pattern-matched fake
connection, no database."""
import pytest

from config import GRADE_BANDS
from pipeline import focus


class _Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []

    def __enter__(self): return self
    def __exit__(self, *exc): return False

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self._conn.executed.append((s, list(params) if params else []))
        self._rows = []
        for frag, rows in self._conn.script:
            if frag in s:
                self._rows = rows() if callable(rows) else rows
                return
        raise AssertionError(f"unscripted SQL: {s[:110]}")

    @property
    def description(self):
        rows = self._rows
        if rows and isinstance(rows[0], dict):
            return [(k,) for k in rows[0].keys()]
        return []

    def fetchone(self):
        rows = self.fetchall()
        return rows[0] if rows else None

    def fetchall(self):
        rows = self._rows
        if rows and isinstance(rows[0], dict):
            return [tuple(r.values()) for r in rows]
        return list(rows)


class _Conn:
    def __init__(self, script):
        self.script = script
        self.executed = []       # (normalized sql, params) pairs
        self.commits = 0

    def cursor(self, *a, **k): return _Cursor(self)
    def commit(self): self.commits += 1
    def rollback(self): pass


# ── pure logic ────────────────────────────────────────────────────────────────

def test_focus_floor_boundaries():
    assert focus.focus_floor(0) == 50
    assert focus.focus_floor(49) == 50
    assert focus.focus_floor(500) == 50
    assert focus.focus_floor(1000) == 100      # 10% takes over
    assert focus.focus_floor(10_000) == 500    # capped
    assert focus.focus_floor(200_000) == 500


def test_cutoff_rich_book_stops_at_the_top_band():
    counts = {75.0: 120, 55.0: 300, 35.0: 400}
    assert focus.compute_focus_cutoff(counts, 400) == 75.0


def test_cutoff_widens_when_the_top_band_is_thin():
    # A ZIP with almost no A's must widen to B instead of showing 5 leads.
    counts = {75.0: 5, 55.0: 80, 35.0: 200}
    assert focus.compute_focus_cutoff(counts, 200) == 55.0
    counts = {75.0: 5, 55.0: 20, 35.0: 90}
    assert focus.compute_focus_cutoff(counts, 200) == 35.0


def test_cutoff_none_for_thin_books_and_when_only_everything_reaches():
    # Fewer scored candidates than the floor → focus off.
    assert focus.compute_focus_cutoff({75.0: 20, 55.0: 30, 35.0: 30}, 30) is None
    # Only the bottom "everything" band reaches the floor → a cutoff there
    # would filter nothing; focus off.
    assert focus.compute_focus_cutoff({75.0: 5, 55.0: 20, 35.0: 40}, 600) is None


def test_focus_condition_shape():
    cond = focus.focus_condition("p.")
    assert cond.count("%s") == 1                     # exactly the cutoff param
    assert "p.lead_score >= %s" in cond
    assert "p.lead_score IS NULL" in cond            # unscored rows always show
    assert "COALESCE(p.status, 'new') <> 'new'" in cond   # worked leads always show
    assert "NOT (p.lead_source IS NULL" in cond      # own-book rows always show
    assert "'csv_import'" in cond


def test_grade_for_cutoff_maps_grade_bands():
    assert focus.grade_for_cutoff(75.0) == "A"
    assert focus.grade_for_cutoff(55.0) == "B"
    assert focus.grade_for_cutoff(35.0) == "C"
    assert focus.grade_for_cutoff(None) is None


# ── recompute writer ──────────────────────────────────────────────────────────

def _band_thresholds():
    return [float(t) for t, _g in GRADE_BANDS if t > 0]


def test_recompute_interpolates_thresholds_and_stores_the_cutoff():
    # Counts per band (75/55/35) + total, in SELECT order.
    conn = _Conn([
        ("FROM properties", [(120, 300, 400, 400)]),
        ("UPDATE accounts SET focus_score_cutoff", []),
    ])
    assert focus.recompute_focus(conn, 3) == 75.0
    agg_sql = next(s for s, _p in conn.executed if "FROM properties" in s)
    for t in _band_thresholds():
        assert f"lead_score >= {t}" in agg_sql       # from GRADE_BANDS, not hard-coded
    assert "account_id = %s" in agg_sql              # tenant-scoped
    upd_sql, upd_params = next((s, p) for s, p in conn.executed if "UPDATE accounts" in s)
    assert upd_params == [75.0, 3]
    assert conn.commits == 1


def test_recompute_stores_null_for_a_thin_account():
    conn = _Conn([
        ("FROM properties", [(3, 8, 10, 12)]),
        ("UPDATE accounts SET focus_score_cutoff", []),
    ])
    assert focus.recompute_focus(conn, 3) is None
    _s, params = next((s, p) for s, p in conn.executed if "UPDATE accounts" in s)
    assert params == [None, 3]


def test_get_focus_cutoff_degrades_to_off():
    def _boom():
        raise RuntimeError("db down")
    assert focus.get_focus_cutoff(_Conn([("FROM accounts", _boom)]), 3) is None
    assert focus.get_focus_cutoff(_Conn([("FROM accounts", [])]), 3) is None
    assert focus.get_focus_cutoff(_Conn([("FROM accounts", [(55.0,)])]), 3) == 55.0


# ── GET /leads wiring ─────────────────────────────────────────────────────────

USER = {"id": 9, "account_id": 3, "role": "rep"}


def _list_leads(conn, **overrides):
    from api.routes import leads as leads_route
    kwargs = dict(zip=None, grade=None, vertical=None, status=None,
                  min_value=None, max_value=None, neighborhood=None,
                  min_neighborhood_pctile=None, sort="score", page=1,
                  page_size=50, show_all=False, db=conn, user=USER)
    kwargs.update(overrides)
    return leads_route.list_leads(**kwargs)


def test_list_leads_defaults_to_focus_when_cutoff_set():
    conn = _Conn([
        ("SELECT focus_score_cutoff FROM accounts", [(55.0,)]),
        ("COUNT(*) FILTER", [(1000, 214)]),          # (all_total, focus_total)
        ("LEFT JOIN lead_geo_scores", []),
        ("FROM account_plans", [("pro", None)]),     # unlimited → no masking
    ])
    page = _list_leads(conn)
    assert page.total == 214
    assert page.focus is not None
    assert page.focus.active is True
    assert page.focus.grade == "B"
    assert page.focus.shown_total == 214 and page.focus.all_total == 1000
    # psycopg2 binds %s in statement-text order: the FILTER's cutoff sits in
    # the SELECT list, BEFORE the WHERE's account_id.
    _count_sql, count_params = next((s, p) for s, p in conn.executed
                                    if "COUNT(*) FILTER" in s)
    assert count_params == [55.0, 3]
    rows_sql, rows_params = next((s, p) for s, p in conn.executed
                                 if "LEFT JOIN lead_geo_scores" in s)
    assert "p.lead_score >= %s" in rows_sql
    # In the rows query the cutoff is appended to the WHERE — after account_id,
    # before LIMIT/OFFSET.
    assert rows_params == [3, 55.0, 50, 0]


def test_list_leads_show_all_lifts_the_focus_filter():
    conn = _Conn([
        ("SELECT focus_score_cutoff FROM accounts", [(55.0,)]),
        ("COUNT(*) FILTER", [(1000, 214)]),
        ("LEFT JOIN lead_geo_scores", []),
        ("FROM account_plans", [("pro", None)]),
    ])
    page = _list_leads(conn, show_all=True)
    assert page.total == 1000
    assert page.focus.active is False
    rows_sql, _ = next((s, p) for s, p in conn.executed
                       if "LEFT JOIN lead_geo_scores" in s)
    assert "p.lead_score >= %s" not in rows_sql


def test_list_leads_without_cutoff_is_byte_identical_to_before():
    # Protects the 0084 index contract: no cutoff → no focus predicate, no
    # FILTER count, plain COUNT(*), and no focus block in the response.
    conn = _Conn([
        ("SELECT focus_score_cutoff FROM accounts", [(None,)]),
        ("SELECT COUNT(*) FROM properties p", [(1000,)]),
        ("LEFT JOIN lead_geo_scores", []),
        ("FROM account_plans", [("pro", None)]),
    ])
    page = _list_leads(conn)
    assert page.total == 1000
    assert page.focus is None
    count_sql, _ = next((s, p) for s, p in conn.executed if "COUNT(*)" in s)
    assert "FILTER" not in count_sql
    rows_sql, rows_params = next((s, p) for s, p in conn.executed
                                 if "LEFT JOIN lead_geo_scores" in s)
    assert "lead_score >= %s" not in rows_sql
    assert rows_params == [3, 50, 0]                 # account_id, LIMIT, OFFSET
