# RAG Platform

Multi-tenant Retrieval-Augmented Generation platform. A company registers,
uploads documents, and immediately gets a working AI chatbot grounded in those
documents — exposed over a clean HTTP API with streaming answers and citations.

Designed to **deploy on free tiers** (Neon Postgres + Cloudflare R2 + Gemini/Groq
free LLM APIs + a free web host) while keeping a production-grade internal
architecture so it can grow into paid infrastructure without a rewrite.

## Why this stack

| Concern | Choice | Reason |
|---|---|---|
| API | FastAPI (async) | Streaming (SSE), Pydantic validation, OpenAPI for free |
| DB + vectors | Postgres + **pgvector** (Neon) | One free datastore for both relational data and embeddings |
| Files | Cloudflare R2 (S3 API) | Free object storage; host disk is ephemeral |
| Embeddings | **Gemini** `text-embedding-004` | Free → ingestion costs nothing |
| Generation | **Groq** primary, **Gemini** fallback | Two free pools + automatic failover on rate limits |
| Background work | FastAPI BackgroundTasks | No always-on worker = no cost; ingestion is resumable |
| Auth | JWT + per-tenant API keys | Stateless, horizontally scalable |

There is **no Redis, Celery, or Qdrant** — at this scale pgvector + in-process
tasks + a Postgres usage table cover those roles for free. The ports/adapters
design means each can be swapped back in later by adding an adapter.

## Architecture (Clean Architecture + DDD)

```
src/
  domain/          Pure business core (entities, value objects, events). No frameworks.
  application/     Use cases + ports (Protocols for repos & services).
  infrastructure/  Adapters: SQLAlchemy+pgvector, Gemini/Groq, R2, JWT, LangGraph.
  interfaces/api/  FastAPI routers, auth, SSE streaming, health/metrics.
  config/          Pydantic settings + DI composition root (container.py).
migrations/        Alembic (initial schema + pgvector + RLS).
deploy/            Render & Fly free-tier configs.
```

Dependencies point **inward only**: the domain knows nothing about FastAPI,
SQLAlchemy, or any provider SDK.

### Multi-tenancy
Every tenant-scoped query is filtered by `tenant_id` (primary guard). Postgres
**Row-Level Security** policies provide defense-in-depth — see *RLS* below.

### Resumable ingestion
`upload → parse → chunk → embed → ready` is a state machine persisted per
document. If a free host sleeps mid-job, the startup *resume sweep* (and a
`/retry` endpoint) continue from the last completed step instead of restarting.

## Local development

```powershell
# 1. Configure
copy .env.example .env       # then fill GEMINI_API_KEY and GROQ_API_KEY

# 2. Start Postgres (pgvector) + the API
docker compose up --build

# API: http://localhost:8000   Docs: http://localhost:8000/docs
```

Without Docker:

```powershell
python -m venv .venv; .\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
# point DATABASE_URL at a local/Neon Postgres, then:
alembic upgrade head
uvicorn src.interfaces.api.app:app --reload
```

## API quickstart

```
POST /api/v1/auth/register     { tenant_name, email, password }  -> JWT
POST /api/v1/documents         { filename, content_type, size_bytes } -> presigned upload URL
PUT  <upload_url>              (raw bytes)
POST /api/v1/documents/{id}/complete   -> schedules ingestion
GET  /api/v1/documents/{id}    -> status: pending|...|ready|failed
POST /api/v1/chatbots          { name } -> chatbot
POST /api/v1/chatbots/{id}/sessions     -> session_id
POST /api/v1/sessions/{id}/messages     { message } -> answer + citations (JSON)
POST /api/v1/sessions/{id}/stream       { message } -> SSE token stream
```

Ops: `GET /healthz` (liveness), `GET /readyz` (DB check), `GET /metrics` (Prometheus).

## Building an assistant

You describe the assistant in prose and the platform writes its configuration:

```
POST /api/v1/chatbots/generate   { description, use_case?, channel? }  -> a saved assistant
```

An LLM turns the description into a name, a welcome message, and a
**Conversational Flow** specific to that job — a collections assistant gets a
payment-arrangement flow, a recruiting one gets a candidate-qualification flow.
Nothing is templated, and everything is editable afterwards.

Two invariants survive whatever the model returns
(`src/application/use_cases/generate_assistant.py`):

