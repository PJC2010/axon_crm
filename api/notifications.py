"""Outbound email (Resend) and SMS (Twilio): invoice/quote delivery, signup
welcome email, and internal admin alerts (new signups, landing-page prospects).

Both senders fail soft per channel: if a provider isn't configured they raise a
clear error so the route can report which channel failed without aborting the
others. Messages are a plain invoice summary (no online pay link — Stripe
payments are deferred; see api/integrations/stripe/README.md).

Every SMS goes out through ``_send_sms``, which resolves the sender in one
place: an explicit ``from_number`` (the account's own tracking number) wins
over the global ``TWILIO_FROM_NUMBER``, the value is normalized to E.164 (see
api/sms_logic.py), a Messaging Service SID is routed to ``messaging_service_sid``
rather than ``from_``, and a Twilio rejection is re-raised as ``SmsSendError``
carrying what the error code actually means for this deployment's config.
"""
import html as _html
import logging

from config import (
    ADMIN_NOTIFICATION_EMAIL, APP_BASE_URL,
    RESEND_API_KEY, RESEND_FROM_EMAIL,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER,
)
from api import sms_logic

log = logging.getLogger(__name__)


class SmsSendError(RuntimeError):
    """A Twilio send that failed, with the cause spelled out.

    Subclasses RuntimeError so the existing ``except Exception`` handlers in the
    invoice/quote/messaging routes keep working unchanged.
    """

    def __init__(self, message: str, *, code: int | None = None, sender: str = ""):
        super().__init__(message)
        self.code = code
        self.sender = sender


def email_configured() -> bool:
    return bool(RESEND_API_KEY and RESEND_FROM_EMAIL)


def resolve_sms_sender(from_number: str | None = None) -> str:
    """The normalized sender an SMS will actually go out from.

    ``from_number`` is the account's own tracking number when it has one; the
    global TWILIO_FROM_NUMBER is the fallback for accounts that don't.
    """
    return (sms_logic.normalize_sender(from_number)
            or sms_logic.normalize_sender(TWILIO_FROM_NUMBER))


def sms_configured(from_number: str | None = None) -> bool:
    """Whether an SMS can be sent — credentials plus a usable sender.

    Passing an account's own tracking number stands in for a blank global
    TWILIO_FROM_NUMBER, so an account with its own number isn't held back by
    the platform-wide default being unset.
    """
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and resolve_sms_sender(from_number))


def account_sms_from(db, account_id: int) -> str | None:
    """The account's own active tracking number, or None if it has none.

    Texting a lead from the number already on their caller ID keeps the thread
    in one place — and it means a stale platform-wide TWILIO_FROM_NUMBER can't
    break sends for an account that owns a working number of its own. Inbound
    replies to it already resolve back to this tenant
    (api/routes/twilio_inbound.py).
    """
    with db.cursor() as cur:
        cur.execute(
            "SELECT phone_number FROM tracking_numbers "
            "WHERE account_id = %s AND status = 'active' ORDER BY id LIMIT 1",
            (account_id,),
        )
        row = cur.fetchone()
    return row[0] if row else None


def _twilio_client():
    from twilio.rest import Client
    return Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


def _send_sms(*, to_phone: str, body: str, from_number: str | None = None,
              media_url: list[str] | None = None) -> None:
    """The single outbound-SMS chokepoint. All senders below route through it."""
    if not sms_configured(from_number):
        raise SmsSendError("SMS is not configured (TWILIO_* env vars)")
    sender = resolve_sms_sender(from_number)
    kwargs: dict = {"body": body, "to": sms_logic.normalize_recipient(to_phone)}
    if sms_logic.is_messaging_service(sender):
        kwargs["messaging_service_sid"] = sender
    else:
        kwargs["from_"] = sender
    if media_url:
        kwargs["media_url"] = media_url
    try:
        _twilio_client().messages.create(**kwargs)
    except Exception as exc:
        log.warning("Twilio send from %s failed: %s", sender, exc)
        raise SmsSendError(sms_logic.describe_send_failure(exc, sender=sender),
                           code=sms_logic.twilio_error_code(exc), sender=sender) from exc


