# WhatsApp Cloud API

Meta's official Business API — the third way a WhatsApp message reaches this
app, and the one meant for production.

| Path | Owns the connection | Identified by | Notes |
|---|---|---|---|
| `whatsapp_web.py` | the Baileys bridge (Node sidecar) | a linked handset | Personal account. Against Meta's terms; the number can be banned. |
| `whatsapp.py` | Twilio | the number itself | Official, but a reseller sits in the middle. |
| **`whatsapp_cloud.py`** | Meta | `phone_number_id` | Official, direct, no sidecar. |

One `whatsapp_channels` table serves the two business paths, discriminated by
`provider` (migration 0029). Everything downstream — conversations, the inbox,
campaigns, which assistant answers — keys off the channel id and never asks
which vendor is behind it. Only the send path branches.

## Setting one up

**Deployment (once, in `.env`)**

| Variable | Where it comes from | What happens without it |
|---|---|---|
| `WHATSAPP_CLOUD_APP_SECRET` | App Dashboard → Settings → Basic | Every inbound delivery is refused, deliberately |
| `WHATSAPP_CLOUD_VERIFY_TOKEN` | You choose it | Meta cannot verify the callback URL |
| `WHATSAPP_CLOUD_API_VERSION` | Pinned, default `v21.0` | — |

**Per number (in the app, Channels → WhatsApp Cloud Business)**

Phone number ID, WABA ID and a permanent access token, all from App Dashboard →
WhatsApp → API Setup. Stored on the channel row, so two tenants can bring two
different numbers into one deployment. The token is never returned by the API
once saved — it can be replaced, not read.

**In Meta**

Callback URL `<APP_BASE_URL>/api/v1/whatsapp/cloud/webhook`, the verify token
from `.env`, and then **subscribe the WABA to the `messages` field**. Without
that subscription the URL verifies, the number looks connected, and nothing is
ever delivered.

## The three things this endpoint gets right on purpose

**It verifies the signature over the raw body.** The URL is public and
unauthenticated — Meta is the caller — so `X-Hub-Signature-256` is the only
thing between an attacker and words appearing in a customer's thread. Verified
against `await request.body()`, not the re-serialised JSON: re-serialising
changes whitespace and key order, and the digest with it, which is how this
check gets written so it can never pass and is then "fixed" by deleting it.

A missing app secret refuses everything rather than skipping the check. An
endpoint that accepts unsigned posts because it was misconfigured fails
silently, and the damage is real messages to real people.

**It answers Meta immediately.** A reply is a full RAG or agent run — seconds to
tens of seconds. Meta expects a 200 within seconds, retries what it does not
get, and throttles a subscription that keeps failing. The message is stored, the
webhook returns, and the reply is generated in a background task behind the same
per-process bulkhead the personal-account path uses.

**It never fails loudly.** A 500 is a retry, and a retry is a duplicate message
to a real person. An unfamiliar payload is logged and answered 200 — Meta ships
new event types without notice, and there is nothing it can usefully do by
sending them again.

## What arrives, and what is read

`parse_webhook` flattens `entry[].changes[].value.{messages,statuses}`. One POST
can carry several numbers, each with several messages; treating a delivery as
"the message" is how messages get dropped exactly when traffic is highest.

Text comes from `text.body`, but also from `button.text` and
`interactive.{button_reply,list_reply}.title` — a tapped reply is a real answer,
and the booking assistant's numbered options are exactly what produce them.
A photo or location arrives with no text: it is still stored (the inbox should
show that something came in) and answered with a short "I can only read text".

## Booking assistants work here

An assistant with `appointments_enabled` is routed to `AskFrontOffice`, so it
can check real availability and book. This is not optional politeness: a model
given no tools does not say "I can't book" — it says "you're booked".
`tests/test_booking_agent_routing.py` guards every answering surface for exactly
this, this module included.

## The 24-hour window

Outside 24 hours from a customer's last message, Meta only accepts **approved
template messages** — free-form text is rejected with code 131047, surfaced as
"Outside the 24-hour customer service window". This affects campaigns:
broadcasts send free-form text today, so a Cloud campaign to a cold contact
fails per recipient with that message on the row. Templates are not implemented
yet; that is the next piece of work for this channel.

## Delivery receipts

Twilio posts them to a dedicated status-callback URL. Meta puts them on the same
webhook as inbound messages. Both funnel through
`broadcasts.advance_delivery_status`, so campaign counts are computed one way
rather than twice — the second copy being the one that forgets to recompute.

## Operating notes

- **A development number only messages test recipients.** Until the number is
  live, Meta delivers only from the numbers added under API Setup. A silent
  webhook is usually this, not a bug.
- **Temporary tokens expire in 24 hours.** The token on the API Setup page is a
  development one. Use a permanent System User token, or the number stops
  replying a day later with Meta code 190 in the logs.
- **`phone_number_id`, not the phone number, resolves the tenant.** It is
  uniquely indexed where non-empty; the display number in a payload is cosmetic
  and inconsistently formatted.
- **Local testing needs a tunnel.** Meta will not call `localhost` — ngrok or
  cloudflared, with `APP_BASE_URL` set to the public URL.