* **Structure** — sections are sorted back onto a known spine (Identity &
  Purpose → Facts → Actions & Limits → Flow: … → Scope & Redirects →
  Guardrails), so the editor always renders something recognisable.
* **Safety** — a Guardrails section is appended if the model omits one. An
  assistant with no injection resistance is a liability, and the model is the
  least reliable place to enforce that.

If generation fails — no API key, rate limit, malformed JSON — the endpoint
returns a usable draft with `ai_generated: false` rather than an error. The
owner is mid-create; a dead end is worse than a rough draft.

`POST /api/v1/chatbots/{id}/flow/generate` ("Ask AI") rebuilds an existing
assistant's flow from a new description, keeping its name, voice, model,
knowledge base, and publish state.

### Assistant settings

Call direction, languages, TTS voice, LLM, transcription backend, and the
welcome message live in one `assistant` object, saved as a unit:

```
GET   /api/v1/chatbots/options            -> the values the UI may offer
PATCH /api/v1/chatbots/{id}   { assistant: { direction, languages, tts_voice, ... } }
```

The welcome message supports `[user_name]`-style placeholders filled from call
data at dial time. With **Dynamic** on, the message is a brief the model
rephrases per call; with it off the text is spoken verbatim and the generation
call is skipped entirely — routing a request through a model to reproduce a
fixed string costs latency and is the one thing models are least reliable at.

### Per-assistant knowledge base

```
GET /api/v1/chatbots/{id}/knowledge                        -> every doc, flagged attached
PUT /api/v1/chatbots/{id}/knowledge   { document_ids: [] }  -> replace the selection
```

An empty selection means "search every ready document in the workspace", which
is what an assistant starts on. An assistant with **no** knowledge base still
works — it answers from its Conversational Flow alone — so the UI nudges toward
uploading one rather than blocking. Submitted ids are intersected with the
tenant's own documents before saving, so a foreign or deleted id can't sit in
the allowlist quietly narrowing retrieval.

## Conversational Flow

An assistant's system prompt is authored as an **ordered list of named,
individually toggleable sections** rather than one opaque blob — reorder them,
switch one off to A/B a behaviour, or add a role-specific branch without a
deploy.

```
PATCH /api/v1/chatbots/{id}   { flow_sections: [{ title, body, enabled }, ...] }
POST  /api/v1/chatbots/{id}/flow/reset   -> restore the stock section set
```

The enabled sections are composed into `system_prompt` on write, so every
generation path (chat, stream, widget, WhatsApp, interviews) reads one string
and needs no knowledge of sections. `system_prompt` and `flow_sections` are two
views of the same thing: sending both to `PATCH` is rejected, and writing
`system_prompt` directly clears the sections (the raw-prompt escape hatch).
A flow whose enabled sections are all empty falls back to the stock prompt —
a blank system prompt would silently leave the assistant unguarded.

## Post-call delivery

When a conversation ends, matching configurations push it to a webhook or an
inbox. Each block is optional and each of summary / sentiment / extraction costs
one LLM call, so unchecked boxes are a real cost lever.

```
POST /api/v1/chatbots/{id}/post-call   { delivery_method, webhook_url|email_to,
                                         trigger_statuses: ["completed", ...],
                                         include_summary, include_transcript,
                                         include_sentiment, include_extracted }
POST /api/v1/chatbots/{id}/sessions/{sid}/end   { call_status } -> fires matches
GET  /api/v1/chatbots/{id}/post-call-deliveries -> audit trail
```

Webhooks are signed like Stripe's: verify `X-Signature` as
`HMAC-SHA256(jwt_secret, "{X-Signature-Timestamp}.{raw_body}")`. Dispatch runs
as a background task and is idempotent — a `(config, session)` unique constraint
means a repeated "end session" call can't double-post into a customer's ATS.

## WhatsApp broadcast campaigns

Outbound sends to a contact list, where every reply is then handled by the
assistant's normal auto-reply pipeline (the campaign owns *delivery*; the
conversation belongs to the existing WhatsApp session machinery).

