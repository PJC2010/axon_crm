"""GET /api/leads returned QueryCanceled 500s (DB_STATEMENT_TIMEOUT_MS, 30s)
on 2026-08-29 whenever the request carried no zip filter: the default sort's
ORDER BY (lead_score DESC NULLS LAST) had no order-serving index — the only
score index, idx_props_acct_zip_score (0017), keys (account_id, zip,
lead_score), so without a zip equality the whole account gets gathered and
top-N sorted per request, twice counting the COUNT(*). Migration 0084 adds
(account_id, <sort col>) partial indexes for the two sorts the app hits on
every page load (score — also the fallback for unrecognized values — and
updated_at, which was missing from SORT_MAP entirely).

An ORDER BY / index mismatch never errors: the planner just quietly goes back
to sorting the account and the 500s return. So these tests pin the chain
byte-for-byte — SORT_MAP's expressions appear verbatim in 0084's DDL, and
_build_filters states the partial predicate the indexes require.
"""
from pathlib import Path

from api.routes.leads import SORT_MAP, _build_filters

MIGRATION = (Path(__file__).resolve().parents[1]
             / "db/migrations/0084_leads_list_sort_indexes.sql")


def _ddl() -> str:
    """The migration's statements, comment lines stripped, whitespace
    collapsed — so assertions match the DDL and never a header mention."""
    lines = [ln for ln in MIGRATION.read_text().splitlines()
             if not ln.lstrip().startswith("--")]
    return " ".join(" ".join(lines).split())


def test_default_sort_expression_is_index_served():
    assert f"ON properties (account_id, {SORT_MAP['score']})" in _ddl()


def test_updated_at_sort_exists_and_is_index_served():
    # The dashboard requests sort=updated_at on every load; before 0084 the
    # key was absent, silently falling back to the (then unindexed) score sort.
    assert f"ON properties (account_id, {SORT_MAP['updated_at']})" in _ddl()


def test_indexes_are_partial_on_the_filter_every_consumer_states():
    assert _ddl().count("WHERE archived_at IS NULL") == 2
    conditions, _ = _build_filters(1, prefix="p.")
    assert "p.archived_at IS NULL" in conditions   # the joined, aliased list
    conditions, _ = _build_filters(1)
    assert "archived_at IS NULL" in conditions     # the unaliased CSV export


def test_only_final_score_may_reference_join_aliases():
    # export.py runs SORT_MAP against an unjoined `FROM properties` query; an
    # aliased entry is a guaranteed SQL error there. final_score predates this
    # rule (and is already unusable on /api/export for that reason) — nothing
    # new may join it.
    aliased = {k for k, v in SORT_MAP.items() if "p." in v or "lgs." in v}
    assert aliased == {"final_score"}
