"""FastAPI dependency: yields a psycopg2 connection, closes it after the request."""
import psycopg2
import psycopg2.extras
from config import DATABASE_URL


def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    try:
        yield conn
    finally:
        conn.close()


def dict_fetchall(cur) -> list[dict]:
    """Return all rows from a cursor as a list of dicts."""
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, row)) for row in cur.fetchall()]


def dict_fetchone(cur) -> dict | None:
    cols = [d[0] for d in cur.description]
    row = cur.fetchone()
    return dict(zip(cols, row)) if row else None