```
POST /api/v1/broadcasts                     { chatbot_id, name, message_template,
                                              recipients_text }
POST /api/v1/broadcasts/{id}/start          -> background send sweep
POST /api/v1/broadcasts/{id}/pause | /complete | /retry-failed
GET  /api/v1/broadcasts/{id}/recipients?status=&search=&page=
GET|POST /api/v1/broadcasts/{id}/recipients/{rid}/messages  -> chat log / takeover
POST /api/v1/broadcasts/status-callback     (Twilio, signature-verified)
```

The sweep claims recipients with `FOR UPDATE SKIP LOCKED`, so it is safe to run
on more than one process and resumes after a free host sleeps mid-campaign
without re-messaging anyone. Delivery status (`sent → delivered → read →
replied`) is rank-ordered, so out-of-order Twilio callbacks can't move a contact
backwards. Requires the assistant to be connected to a WhatsApp number first
(see *Channels*); message templates support `{{name}}`, `{{first_name}}`,
and `{{phone}}`.

## Integrations

A catalogue of 14 connectable services, filtered by category (Calendar & CRM,
Messaging, Data & Sheets, Custom & Tools) with per-tenant credentials.

```
GET    /api/v1/integrations-catalogue                  -> cards + connection state
POST   /api/v1/integrations-catalogue/{id}/connect     { config: {...} }
POST   /api/v1/integrations-catalogue/{id}/test        -> sends a real message
DELETE /api/v1/integrations-catalogue/{id}
```

The catalogue is a code-level registry (`src/domain/integration/catalogue.py`),
so adding an integration is a deploy rather than a migration; only the
*connections* are tenant data. Each spec declares its own credential fields, and
`connect` persists **only** the keys the spec names — an arbitrary JSON blob
can't be stored under an integration. Secret fields are write-only: responses go
through `redact()`, so a stored credential never travels back to the browser.

### One-click connect (OAuth)

Consent-based integrations are connected in a popup — the user approves in
their own account and never handles a token:

```
GET    /api/v1/integrations/oauth/{provider}/start      -> the vendor consent URL
GET    /api/v1/integrations/oauth/{provider}/callback   -> stores tokens, closes the popup
GET    /api/v1/integrations/oauth/{provider}/status
DELETE /api/v1/integrations/oauth/{provider}
```

`start` returns the URL as JSON rather than redirecting, because a plain
browser navigation wouldn't carry the bearer token (the JWT lives in
localStorage, not a cookie). The callback replies with a page that
`postMessage`s the result to the app's own origin and closes itself, so the
page behind the popup never navigates.

**`state` is a signed JWT** carrying the tenant id, the provider, a
short expiry, and an `oauth-state` audience. That is what lets the callback
attribute a consent without a session, rejects a replayed or forged value, and
stops a consent obtained for one provider being redeemed as another (whose
scopes may be wider).

Providers live in `src/infrastructure/oauth/providers.py` — one client
parameterised by a spec, since every vendor runs the identical three steps and
differs only in two URLs, a scope string, and where the account label lives.
Both Google integrations share one OAuth app; they differ only in scopes.
Google Sheets asks for `drive.file`, not `drive`, so it can only touch files it
creates or the user explicitly opens with it.

**What transacts today**, per each spec's `wired` flag:

| Integration | Connect | What it does |
|---|---|---|
| **Google Calendar** | 1-click OAuth | Check availability and create events. |
| **Google Sheets** | 1-click OAuth | Append finished conversations as rows. |
| **Slack** | Webhook URL | Adds `slack` as a Post-Call delivery method. |
| **Custom API** | Endpoint URL | HMAC-signed POST to any HTTPS endpoint you control. |
| **Cal.com** | 1-click OAuth* | *Needs a Cal.com Platform OAuth client — see `.env.example`. |

An OAuth card is only `wired` when the server actually has an app registered for
that vendor; otherwise it renders with Connect **disabled** and says what is
missing. The remaining cards do the same (they need a vendor OAuth app plus an
adapter). That is deliberate: a card that appears to connect and then silently
does nothing is worse than one that says it isn't ready.

## Personal WhatsApp linking ("Phone WhatsApp")

Scan a QR from **WhatsApp → Settings → Linked Devices** and your personal
number becomes an inbound channel: whoever messages it gets answered by the
assistant you attach.