def _sms_capable(number) -> bool:
    """Whether a Twilio IncomingPhoneNumber can send SMS. ``capabilities`` comes
    back as a plain dict from the REST client, but tolerate an object too."""
    caps = getattr(number, "capabilities", None) or {}
    if isinstance(caps, dict):
        return bool(caps.get("sms") or caps.get("SMS"))
    return bool(getattr(caps, "sms", False))


def verify_sms_sender(from_number: str | None = None) -> dict:
    """Ask Twilio whether the configured sender is usable, without sending.

    Answers the question the 21659 error leaves open — *is this number on this
    project at all?* — and lists the senders that are, so the fix is a copy-paste
    rather than a hunt through the console. Never raises: every failure mode is
    reported in the returned dict.
    """
    sender = resolve_sms_sender(from_number)
    result: dict = {
        "sender": sender,
        "source": "account_tracking_number" if sms_logic.normalize_sender(from_number) else "TWILIO_FROM_NUMBER",
        "credentials_configured": bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN),
        "account_sid": f"{TWILIO_ACCOUNT_SID[:6]}…{TWILIO_ACCOUNT_SID[-4:]}" if TWILIO_ACCOUNT_SID else "",
        "checked": False,
        "owned": None,
        "sms_capable": None,
        "available_senders": [],
        "error": None,
    }
    if not result["credentials_configured"]:
        result["error"] = "TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN are not set"
        return result
    if not sender:
        result["error"] = "No sender configured — set TWILIO_FROM_NUMBER or buy a tracking number"
        return result

    try:
        client = _twilio_client()
        if sms_logic.is_messaging_service(sender):
            service = client.messaging.v1.services(sender).fetch()
            result.update(checked=True, owned=True, sms_capable=True,
                          friendly_name=service.friendly_name)
            return result
        result["available_senders"] = [
            {"phone_number": n.phone_number, "sms_capable": _sms_capable(n)}
            for n in client.incoming_phone_numbers.list(limit=100)
        ]
        match = next((n for n in result["available_senders"] if n["phone_number"] == sender), None)
        result.update(checked=True, owned=match is not None,
                      sms_capable=match["sms_capable"] if match else None)
        if match is None:
            result["error"] = (
                f"{sender} is not on this Twilio project — it is not in the "
                f"{len(result['available_senders'])} active number(s) this Account SID owns."
            )
        elif not match["sms_capable"]:
            result["error"] = f"{sender} is on this project but has no SMS capability."
    except Exception as exc:
        result["error"] = sms_logic.describe_send_failure(exc, sender=sender)
    return result


def send_email(*, to_email: str, subject: str, html: str) -> None:
    """Generic transactional email — the primitive workflow notifications use.
    The invoice/quote senders below keep their bespoke templates."""
    if not email_configured():
        raise RuntimeError("Email is not configured (RESEND_API_KEY / RESEND_FROM_EMAIL)")
    import resend
    resend.api_key = RESEND_API_KEY
    resend.Emails.send({
        "from": RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": subject,
        "html": html,
    })


def send_sms(*, to_phone: str, body: str, from_number: str | None = None) -> None:
    """Generic SMS primitive. from_number overrides TWILIO_FROM_NUMBER when set."""
    _send_sms(to_phone=to_phone, body=body, from_number=from_number)


def admin_alerts_configured() -> bool:
    return bool(ADMIN_NOTIFICATION_EMAIL) and email_configured()


def send_admin_signup_alert(*, company_name: str, email: str, business_type: str,
                            username: str) -> None:
    """Internal alert to the platform owner when a self-serve signup lands."""
    if not admin_alerts_configured():
        raise RuntimeError("Admin alerts are not configured (ADMIN_NOTIFICATION_EMAIL + RESEND_*)")
    company = _html.escape(company_name)
    send_email(
        to_email=ADMIN_NOTIFICATION_EMAIL,
        subject=f"New Axon signup: {company_name}",
        html=f"""
        <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
          <h2 style="margin:0 0 12px">New self-serve signup</h2>
          <table style="border-collapse:collapse;font-size:14px">
            <tr><td style="padding:4px 12px 4px 0;color:#888">Company</td><td>{company}</td></tr>
            <tr><td style="padding:4px 12px 4px 0;color:#888">Email</td><td>{_html.escape(email)}</td></tr>
            <tr><td style="padding:4px 12px 4px 0;color:#888">Username</td><td>{_html.escape(username)}</td></tr>
            <tr><td style="padding:4px 12px 4px 0;color:#888">Business type</td><td>{_html.escape(business_type)}</td></tr>
          </table>
          <p style="color:#888;font-size:13px;margin-top:20px">They start on a pro trial —
          worth a personal welcome within the first day.</p>
        </div>
        """,
    )


