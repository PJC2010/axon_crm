# Twilio setup (SMS + call tracking)

Axon uses Twilio in two structurally different ways. They share one set of credentials but
are configured in completely different places, and confusing them is the usual reason
"SMS doesn't work" or "the tracking number rings nowhere."

| | **Global platform number** | **Per-account tracking numbers** |
|---|---|---|
| How many | One, for the whole deployment | One per account |
| Env var | `TWILIO_FROM_NUMBER` | none — stored in `tracking_numbers` |
| Who configures the webhooks | **You, by hand, in the Twilio console** | **The app**, at purchase time |
| Powers | All outbound SMS/MMS + inbound replies | Inbound call tracking + its SMS twin |
| Module | `core` (always on) | `calls` (gated) |

---

## 1. Credentials

Three env vars, all from the Twilio console (Account → API keys & tokens):

```bash
TWILIO_ACCOUNT_SID=AC...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM_NUMBER=+18325550100    # E.164
```

Plus one that isn't a credential but breaks call tracking if it's wrong:

```bash
PUBLIC_API_BASE_URL=https://axon-crm-api.onrender.com
```

This is **the API's own origin**, not the frontend's (`APP_BASE_URL`). It's what the app
stamps onto every tracking number it buys as the `voice_url` / `sms_url`. Empty means
"derive from the incoming request," which works but leaves you at the mercy of proxy
headers — set it explicitly in production. It's already in `render.yaml`.

On Render, `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER` are **not** in
the blueprint — enter them in the dashboard.

**Everything degrades gracefully.** `notifications.sms_configured()` requires all three
vars; when any is empty the SMS channel is skipped rather than raising, invoice/quote sends
report a per-channel failure, and `/api/calls/*` returns 503. Missing keys never break a
deploy.

### What the credentials unlock

`api/notifications.py` is the only outbound sender. Callers:

| What | Where |
|---|---|
| Invoice delivery (MMS — attaches the PDF via `media_url`) | `api/routes/invoices.py` |
| Quote delivery | `api/routes/quotes.py` |
| Manual "text this lead" | `api/routes/messaging.py` |
| Workflow-rule template sends (policy renewals, delayed missed-call SMS) | `api/workflow_engine.py` |
| Speed-to-lead auto-reply on website intake | `api/routes/public_intake.py` |

Note the `calls` module needs only SID + token — `voice_configured()` deliberately does
*not* require `TWILIO_FROM_NUMBER`, because calls arrive on per-account tracking numbers.
You can run call tracking without a global SMS number, and vice versa.

---

## 2. Buy the global number and point its messaging webhook at us

Buy a **local US number with SMS + MMS + Voice** capability. MMS is not optional: invoice
sends attach the PDF via `media_url`, and a non-MMS number will fail those.

Then, on that number's **Messaging configuration** page:

| Field | Value |
|---|---|
| Select a method | `Webhook, TwiML Bin, Function, Studio Flow, Proxy Service` |
| Primary method | `Use Webhooks` |
| **Webhook URL** | `https://<your-api-host>/api/public/twilio/sms` |
| Method to handle responses | `HTTP POST` |
| Backup method | Leave blank, or the same URL |

Three ways to silently break signature validation:

- **Use `https://`.** `_signature_valid` force-upgrades the scheme before verifying
  (Render terminates TLS at its proxy, so uvicorn only ever sees plain http), but that
  only helps if you configured https in the first place.
- **No trailing slash.** Twilio signs the URL string exactly as configured; `/sms/` will
  not validate against the `/sms` route.
- **No query params.** Anything appended becomes part of the signed string.

A mismatch returns 403 with `Inbound SMS rejected: invalid Twilio signature` in the logs —
that's the string to grep for when testing.

**Leave the Voice configuration on this number alone.** Inbound calls to it would resolve
no `tracking_numbers` row and just get the "unconfigured" TwiML.

### What inbound SMS to this number does

`POST /api/public/twilio/sms` (`api/routes/twilio_inbound.py`) matches the sender
**cross-account** by last-10 digits, tie-broken by whichever record was texted most
recently — that's who the customer is replying to. The message threads into
`contact_history` next to the outbound sends.

An unknown sender on the global number is logged and dropped, **no lead created**. That's
deliberate: the number is shared across tenants, so there's no account to attribute a new
lead to. Only tracking numbers auto-create leads from unknown senders.

Either way the route answers 200 + empty TwiML. A non-2xx makes Twilio retry forever, so
every business-level miss still returns success.

---

## 3. A2P 10DLC registration

**Required** for US application-to-person SMS from a 10-digit long code. Without it
carriers filter or outright block your messages, and you get no error back — sends look
fine in the Twilio logs and never arrive.

1. Register a **Brand** (legal entity, EIN, business details).
2. Register a **Campaign** describing the use case.
3. Create a **Messaging Service** and attach it to the campaign.
4. **Add your number to that Messaging Service.**

