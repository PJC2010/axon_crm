"""Outbound email (Resend) and SMS (Twilio): invoice/quote delivery, signup
welcome email, and internal admin alerts (new signups, landing-page prospects).

Both senders fail soft per channel: if a provider isn't configured they raise a
clear error so the route can report which channel failed without aborting the
others. Messages are a plain invoice summary (no online pay link — Stripe
payments are deferred; see api/integrations/stripe/README.md).
"""
import html as _html

from config import (
    ADMIN_NOTIFICATION_EMAIL, APP_BASE_URL,
    RESEND_API_KEY, RESEND_FROM_EMAIL,
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER,
)


def email_configured() -> bool:
    return bool(RESEND_API_KEY and RESEND_FROM_EMAIL)


def sms_configured() -> bool:
    return bool(TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN and TWILIO_FROM_NUMBER)


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


def send_sms(*, to_phone: str, body: str) -> None:
    """Generic SMS primitive."""
    if not sms_configured():
        raise RuntimeError("SMS is not configured (TWILIO_* env vars)")
    from twilio.rest import Client
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=to_phone)


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
                     pay_url: str | None = None) -> None:
    """Text the customer. A plain SMS can't hold a file, so when ``pdf_url`` is
    given the message links to the PDF and (where the carrier supports it) Twilio
    delivers it as an MMS attachment via ``media_url``. ``pay_url`` (when the
    account has Stripe payments enabled) appends the online-payment link."""
    if not sms_configured():
        raise RuntimeError("SMS is not configured (TWILIO_* env vars)")
    from twilio.rest import Client
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    pay_note = f" Pay online: {pay_url}" if pay_url else ""
    if pdf_url:
        body = (
            f"{business_name}: Invoice {invoice_number} for ${amount_due:,.2f} is ready. "
            f"View your invoice: {pdf_url}{pay_note}"
        )
        client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=to_phone,
                                media_url=[pdf_url])
    else:
        contact_note = "" if pay_url else " Please contact us to arrange payment."
        body = (
            f"{business_name}: Invoice {invoice_number} for ${amount_due:,.2f} is ready."
            f"{pay_note}{contact_note}"
        )
        client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=to_phone)


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
                   total: float, quote_url: str | None = None) -> None:
    if not sms_configured():
        raise RuntimeError("SMS is not configured (TWILIO_* env vars)")
    from twilio.rest import Client
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    link = f" View and accept: {quote_url}" if quote_url else " Contact us with questions or to accept."
    body = f"{business_name}: Your quote {quote_number} for ${total:,.2f} is ready.{link}"
    client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=to_phone)