def send_admin_prospect_alert(*, email: str, name: str | None, source: str | None) -> None:
    """Internal alert when a visitor leaves their email on the landing/preview pages."""
    if not admin_alerts_configured():
        raise RuntimeError("Admin alerts are not configured (ADMIN_NOTIFICATION_EMAIL + RESEND_*)")
    send_email(
        to_email=ADMIN_NOTIFICATION_EMAIL,
        subject=f"New Axon prospect: {email}",
        html=f"""
        <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
          <h2 style="margin:0 0 12px">Someone left their email</h2>
          <table style="border-collapse:collapse;font-size:14px">
            <tr><td style="padding:4px 12px 4px 0;color:#888">Email</td><td>{_html.escape(email)}</td></tr>
            <tr><td style="padding:4px 12px 4px 0;color:#888">Name</td><td>{_html.escape(name or "—")}</td></tr>
            <tr><td style="padding:4px 12px 4px 0;color:#888">Source</td><td>{_html.escape(source or "landing")}</td></tr>
          </table>
          <p style="color:#888;font-size:13px;margin-top:20px">They asked for a walkthrough —
          reply while the interest is warm.</p>
        </div>
        """,
    )


def send_welcome_email(*, to_email: str, company_name: str, trial_days: int) -> None:
    """Onboarding welcome sent alongside the verification email at signup."""
    if not email_configured():
        raise RuntimeError("Email is not configured (RESEND_API_KEY / RESEND_FROM_EMAIL)")
    company = _html.escape(company_name)
    send_email(
        to_email=to_email,
        subject=f"Welcome to Axon — your {trial_days}-day Pro trial is live",
        html=f"""
        <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
          <h2 style="margin:0 0 12px">Welcome aboard, {company}</h2>
          <p>Your workspace is ready and every Pro feature is unlocked for the next
          <strong>{trial_days} days</strong> — no card required.</p>
          <p style="margin:16px 0 8px"><strong>Three things worth doing first:</strong></p>
          <ol style="margin:0 0 16px;padding-left:20px;line-height:1.7">
            <li><strong>Import your leads</strong> — drop in a CSV and they land on your board.</li>
            <li><strong>Set up your pipeline</strong> — rename stages to match how you actually sell.</li>
            <li><strong>Send your first invoice or quote</strong> — email or text, straight from a lead.</li>
          </ol>
          <p style="margin:24px 0"><a href="{APP_BASE_URL}/dashboard"
             style="background:#1a5a75;color:#fff;text-decoration:none;padding:12px 24px;
                    border-radius:8px;font-weight:600">Open your dashboard</a></p>
          <p style="color:#888;font-size:13px">Questions? Just reply to this email —
          a real person reads these.</p>
        </div>
        """,
    )


