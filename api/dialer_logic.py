"""Pure power-dialer logic: queue eligibility SQL fragments, the disposition
vocabulary and its mappings, and the browser-client identity encoding.

Dependency-free on purpose (no DB, no config, no twilio import) so it can be
unit-tested directly — same split as api/call_logic.py and api/sms_logic.py.
The routes in api/routes/dialer.py and the outbound webhooks in
api/routes/twilio_voice.py are thin wrappers over this.
"""
import re

# The rep's verdict after a call. Mirrors the CHECK on calls.disposition
# (migration 0069) — keep the two lists in sync.
DISPOSITIONS = ("no_answer", "voicemail", "interested", "not_interested",
                "callback", "wrong_number", "do_not_call")

# Dispositions that mean a human was reached — these emit 'contacted' to the
# scoring feedback loop; everything else is a mere 'contact_attempted'.
CONNECT_DISPOSITIONS = ("interested", "not_interested", "callback")

# Queue defaults: the "still worth cold-calling" stages. Overridable per
# request within the properties.status vocabulary (migration 0003).
QUEUE_DEFAULT_STATUSES = ("new", "contacted")
QUEUE_ALLOWED_STATUSES = ("new", "contacted", "qualified", "quote_sent",
                          "won", "lost", "not_interested")

GRADES = ("A", "B", "C", "D")

# ── Browser-client identity ───────────────────────────────────────────────────
#
# The Voice access token's identity is what the outbound TwiML webhook gets as
# From ("client:axon-<account>-<user>"). It is parsed for account/user context
# but the users table stays authoritative — the webhook re-verifies both ids.

_IDENTITY_RE = re.compile(r"^axon-(\d+)-(\d+)$")


def build_identity(account_id: int, user_id: int) -> str:
    return f"axon-{int(account_id)}-{int(user_id)}"


def parse_client_identity(raw: str | None) -> tuple[int, int] | None:
    """(account_id, user_id) from a Voice-SDK From value, or None.

    Accepts the bare identity or Twilio's "client:" prefixed form. Anything
    malformed — wrong shape, non-numeric, empty — is None, which the webhook
    treats as a business-level reject (2xx TwiML, no side effects).
    """
    s = (raw or "").strip()
    if s.startswith("client:"):
        s = s[len("client:"):]
    m = _IDENTITY_RE.match(s)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


# ── Queue eligibility ─────────────────────────────────────────────────────────

def build_queue_filters(account_id: int, *, grade: str | None = None,
                        statuses: tuple[str, ...] | list[str] | None = None,
                        cooldown_hours: int = 4) -> tuple[list[str], list]:
    """(conditions, params) for the dialer queue, positional-%s style like
    api/routes/leads.py::_build_filters. Callable = in this account, not
    archived, not do-not-call, in a workable status, holding a dialable phone,
    not litigator-flagged, and not already dialed inside the cooldown window.

    Raises ValueError on a status outside the vocabulary or an unknown grade —
    the route turns that into a 400.
    """
    statuses = tuple(statuses) if statuses else QUEUE_DEFAULT_STATUSES
    bad = [s for s in statuses if s not in QUEUE_ALLOWED_STATUSES]
    if bad:
        raise ValueError(f"Unknown status filter: {', '.join(bad)}")
    if grade is not None and grade not in GRADES:
        raise ValueError(f"Unknown grade filter: {grade}")

    conditions = [
        "p.account_id = %s",
        "p.archived_at IS NULL",
        "p.do_not_call = FALSE",
        "p.status = ANY(%s)",
        # Dialable = at least a full 10-digit US number somewhere in the raw
        # text (contact_phone is free-form; E.164 happens at dial time).
        "LENGTH(regexp_replace(COALESCE(p.contact_phone, ''), '[^0-9]', '', 'g')) >= 10",
        # Known TCPA litigators are never queued even before anyone flags DNC.
        "COALESCE(LOWER(p.enrichment_flags #>> '{phone_append_meta,litigator}'), '')"
        " NOT IN ('true', 't', '1', 'yes', 'y')",
    ]
    params: list = [account_id, list(statuses)]

    if grade is not None:
        conditions.append("p.score_grade = %s")
        params.append(grade)
    if cooldown_hours > 0:
        conditions.append(
            "NOT EXISTS (SELECT 1 FROM calls c2 WHERE c2.property_id = p.id"
            " AND c2.direction = 'outbound'"
            " AND c2.started_at > NOW() - make_interval(hours => %s))"
        )
        params.append(int(cooldown_hours))
    return conditions, params


# ── Disposition mappings ──────────────────────────────────────────────────────

# Mechanical outcome for a manually-logged (tel:) call, where no Twilio verdict
# exists. Browser calls keep the outcome the status callback wrote.
_MANUAL_OUTCOMES = {
    "no_answer": "no_answer",
    "voicemail": "no_answer",
}

# Timeline vocabulary — matches/extends the ActivityPanel OUTCOME_OPTIONS
# strings so dialer rows read like hand-logged ones.
_HISTORY_OUTCOMES = {
    "no_answer":      "No answer",
    "voicemail":      "Left message",
    "interested":     "Interested",
    "not_interested": "Not interested",
    "callback":       "Callback scheduled",
    "wrong_number":   "Wrong number",
    "do_not_call":    "Do not call",
}

# Statuses a disposition never overrides — the lead's fate is already decided.
_TERMINAL_STATUSES = ("won", "converted", "lost", "not_interested")


def is_valid_disposition(d: str | None) -> bool:
    return d in DISPOSITIONS


def outcome_for_disposition(d: str) -> str:
    return _MANUAL_OUTCOMES.get(d, "answered")


def history_outcome_for(d: str) -> str:
    return _HISTORY_OUTCOMES[d]


def status_change_for(d: str, current_status: str | None) -> str | None:
    """The lead-status move a disposition implies, or None to leave it alone.

    Conservative on purpose: a call outcome only ever advances 'new' to
    'contacted' or closes to 'not_interested' — it never demotes a lead a
    human already moved further down the pipeline.
    """
    current = current_status or "new"
    if d == "not_interested":
        return None if current in _TERMINAL_STATUSES else "not_interested"
    if d in ("interested", "callback") and current == "new":
        return "contacted"
    return None


def event_for(d: str) -> str:
    """lead_events event_type for the scoring feedback loop."""
    return "contacted" if d in CONNECT_DISPOSITIONS else "contact_attempted"


def manual_call_sid(hex32: str) -> str:
    """A synthetic calls.call_sid for a manually-logged (tel:) call — keeps the
    NOT NULL UNIQUE column honest without colliding with Twilio's CA… space.
    The route passes uuid4().hex so this module stays import-free."""
    return f"manual-{hex32}"


def callback_task_title(lead_label: str) -> str:
    return f"Callback requested — {lead_label}"
