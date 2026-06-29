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
