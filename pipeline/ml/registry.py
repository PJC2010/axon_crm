"""
Model registry — persist / activate / load model artifacts (model_versions table).

A "scope" is either 'global' (one pooled model trained PII-free across every
account) or 'account:<id>' (a tenant-specific model). At most one version per scope
is active at a time (enforced by a partial unique index in migration 034).
"""
from __future__ import annotations

import logging

import psycopg2.extras

from pipeline.ml.model import LogisticModel

log = logging.getLogger(__name__)


def global_scope() -> str:
    return "global"


def account_scope(account_id: int) -> str:
    return f"account:{account_id}"


def save_and_activate(
    conn,
    scope: str,
    account_id: int | None,
    model: LogisticModel,
    metrics: dict,
    n_train: int,
    n_test: int,
) -> int:
    """Insert a new version and make it the active champion for its scope."""
    with conn.cursor() as cur:
        # Deactivate the current champion first so the partial unique index holds.
        cur.execute(
            "UPDATE model_versions SET is_active = FALSE WHERE scope = %s AND is_active",
            (scope,),
        )
        cur.execute(
            """
            INSERT INTO model_versions
                (scope, account_id, algo, artifact, metrics, n_train, n_test, is_active)
            VALUES (%s, %s, %s, %s, %s, %s, %s, TRUE)
            RETURNING id
            """,
            (
                scope, account_id, model.algo,
                psycopg2.extras.Json(model.to_dict()),
                psycopg2.extras.Json(metrics),
                n_train, n_test,
            ),
        )
        version_id = cur.fetchone()[0]
    conn.commit()
    log.info("Activated model version %d for scope %s (%s)", version_id, scope, metrics)
    return version_id


def load_active(conn, scope: str) -> tuple[int, LogisticModel] | None:
    """Return (version_id, model) for the active champion of `scope`, or None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, artifact FROM model_versions WHERE scope = %s AND is_active",
            (scope,),
        )
        row = cur.fetchone()
    if not row:
        return None
    return row[0], LogisticModel.from_dict(row[1])


def active_metrics(conn, scope: str) -> dict | None:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT metrics FROM model_versions WHERE scope = %s AND is_active",
            (scope,),
        )
        row = cur.fetchone()
    return row[0] if row else None
