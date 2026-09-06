"""Tests for api/routes/admin_data.py — the Data tab's endpoints. Fake-conn style."""
import os
from datetime import datetime, timedelta, timezone

import psycopg2.errors
import pytest
from fastapi import HTTPException

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-not-used-for-signing")

from api import data_health  # noqa: E402
from api.routes import admin_data  # noqa: E402
from api.routes.admin_data import admin_data_health, admin_data_health_refresh  # noqa: E402
from tests.fakeconn import Conn, first_index, sql_matching  # noqa: E402

ADMIN = {"id": 7, "username": "pete", "account_id": 1}
NOW = datetime.now(timezone.utc)
SNAP_COLS = ["id", "started_at", "finished_at", "status", "triggered_by", "host", "report"]
LATEST_COLS = ["id", "started_at", "finished_at", "status", "triggered_by", "error"]

REPORT = {
    "parcels": {"total": 800, "with_coords": 580, "with_apn": 700, "unclassified": 0,
                "non_residential": 20},
    "apn_match": {"with_apn": 700, "matched": 690},
    "zips": [{"zip": "77001", "parcels": 500, "with_coords": 480, "unclassified": 0,
              "non_residential": 20, "hcad_rows": 520}],
    "accounts": [
        {"account_id": 1, "properties": 900, "with_coords": 890, "unclassified": 0, "excludable": 12},
        {"account_id": 99, "properties": 5, "with_coords": 5, "unclassified": 0, "excludable": 0},
    ],
    "hcad": {"properties": 610, "site_city_filled": 600, "centroids": 1500000,
             "centroids_loaded_at": "2026-08-20T00:00:00+00:00", "permits": 12345},
    "geocode_sources": [{"source": "hcad_centroid", "count": 580}],
    "discrepancies": {"total_open": 35, "by_field": [], "by_account": []},
    "city_sanity": {"parcels_mail_city_leak": 0, "properties_mail_city_leak": 0,
                    "parcels_null_city": 0, "properties_null_city": 0},
    "blocks_failed": [], "duration_seconds": 4.2,
}


def _script(snapshot_rows=None, latest_rows=None, geocode=None):
    started = NOW - timedelta(hours=3)
    snap = ([(5, started, started, "ok", "schedule", "web-1", REPORT)]
            if snapshot_rows is None else snapshot_rows)
    latest = ([(5, started, started, "ok", "schedule", None)]
              if latest_rows is None else latest_rows)
    return [
        ("FROM data_health_snapshots WHERE status IN", (SNAP_COLS, snap)),
        ("FROM data_health_snapshots ORDER BY", (LATEST_COLS, latest)),
        ("SELECT id, name FROM accounts", (["id", "name"], [(1, "Acme Roofing"), (2, "New Org")])),
        ("FROM geocode_queue GROUP BY status",
         geocode or (["status", "n", "oldest"], [("queued", 12, NOW), ("failed", 2, NOW)])),
        ("GROUP BY last_error", (["last_error", "n"], [("no match", 2)])),
        ("WHERE non_residential_reasons IS NULL GROUP BY account_id",
         (["account_id", "n"], [(2, 5)])),
        ("FROM property_rule_stamps",
         (["account_id", "rule_hash", "classified_at"], [(1, "hp", NOW)])),
        ("FROM parcel_rule_stamps",
         (["zip", "rule_hash", "classified_at"], [("77001", "old", NOW)])),
    ]


@pytest.fixture(autouse=True)
def _pin_rule(monkeypatch):
    monkeypatch.setattr(admin_data, "_current_hashes", lambda: ("hp", "pc"))
    monkeypatch.setattr(admin_data, "_hcad_source", lambda report: "postgres")