def send_invoice_email(*, to_email: str, business_name: str, invoice_number: str,
                       amount_due: float, pdf_bytes: bytes | None = None,
                       pay_url: str | None = None) -> None:
    """Email the invoice. When ``pdf_bytes`` is supplied the rendered invoice PDF
    is attached so the customer gets a print-ready copy, not just a summary.
    When ``pay_url`` is given (the account has Stripe payments enabled) the
    email carries a "Pay online" button instead of the arrange-payment note."""
    if not email_configured():
        raise RuntimeError("Email is not configured (RESEND_API_KEY / RESEND_FROM_EMAIL)")
    import resend
    resend.api_key = RESEND_API_KEY

    amount = f"${amount_due:,.2f}"
    attached_note = (
        '<p style="color:#888;font-size:13px">Your invoice is attached as a PDF.</p>'
        if pdf_bytes else ""
    )
    cta = (
        f'<p style="margin:24px 0"><a href="{pay_url}" '
        f'style="background:#1a5a75;color:#fff;text-decoration:none;'
        f'padding:12px 24px;border-radius:8px;font-weight:600">Pay online</a></p>'
        if pay_url else
        f'<p style="color:#888;font-size:13px">Please reply to this email or contact '
        f'{business_name} to arrange payment.</p>'
    )
    html = f"""
      <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
        <h2 style="margin:0 0 4px">Invoice {invoice_number}</h2>
        <p style="color:#555;margin:0 0 20px">from {business_name}</p>
        <p>You have a new invoice with a balance of <strong>{amount}</strong>.</p>
        {attached_note}
        {cta}
      </div>
    """
    payload = {
        "from": RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": f"Invoice {invoice_number} from {business_name} — {amount} due",
        "html": html,
    }
    if pdf_bytes:
        import base64
        payload["attachments"] = [{
            "filename": f"{invoice_number}.pdf",
            "content": base64.b64encode(pdf_bytes).decode("ascii"),
            "content_type": "application/pdf",
        }]
    resend.Emails.send(payload)


def send_invoice_sms(*, to_phone: str, business_name: str, invoice_number: str,
                     amount_due: float, pdf_url: str | None = None,
                     pay_url: str | None = None, from_number: str | None = None) -> None:
    """Text the customer. A plain SMS can't hold a file, so when ``pdf_url`` is
    given the message links to the PDF and (where the carrier supports it) Twilio
    delivers it as an MMS attachment via ``media_url``. ``pay_url`` (when the
    account has Stripe payments enabled) appends the online-payment link."""
    pay_note = f" Pay online: {pay_url}" if pay_url else ""
    if pdf_url:
        body = (
            f"{business_name}: Invoice {invoice_number} for ${amount_due:,.2f} is ready. "
            f"View your invoice: {pdf_url}{pay_note}"
        )
        _send_sms(to_phone=to_phone, body=body, from_number=from_number, media_url=[pdf_url])
    else:
        contact_note = "" if pay_url else " Please contact us to arrange payment."
        body = (
            f"{business_name}: Invoice {invoice_number} for ${amount_due:,.2f} is ready."
            f"{pay_note}{contact_note}"
        )
        _send_sms(to_phone=to_phone, body=body, from_number=from_number)


def send_quote_email(*, to_email: str, business_name: str, quote_number: str,
                     total: float, valid_until=None, quote_url: str | None = None) -> None:
    if not email_configured():
        raise RuntimeError("Email is not configured (RESEND_API_KEY / RESEND_FROM_EMAIL)")
    import resend
    resend.api_key = RESEND_API_KEY

    amount = f"${total:,.2f}"
    validity = (
        f'<p style="color:#888;font-size:13px">This quote is valid until {valid_until:%B %d, %Y}.</p>'
        if valid_until else ""
    )
    cta = (
        f'<p style="margin:24px 0"><a href="{quote_url}" '
        f'style="background:#1a5a75;color:#fff;text-decoration:none;'
        f'padding:12px 24px;border-radius:8px;font-weight:600">View &amp; accept quote</a></p>'
        if quote_url else
        f'<p style="color:#888;font-size:13px">Reply to this email or contact '
        f'{business_name} with any questions or to accept this quote.</p>'
    )
    html = f"""
      <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
        <h2 style="margin:0 0 4px">Quote {quote_number}</h2>
        <p style="color:#555;margin:0 0 20px">from {business_name}</p>
        <p>Your quote is ready, totaling <strong>{amount}</strong>.</p>
        {validity}
        {cta}
      </div>
    """
    resend.Emails.send({
        "from": RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": f"Quote {quote_number} from {business_name} — {amount}",
        "html": html,
    })


def send_quote_sms(*, to_phone: str, business_name: str, quote_number: str,
                   total: float, quote_url: str | None = None,
                   from_number: str | None = None) -> None:
    link = f" View and accept: {quote_url}" if quote_url else " Contact us with questions or to accept."
    body = f"{business_name}: Your quote {quote_number} for ${total:,.2f} is ready.{link}"
    _send_sms(to_phone=to_phone, body=body, from_number=from_number)