> **Read this before enabling it.** This uses WhatsApp's *unofficial*
> multi-device protocol via [Baileys](https://github.com/WhiskeySockets/Baileys).
> It violates Meta's terms of service and the linked number **can be banned**.
> Use a number you can afford to lose. Official Business numbers go through the
> Twilio path instead, which is supported and unaffected.

```
GET    /api/v1/whatsapp-web/options                     -> is the bridge configured/healthy
POST   /api/v1/whatsapp-web/sessions                    -> create + begin pairing
GET    /api/v1/whatsapp-web/sessions/{id}               -> QR + countdown + status (polled)
POST   /api/v1/whatsapp-web/sessions/{id}/refresh       -> new QR after the window lapsed
PATCH  /api/v1/whatsapp-web/sessions/{id}/assistant     { chatbot_id }  (null = receive only)
DELETE /api/v1/whatsapp-web/sessions/{id}               -> unlink at WhatsApp, wipe keys
```

### Architecture

WhatsApp sockets live in a **Node sidecar** (`whatsapp-bridge/`), not in the
Python process. Baileys is the mature implementation of this protocol and it is
Node-only; running it out-of-process also means a WhatsApp reconnect storm can't
take down the API. The two talk over localhost HTTP with a shared secret
(`BRIDGE_TOKEN`), and the bridge binds to `127.0.0.1` — it has no per-tenant
authorization of its own, so nothing outside the container should reach it.

Three decisions worth knowing about:

- **Auth state lives in Postgres**, not on disk. Baileys ships an on-disk store,
  but the container filesystem is ephemeral on free hosts — keys there would be
  wiped by every sleep or redeploy and force a re-scan. Persisting them means a
  link survives a restart, and the bridge re-attaches linked sessions on boot.
- **Inbound only.** Bulk outbound from a linked personal account is what
  actually triggers bans, so Broadcast stays on the Twilio path where recipients
  opted in.
- **Groups, status broadcasts, own echoes, and captionless media are dropped**
  before they reach the API. Auto-replying into a group chat gets a number
  reported fast.

Enable it by setting `BRIDGE_TOKEN`; `scripts/start.sh` launches the sidecar
alongside the API when it's present. Leave it blank and the feature reports
itself unconfigured and everything else runs unchanged.

## Report Issue

An in-app bug report / feature request form, reachable from the sidebar by any
signed-in user.

```
GET  /api/v1/issues/options   -> report types, priorities, whether email is configured
POST /api/v1/issues           { name, email, phone, report_type, priority, subject, description }
GET  /api/v1/issues           -> this tenant's reports (admin)
```

The report is **persisted first and emailed second**. Email is the part that can
fail (no `SUPPORT_EMAIL`, no `RESEND_API_KEY`, provider outage), and losing what
a frustrated user just typed because of that would be the worst outcome — a
report whose email didn't send still appears in the list with `email_sent=false`,
and the UI says so. User input is HTML-escaped before it reaches the email body.

## Clone Voice

Build a custom AI voice from a microphone recording or an uploaded file, then
assign it to a voice-channel assistant.

```
GET    /api/v1/voices/options        -> languages, genders, limits, cloning_enabled
POST   /api/v1/voices                (multipart: sample + name/gender/language/duration)
POST   /api/v1/voices/{id}/retry     -> re-send the stored sample to the provider
POST   /api/v1/voices/{id}/speak     { text } -> audio/mpeg
GET    /api/v1/voices/{id}/sample    -> the original recording
DELETE /api/v1/voices/{id}
```

Recording uses `MediaRecorder` with a wall-clock timer rather than the Blob's
duration header — a fresh webm/opus blob reports `Infinity` until fully decoded,
so the timer is what the 20-second gate and the server both rely on. Duration is
treated as untrusted: the server range-checks it *and* cross-checks it against
the actual byte count, so a client claiming 30 seconds while sending 2KB is
rejected.

Cloning uses **ElevenLabs**, opt-in via `ELEVENLABS_API_KEY` in the same shape as
Google Calendar and Resend. Without a key the page still records, validates,
stores, lists, and plays back samples — profiles simply land as `failed` with a
Retry button that works the moment a key is set. The source sample is kept in
object storage precisely so that retry never asks the user to record again.

Assigning a voice sets `chatbots.voice_profile_id`; the FK is `ON DELETE SET
NULL`, so deleting a voice degrades that assistant to the browser's default
voice rather than deleting the assistant.

## Embed & integrate (the public widget)

A chatbot can be **published** and dropped into any website — no account needed
by the end visitor. Toggle a bot public in the builder (**Embed & Share**), then:

**1. Embed script** — paste before `</body>` on any page:

```html
<script src="https://YOUR-APP/widget.js" data-chatbot-key="pk_xxx" async></script>
```

It renders a floating, themeable chat bubble inside a Shadow DOM (zero CSS
clashes) and streams answers over SSE.

**2. Share a link** — every public bot also has a full-page chat at
`https://YOUR-APP/c/pk_xxx` to share directly.

Public API (no auth — identified only by the publishable `pk_` key):

```
GET  /api/v1/public/chatbots/{key}/config                       -> theme + name
POST /api/v1/public/chatbots/{key}/sessions                     -> session_id
POST /api/v1/public/chatbots/{key}/sessions/{id}/messages       -> answer (JSON)
POST /api/v1/public/chatbots/{key}/sessions/{id}/stream         -> SSE token stream
```

Owner controls (admin API, JWT):
```
PATCH /api/v1/chatbots/{id}            { is_public, allowed_origins, widget{...} }
POST  /api/v1/chatbots/{id}/rotate-key -> new pk_ key (old snippet stops working)
```

**Anonymous-traffic guards**, in order: publishable key resolves to a *public*
bot → request `Origin` is on the bot's allowlist (empty = any) → per-IP+bot
sliding-window rate limit (`PUBLIC_ANON_*`) → the owning tenant's daily token
quota. The publishable key is non-secret; the layered guards (not the key) are
what contain abuse. CORS for these routes reflects the caller's origin without
credentials — the allowlist is the authorization layer.

## Deployment (free)

The Docker image is a **single deployable unit**: it builds the SPA (`vite build`)
and FastAPI serves it alongside the API and `/widget.js`. So one deploy yields
**one public origin** that hosts the admin app, the share page (`/c/<key>`), the
embed script, and the API — which is exactly what lets a generated link/snippet
work on any visitor's machine. Locally, `frontend/dist` is absent and Vite serves
the SPA instead (see *Local development*).

1. **Database** — create a free Neon project, enable the `vector` extension, copy
   the connection string into `DATABASE_URL`.
2. **Files** — create a Cloudflare R2 bucket + API token; set `R2_*`.
   (Omit to use local disk in dev.)
3. **Keys** — get free `GEMINI_API_KEY` (Google AI Studio) and `GROQ_API_KEY`.
4. **Public URL** — set `APP_BASE_URL` to your deployed HTTPS domain
   (e.g. `https://rag-platform.fly.dev`). This is what the share link and embed
   snippet are built from; `WIDGET_BASE_URL`/`FRONTEND_BASE_URL` fall back to it,
   so on a single-origin deploy you only set `APP_BASE_URL`.
5. **Host** — deploy with `deploy/fly.toml` (`fly launch`) or `deploy/render.yaml`.
   Migrations run automatically on container start (`scripts/start.sh`).
6. Optional: a free uptime pinger on `/healthz` reduces cold starts.

Once deployed, a customer publishes a bot in **Embed & Share** and integrates it
two ways, both pointing at your public domain:

```html
<!-- 1. drop-in widget on any website -->
<script src="https://YOUR-DOMAIN/widget.js" data-chatbot-key="pk_xxx" async></script>
```
```
2. share-by-link:  https://YOUR-DOMAIN/c/pk_xxx
```

## Enforcing RLS in production

RLS policies exist in the initial migration but are **dormant** when the app
connects as the table owner (owners bypass RLS). To activate enforced isolation,
connect the app as a dedicated non-owner role:

```sql
CREATE ROLE rag_app LOGIN PASSWORD '...';
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rag_app;
-- then set DATABASE_URL to use rag_app
```

Until then, explicit per-query `tenant_id` filtering is the active isolation
guard.

## Free-tier caveats
- First request after idle has cold-start lag (host wakes from sleep).
- Free LLM tiers share rate limits → per-tenant token quotas + provider failover
  keep it usable; heavy concurrent load will throttle.
- pgvector scales well into the hundreds of thousands of chunks; beyond that,
  swap in Qdrant via a new `ChunkRepository` adapter — no domain changes.

## Tests

```powershell
pip install -e ".[dev]"
pytest
```
