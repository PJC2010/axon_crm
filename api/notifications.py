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


def send_invoice_email(*, to_email: str, business_name: str, invoice_number: str,
                       amount_due: float) -> None:
    if not email_configured():
        raise RuntimeError("Email is not configured (RESEND_API_KEY / RESEND_FROM_EMAIL)")
    import resend
    resend.api_key = RESEND_API_KEY

    amount = f"${amount_due:,.2f}"
    html = f"""
      <div style="font-family:system-ui,sans-serif;max-width:520px;margin:0 auto;color:#1a1a1a">
        <h2 style="margin:0 0 4px">Invoice {invoice_number}</h2>
        <p style="color:#555;margin:0 0 20px">from {business_name}</p>
        <p>You have a new invoice with a balance of <strong>{amount}</strong>.</p>
        <p style="color:#888;font-size:13px">Please reply to this email or contact
           {business_name} to arrange payment.</p>
      </div>
    """
    resend.Emails.send({
        "from": RESEND_FROM_EMAIL,
        "to": [to_email],
        "subject": f"Invoice {invoice_number} from {business_name} — {amount} due",
        "html": html,
    })


def send_invoice_sms(*, to_phone: str, business_name: str, invoice_number: str,
                     amount_due: float) -> None:
    if not sms_configured():
        raise RuntimeError("SMS is not configured (TWILIO_* env vars)")
    from twilio.rest import Client
    client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
    body = (
        f"{business_name}: Invoice {invoice_number} for ${amount_due:,.2f} is ready. "
        f"Please contact us to arrange payment."
    )
    client.messages.create(body=body, from_=TWILIO_FROM_NUMBER, to=to_phone)
