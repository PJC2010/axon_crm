"""Scripted fake psycopg2 connection for endpoint tests — no live DB.

Answers whitespace-normalized SQL by first matching substring, so a test
scripts only the statements it cares about (specific patterns first) and
survives unrelated statements being added around them. COMMIT/ROLLBACK land
in the same ``executed`` stream as the writes, so ordering (audit row before
commit) can be asserted. Lifted from tests/test_admin_accounts_create.py,
where the pattern started, so the admin test files share one copy.

A script entry is ``(substring, (cols, rows))`` or ``(substring, Exception)``;
``cols`` may be None for a statement that is never fetched from.
"""


class Cursor:
    def __init__(self, conn):
        self._conn = conn
        self._rows = []
        self.description = None
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def _respond(self, flat_sql):
        for pattern, response in self._conn.script:
            if pattern in flat_sql:
                if isinstance(response, Exception):
                    raise response
                cols, rows = response
                self.description = [(c,) for c in cols] if cols else None
                self._rows = list(rows)
                self.rowcount = len(self._rows)
                return
        self.description = None
        self._rows = []
        self.rowcount = 0

    def execute(self, sql, params=None):
        flat = " ".join(sql.split())
        self._conn.executed.append((flat, params))
        self._respond(flat)

    def executemany(self, sql, seq):
        self._conn.executed.append((" ".join(sql.split()), list(seq)))
        self._rows = []

    def fetchone(self):
        return self._rows.pop(0) if self._rows else None

    def fetchall(self):
        rows, self._rows = list(self._rows), []
        return rows


class Conn:
    def __init__(self, script=()):
        self.script = list(script)
        self.executed = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self, *a, **k):
        return Cursor(self)

    def commit(self):
        self.commits += 1
        self.executed.append(("COMMIT", None))

    def rollback(self):
        self.rollbacks += 1
        self.executed.append(("ROLLBACK", None))

    def close(self):
        self.closed = True


def sql_matching(conn, needle):
    """Every (sql, params) executed on ``conn`` whose text contains ``needle``."""
    return [(s, p) for s, p in conn.executed if needle in s]


def first_index(conn, needle):
    """Position of the first statement containing ``needle`` (for ordering)."""
    for i, (s, _) in enumerate(conn.executed):
        if needle in s:
            return i
    raise AssertionError(f"no statement containing {needle!r}")
