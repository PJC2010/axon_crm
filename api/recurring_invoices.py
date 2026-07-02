"""Recurring invoices (Phase 7 — recurring revenue).

A recurring invoice is a normal invoice with ``recurrence`` set; it's the first
occurrence. ``generate_due_invoices`` (run daily by the scheduler) clones every
active template whose ``recurrence_next`` has fallen due into a fresh,
independent invoice, then advances ``recurrence_next`` by the cadence until it
passes ``recurrence_end``. The date math is pure and unit-tested.
"""
import logging
from calendar import monthrange
from datetime import date

log = logging.getLogger(__name__)

# Cadence → months/days to advance. Weekly is the only day-based one.
RECURRENCES = ("weekly", "monthly", "quarterly", "annual")
_MONTHS = {"monthly": 1, "quarterly": 3, "annual": 12}


def add_months(d: date, months: int) -> date:
    """d + N calendar months, clamping the day to the target month's length
    (Jan 31 + 1 month → Feb 28/29)."""
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def advance(d: date, recurrence: str) -> date:
    """The next occurrence date after ``d`` for a cadence."""
    if recurrence == "weekly":
        return date.fromordinal(d.toordinal() + 7)
    if recurrence in _MONTHS:
        return add_months(d, _MONTHS[recurrence])
    raise ValueError(f"Unknown recurrence: {recurrence!r}")


def next_after(d: date, recurrence: str, *, today: date | None = None) -> date:
    """Advance ``d`` by the cadence until it's strictly in the future — so a
    template that missed several ticks resumes on a sensible upcoming date
    rather than firing a backlog all at once."""
    today = today or date.today()
    nxt = advance(d, recurrence)
    # Cap the catch-up so a very stale template can't loop forever.
    for _ in range(600):
        if nxt > today:
            break
        nxt = advance(nxt, recurrence)
    return nxt


def series_ended(next_date: date, recurrence_end: date | None) -> bool:
    """True when the next occurrence would fall past the series end date."""
    return recurrence_end is not None and next_date > recurrence_end


def generate_due_invoices(conn, *, today: date | None = None) -> dict:
    """Clone every active recurring invoice that's due into a fresh invoice and
    advance its schedule. Caller-agnostic (used by the scheduler). Returns a
    summary. Each template is handled in its own transaction slice so one bad
    row doesn't block the rest."""
    today = today or date.today()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id, account_id FROM invoices "
            "WHERE recurrence IS NOT NULL AND recurrence_next IS NOT NULL "
            "AND recurrence_next <= %s",
            (today,),
        )
        due = cur.fetchall()

    summary = {"generated": 0, "templates": len(due), "failures": 0}
    for template_id, account_id in due:
        try:
            created = _generate_one(conn, template_id, account_id, today)
            conn.commit()
            summary["generated"] += created
        except Exception:
            conn.rollback()
            summary["failures"] += 1
            log.exception("Recurring invoice generation failed for template %d", template_id)
    return summary


def _generate_one(conn, template_id: int, account_id: int, today: date) -> int:
    """Clone one due template forward and advance its recurrence_next. Returns
    the number of invoices generated (0 or 1)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT property_id, client_name, client_phone, client_email, client_address, "
            "tax_rate, subtotal, tax_amount, total, issue_date, due_date, notes, created_by, "
            "recurrence, recurrence_next, recurrence_end "
            "FROM invoices WHERE id = %s AND account_id = %s",
            (template_id, account_id),
        )
        t = cur.fetchone()
        if not t:
            return 0
        (property_id, client_name, client_phone, client_email, client_address,
         tax_rate, subtotal, tax_amount, total, issue_date, due_date, notes, created_by,
         recurrence, recurrence_next, recurrence_end) = t

        # Preserve the template's issue→due gap on each clone.
        due_gap = (due_date - issue_date).days if due_date and issue_date else None
        clone_issue = recurrence_next
        clone_due = date.fromordinal(clone_issue.toordinal() + due_gap) if due_gap is not None else None

        cur.execute(
            "INSERT INTO invoices (property_id, client_name, client_phone, client_email, client_address, "
            "status, tax_rate, subtotal, tax_amount, total, issue_date, due_date, notes, created_by, "
            "account_id, recurring_source_id) "
            "VALUES (%s,%s,%s,%s,%s,'sent',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (property_id, client_name, client_phone, client_email, client_address,
             tax_rate, subtotal, tax_amount, total, clone_issue, clone_due, notes, created_by,
             account_id, template_id),
        )
        clone_id = cur.fetchone()[0]

        # Copy the line items.
        cur.execute(
            "INSERT INTO invoice_line_items (invoice_id, description, quantity, unit_price, sort_order) "
            "SELECT %s, description, quantity, unit_price, sort_order "
            "FROM invoice_line_items WHERE invoice_id = %s",
            (clone_id, template_id),
        )

        # Advance the schedule; deactivate the series once it passes its end.
        nxt = next_after(recurrence_next, recurrence, today=today)
        if series_ended(nxt, recurrence_end):
            cur.execute("UPDATE invoices SET recurrence_next = NULL, recurrence = NULL WHERE id = %s",
                        (template_id,))
        else:
            cur.execute("UPDATE invoices SET recurrence_next = %s WHERE id = %s", (nxt, template_id))

    return 1