Step 4 is the one people miss. The code sends with a bare `from_=<number>`, not a
`messaging_service_sid` — that's fine and needs no change, because a number inherits its
campaign through service membership. But a number sitting outside the service gets
filtered even though registration reads "approved."

Using a **toll-free** number instead? You need Toll-Free Verification, not 10DLC.

Campaign registration asks how you record consent. Migration `0064_sms_consent.sql` exists
for exactly this: `users.sms_consent` is the switch, `sms_consent_at` +
`sms_consent_source` (`'signup'` checkbox or `'settings'` toggle) the provenance, and
`sms_opted_out_at` preserves *when* consent was withdrawn rather than deleting the row — so
consent can be demonstrated during a carrier audit.

---

## 4. Call tracking (the `calls` module)

**Do not buy or configure these numbers by hand.** The app does it, and hand-bought numbers
won't have a `tracking_numbers` row for the webhook to resolve.

From the app (Settings → Calls, owner role required):

- `GET /api/calls/numbers/available?area_code=832` searches Twilio's inventory.
- `POST /api/calls/numbers` purchases one and sets `voice_url` →
  `/api/public/twilio/voice` and `sms_url` → `/api/public/twilio/sms`, both built from
  `PUBLIC_API_BASE_URL`. If the DB insert then fails, the number is released back to
  Twilio — real money was spent, so it doesn't strand.
- `PATCH /api/calls/settings` sets `forward_to`, the business's real phone.
- `DELETE /api/calls/numbers/{id}` releases it.

One active number per account (`idx_tracking_numbers_digits_active` enforces that an active
number maps to exactly one tenant).

The call flow, `api/routes/twilio_voice.py`:

1. Twilio POSTs `/api/public/twilio/voice`. The tenant is resolved from the **To** number.
2. The caller is matched to a lead **scoped to that account**; an unknown caller becomes a
   new lead.
3. A `calls` row is inserted — `call_sid` is UNIQUE, which is the idempotency anchor, so a
   Twilio retry skips every side effect and re-returns the same TwiML.
4. `<Dial>` TwiML forwards the caller to `forward_to`, with an action callback.
5. Post-commit and best-effort: if `PHONE_APPEND_PROVIDER` is set, the caller's number is
   reverse-appended (address / name / email) onto the lead. One paid lookup per caller
   ever, flagged in `enrichment_flags.phone_append`. A provider outage never stops the
   call connecting.
6. `/api/public/twilio/voice/dial-status` records answered / missed / busy + duration. On a
   miss it drops an **urgent same-day call-back task** on the owner and fires `call_event`
   workflow rules — those send from the **tracking number**, via the `sms_from` override,
   not the global number.

Callers the webhook couldn't append inside Twilio's 15s window are backfilled nightly by
`api/call_append_sweep.py`. It's **off by default** (`PHONE_APPEND_SWEEP_MAX=0`) — raise it
deliberately, every lookup is billed.

### Optional: Caller Name (CNAM) lookup

The voice webhook reads Twilio's `CallerName` field and stores it on the lead, but Twilio
only populates it if caller-name lookup is enabled on the number (US only, per-lookup fee).
Without it, a lead created from a call arrives with just a phone number.

---

## What you do *not* need

- **Twilio SendGrid** — email goes through Resend (`RESEND_API_KEY` / `RESEND_FROM_EMAIL`).
- **Twilio Verify, Studio, Flex, Conversations, Lookup** — not referenced anywhere.
- **Voice recording / transcription** — not implemented. The `voice_settings` JSONB column
  on `tracking_numbers` is a placeholder for it.
- **A trial account will not work.** Trials can only reach *verified* numbers, which defeats
  the entire unknown-caller-becomes-a-lead premise. Upgrade before testing.

---

## Verifying

- `GET /api/calls/settings` → `{"configured": true, "number": {...}}`. `configured: false`
  means `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` aren't set.
- Text the global number from a phone that matches a lead's `contact_phone`; the message
  should appear on that lead's timeline within a second.
- Watch the logs for `invalid Twilio signature` (URL mismatch) or `matched no record`
  (working, but the sender isn't on any lead).
- Call a tracking number and confirm it forwards, then check `GET /api/calls` for the row
  and the lead timeline for the "Inbound call" line.

## Known gaps

- **No outbound delivery status callback.** Sends are fire-and-forget; a carrier-blocked
  message still logs as sent. If A2P filtering starts eating messages there is no in-app
  signal — check the Twilio console.
- **No STOP/opt-out handling in the inbound route.** Twilio auto-handles STOP/HELP at its
  own layer, so you stay compliant, but the app never learns a contact opted out and will
  keep queuing sends to them.
- **The `calls` module uses the master account SID + auth token** to purchase and release
  numbers. A scoped API Key/Secret would be tighter, but the code path is written for
  SID + token.
