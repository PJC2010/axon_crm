"""Invoice delivery via email (Resend) and SMS (Twilio).

Both senders fail soft per channel: if a provider isn't configured they raise a
clear error so the route can report which channel failed without aborting the
others. Messages are a plain invoice summary (no online pay link — Stripe
payments are deferred; see api/integrations/stripe/README.md).
"""
from config import (
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


def send_invoice_email(*, to_email: str, business_name: str, invoice_number: str,
                       amount_due: float, pdf_bytes: bytes | None = None) -> None:
    """Email the invoice. When ``pdf_bytes`` is supplied the rendered invoice PDF
    is attached so the customer gets a print-ready copy, not just a summary."""
    if not email_configured():
        raise RuntimeError("Email is not configured (RESEND_API_KEY / RESEND_FROM_EMAIL)")
    import resend
    resend.api_key = RESEND_API_KEY

    amount = f"${amount_due:,.2f}"
    attached_note = (
        '<p style="color:#888;font-size:13px">Your invoice is attached as a PDF.</p>'
        if pdf_bytes else ""
    )
    html = f"""
      <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
        <h2 style="margin:0 0 4px">Invoice {invoice_number}</h2>
        <p style="color:#555;margin:0 0 20px">from {business_name}</p>
        <p>You have a new invoice with a balance of <strong>{amount}</strong>.</p>
        {attached_note}
        <p style="color:#888;font-size:13px">Please reply to this email or contact
           {business_name} to arrange payment.</p>
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
                     amount_due: float, pdf_url: str | None = None) -> None:
    """Text the customer. A plain SMS can't hold a file, so when ``pdf_url`` is
    given the message links to the PDF and (where the carrier supports it) Twilio
    delivers it as an MMS attachment via ``media_url``."""
    if not sms_configured():
        raise RuntimeError("SMS is not configured (TWILIO_* env vars)")
    from twilio.rest import Client
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    if pdf_url:
        body = (
            f"{business_name}: Invoice {invoice_number} for ${amount_due:,.2f} is ready. "
            f"View your invoice: {pdf_url}"
        )
        client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=to_phone,
                                media_url=[pdf_url])
    else:
        body = (
            f"{business_name}: Invoice {invoice_number} for ${amount_due:,.2f} is ready. "
            f"Please contact us to arrange payment."
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

