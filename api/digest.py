"""
Daily "who to call today" digest — the habit-formation trigger that lives
outside the app (UX audit §9): one short morning email per opted-in user
listing overdue tasks, quotes to chase, and the day's best uncalled leads.

Opt-in per user via users.preferences.daily_digest = true (Settings toggle,
PATCH /api/auth/preferences). Degrades gracefully: no-ops when email isn't
configured, and never sends an empty digest.

The compose step is pure (plain dicts in, subject/html out) so it can be
unit-tested without a DB — see tests/test_digest.py.
"""
import logging

from api.deps import dict_fetchall, dict_fetchone

log = logging.getLogger(__name__)

# How many top leads to name in the email body.
TOP_LEADS = 3


# ── Pure composition ──────────────────────────────────────────────────────────

def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"


def compose_digest(data: dict) -> tuple[str, str] | None:
    """Build (subject, html) from a digest data dict, or None when there is
    nothing actionable (we never send an empty digest).

    data keys: overdue_tasks, due_today, quotes_to_chase, stale_count,
    stale_value, top_leads (list of {label, grade, score}), app_url.
    """
    overdue = int(data.get("overdue_tasks") or 0)
    due_today = int(data.get("due_today") or 0)
    quotes = int(data.get("quotes_to_chase") or 0)
    stale = int(data.get("stale_count") or 0)
    stale_value = float(data.get("stale_value") or 0)
    top_leads = data.get("top_leads") or []

    if not (overdue or due_today or quotes or stale or top_leads):
        return None

    # Subject leads with the most actionable numbers, e.g.
    # "3 leads to call today, 1 quote to chase".
    bits = []
    if top_leads:
        bits.append(_plural(len(top_leads), "lead") + " to call today")
    if quotes:
        bits.append(_plural(quotes, "quote") + " to chase")
    if overdue:
        bits.append(_plural(overdue, "overdue task"))
    if not bits and (due_today or stale):
        bits.append("your pipeline needs a touch today")
    subject = "Axon: " + ", ".join(bits[:3])

    rows = []
    if top_leads:
        items = "".join(
            f"<li><b>{l.get('label') or '—'}</b>"
            + (f" — grade {l['grade']}" if l.get("grade") else "")
            + "</li>"
            for l in top_leads
        )
        rows.append(f"<p><b>Call these first:</b></p><ol>{items}</ol>")
    if quotes:
        rows.append(f"<p>{_plural(quotes, 'quote')} out with no answer — a nudge today keeps them warm.</p>")
    if overdue or due_today:
        parts = []
        if overdue:
            parts.append(_plural(overdue, "overdue task"))
        if due_today:
            parts.append(_plural(due_today, "task") + " due today")
        rows.append(f"<p>{' and '.join(parts)} on your list.</p>")
    if stale:
        money = f" (≈ ${stale_value:,.0f} in potential work)" if stale_value > 0 else ""
        rows.append(
            f"<p>{_plural(stale, 'lead')} haven't heard from you in two weeks{money}.</p>"
        )

    app_url = data.get("app_url") or ""
    cta = (
        f'<p><a href="{app_url}/home">Open Axon</a> to work the list.</p>'
        if app_url else ""
    )
    html = (
        "<div style=\"font-family:sans-serif;font-size:15px;line-height:1.5\">"
        "<p>Morning — here's today's list:</p>"
        + "".join(rows) + cta + "</div>"
    )
    return subject, html


# ── DB assembly ───────────────────────────────────────────────────────────────

def build_digest_data(conn, account_id: int) -> dict:
    """Gather one account's digest numbers. Every query is account-scoped."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT "
            "  COUNT(*) FILTER (WHERE due_date < CURRENT_DATE) AS overdue_tasks, "
            "  COUNT(*) FILTER (WHERE due_date = CURRENT_DATE) AS due_today "
            "FROM tasks WHERE account_id = %s AND is_complete = FALSE",
            (account_id,),
        )
        tasks = dict_fetchone(cur) or {}

        cur.execute(
            "SELECT "
            "  COUNT(*) FILTER (WHERE status = 'quote_sent') AS quotes_to_chase, "
            "  COUNT(*) FILTER (WHERE status = 'contacted' "
            "    AND stage_moved_at < NOW() - INTERVAL '14 days') AS stale_count, "
            "  COALESCE(SUM(estimated_job_value) FILTER (WHERE status = 'contacted' "
            "    AND stage_moved_at < NOW() - INTERVAL '14 days'), 0) AS stale_value "
            "FROM properties WHERE account_id = %s AND archived_at IS NULL",
            (account_id,),
        )
        pipe = dict_fetchone(cur) or {}

        cur.execute(
            "SELECT address, owner_name, contact_name, score_grade, lead_score "
            "FROM properties WHERE account_id = %s AND archived_at IS NULL "
            "AND status IN ('new', 'contacted') AND lead_score IS NOT NULL "
            "ORDER BY lead_score DESC LIMIT %s",
            (account_id, TOP_LEADS),
        )
        leads = dict_fetchall(cur)

    from config import APP_BASE_URL
    return {
        "overdue_tasks": tasks.get("overdue_tasks") or 0,
        "due_today": tasks.get("due_today") or 0,
        "quotes_to_chase": pipe.get("quotes_to_chase") or 0,
        "stale_count": pipe.get("stale_count") or 0,
        "stale_value": float(pipe.get("stale_value") or 0),
        "top_leads": [
            {
                "label": l.get("contact_name") or l.get("owner_name") or l.get("address") or "—",
                "grade": l.get("score_grade"),
                "score": l.get("lead_score"),
            }
            for l in leads
        ],
        "app_url": APP_BASE_URL,
    }


def send_daily_digests(conn) -> int:
    """Send the morning digest to every opted-in, active user. Returns the
    number of emails sent. Builds each account's data once."""
    from api.notifications import email_configured, send_email
    if not email_configured():
        return 0

    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, email, account_id FROM users "
            "WHERE is_active = TRUE AND email IS NOT NULL "
            "AND (preferences->>'daily_digest') IN ('true', 'email')",
        )
        users = dict_fetchall(cur)

    sent = 0
    cache: dict[int, tuple[str, str] | None] = {}
    for u in users:
        acct = u["account_id"]
        if acct not in cache:
            try:
                cache[acct] = compose_digest(build_digest_data(conn, acct))
            except Exception:
                log.exception("Digest build failed for account %s", acct)
                cache[acct] = None
        composed = cache[acct]
        if composed is None:
            continue
        subject, html = composed
        try:
            send_email(to_email=u["email"], subject=subject, html=html)
            sent += 1
        except Exception:
            log.exception("Digest send failed for user %s", u["id"])
    return sent