class TestDataHealthRead:
    def test_overlays_names_stamps_and_live_counts(self):
        out = admin_data_health(db=Conn(_script()))
        assert out["degraded"] == []
        assert out["snapshot"]["id"] == 5
        assert out["snapshot"]["report"]["parcels"]["total"] == 800
        assert out["summary"] == {"coords_pct": 72.5, "apn_pct": 87.5, "match_rate_pct": 98.6,
                                  "unclassified_pct": 0.0, "non_residential_pct": 2.5}
        accounts = {a["account_id"]: a for a in out["accounts"]}
        assert set(accounts) == {1, 2}                      # 99 was deleted since the snapshot
        assert accounts[1]["name"] == "Acme Roofing"
        assert accounts[1]["rule_state"] == "current" and accounts[1]["unclassified_live"] == 0
        assert accounts[2]["properties"] is None             # created since the snapshot
        assert accounts[2]["rule_state"] == "unstamped" and accounts[2]["unclassified_live"] == 5
        assert out["zips"][0]["rule_state"] == "stale"
        assert out["rule"] == {"property_rule_hash": "hp", "parcel_rule_hash": "pc",
                               "accounts_stale": 0, "accounts_unstamped": 1,
                               "zips_stale": 1, "zips_unstamped": 0}
        assert out["live"]["geocode_queue"]["failed"] == 2
        assert out["live"]["hcad_source"] == "postgres"
        keys = {a["key"] for a in out["alerts"]}
        assert {"accounts_unstamped", "zips_stale", "geocode_failed"} <= keys
        assert "no_snapshot" not in keys and "snapshot_stale" not in keys
        assert out["refresh"]["running"] is False and out["job_id"] == data_health.JOB_ID

    def test_no_snapshot_yet(self):
        out = admin_data_health(db=Conn(_script(snapshot_rows=[], latest_rows=[])))
        assert out["snapshot"] is None and out["summary"] is None and out["refresh"] is None
        assert out["live"]["hcad_source"] == "unknown"
        assert [a["key"] for a in out["alerts"]][0] == "no_snapshot"
        assert out["zips"] == []
        # Orgs still list from the live tables, with unknown counts.
        assert {a["account_id"] for a in out["accounts"]} == {1, 2}
        assert all(a["properties"] is None for a in out["accounts"])

    def test_a_cut_off_live_block_degrades_only_itself(self):
        conn = Conn(_script(geocode=psycopg2.errors.QueryCanceled()))
        out = admin_data_health(db=conn)
        assert out["degraded"] == ["geocode_queue"] and out["live"]["geocode_queue"] is None
        assert conn.rollbacks == 1
        assert out["accounts"]                               # the rest still answered

    def test_stale_and_running_states(self):
        old = NOW - timedelta(days=3)
        script = _script(
            snapshot_rows=[(4, old, old, "partial", "schedule", "web-1",
                            {**REPORT, "blocks_failed": ["hcad"]})],
            latest_rows=[(6, NOW - timedelta(minutes=2), None, "running", "admin", None)],
        )
        out = admin_data_health(db=Conn(script))
        keys = {a["key"] for a in out["alerts"]}
        assert {"snapshot_stale", "blocks_failed"} <= keys
        assert out["refresh"]["running"] is True and out["refresh"]["stalled"] is False


class TestRefresh:
    LATEST_COLS = ["id", "started_at", "status"]

    def test_refused_while_a_fresh_run_is_in_flight(self, monkeypatch):
        monkeypatch.setattr(data_health, "enqueue_snapshot",
                            lambda: pytest.fail("enqueued anyway"))
        conn = Conn([("FROM data_health_snapshots ORDER BY",
                      (self.LATEST_COLS, [(6, NOW - timedelta(minutes=1), "running")]))])
        with pytest.raises(HTTPException) as exc:
            admin_data_health_refresh(admin=ADMIN, db=conn)
        assert exc.value.status_code == 409

    def test_a_stalled_run_does_not_block_a_refresh(self, monkeypatch):
        calls = []
        monkeypatch.setattr(data_health, "enqueue_snapshot", lambda: calls.append(1))
        conn = Conn([("FROM data_health_snapshots ORDER BY",
                      (self.LATEST_COLS, [(6, NOW - timedelta(hours=2), "running")]))])
        assert admin_data_health_refresh(admin=ADMIN, db=conn)["queued"] is True
        assert calls == [1]

    def test_enqueues_and_audits_before_commit(self, monkeypatch):
        calls = []
        monkeypatch.setattr(data_health, "enqueue_snapshot", lambda: calls.append(1))
        conn = Conn([("FROM data_health_snapshots ORDER BY",
                      (self.LATEST_COLS, [(5, NOW - timedelta(hours=3), "ok")]))])
        out = admin_data_health_refresh(admin=ADMIN, db=conn)
        assert out == {"queued": True, "job_id": data_health.MANUAL_JOB_ID}
        assert calls == [1]
        (_, params), = sql_matching(conn, "INSERT INTO admin_audit_log")
        assert params[2] == "data_health.refresh"
        assert params[5].adapted == {"previous_snapshot_id": 5}
        assert first_index(conn, "INSERT INTO admin_audit_log") < first_index(conn, "COMMIT")
