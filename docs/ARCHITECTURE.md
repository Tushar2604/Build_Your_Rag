# RAG Platform — Complete Architecture & Design Documentation

> Authoritative, code-level deep dive into the whole system. Reflects the
> **actual implementation** (not just intent). Where the code currently diverges
> from the README or from each other, it is called out under
> [Known Issues & Discrepancies](#18-known-issues-discrepancies--recommendations).
>
> Companion documents: focused design notes live in [`docs/design/`](design/)
> (`03-database-design` … `18-scaling`). This file is the top-level map that
> connects them.

---

## Table of contents

1. [What this is](#1-what-this-is)
2. [Technology stack & rationale](#2-technology-stack--rationale)
3. [Architectural style: Clean Architecture + DDD](#3-architectural-style-clean-architecture--ddd)
4. [Repository layout](#4-repository-layout)
5. [Domain layer](#5-domain-layer)
6. [Application layer](#6-application-layer)
7. [Infrastructure layer](#7-infrastructure-layer)
8. [Interfaces layer](#8-interfaces-layer)
9. [Configuration & dependency injection](#9-configuration--dependency-injection)
10. [Data model & database](#10-data-model--database)
11. [End-to-end flows](#11-end-to-end-flows)
12. [Multi-tenancy & security model](#12-multi-tenancy--security-model)
13. [Retrieval & RAG internals](#13-retrieval--rag-internals)
14. [The agent system](#14-the-agent-system)
15. [Observability](#15-observability)
16. [Evaluation harness](#16-evaluation-harness)
17. [Frontend architecture](#17-frontend-architecture)
18. [Known issues, discrepancies & recommendations](#18-known-issues-discrepancies--recommendations)
19. [Deployment & operations](#19-deployment--operations)
20. [Configuration reference](#20-configuration-reference)
21. [Testing](#21-testing)
22. [Glossary](#22-glossary)

---

## 1. What this is

A **multi-tenant Retrieval-Augmented Generation (RAG) platform**. A company
registers, uploads documents, and immediately gets a working AI chatbot grounded
in those documents — exposed over a clean HTTP API with streaming answers and
citations, plus an embeddable web widget and a share-by-link page.

Two defining goals shape every decision:

- **Run on free tiers** end to end (Neon Postgres + Cloudflare R2 + Gemini/Groq
  free LLM APIs + a single free web host), *while*
- keeping a **production-grade internal architecture** so it can grow into paid
  infrastructure by swapping adapters, never by rewriting the core.

It offers **two answering modes** over the same corpus:

| Mode | Use case | Endpoint | Engine |
|---|---|---|---|
| **Single-shot RAG** | one retrieve → one generate | `AskChatbot` / `RagGraph` | `src/application/use_cases/ask_chatbot.py`, `src/infrastructure/rag/graph.py` |
| **Multi-step agent** | ReAct loop that may search several times | `RunAgent` / `AgentLoop` | `src/application/use_cases/run_agent.py`, `src/application/agent/loop.py` |

…and **three integration surfaces**: authenticated admin/JSON API, public widget
(`/widget.js` + `/api/v1/public/*`), and an MCP server for AI clients.

---

## 2. Technology stack & rationale

| Concern | Choice | Why |
|---|---|---|
| API framework | **FastAPI** (async) | SSE streaming, Pydantic validation, OpenAPI for free |
| Datastore | **Postgres** (Neon) | One free datastore for relational data *and* vectors |
| Vector search | `embedding` column + cosine | See [§13](#13-retrieval--rag-internals) — *currently in-Python brute force*, not pgvector ANN |
| Object storage | **Cloudflare R2** (S3 API) via boto3 | Free; host disk is ephemeral. Local-disk fallback in dev |
| Embeddings | **Gemini** `gemini-embedding-001` (768-dim) | Free ingestion |
| Generation | **Groq** primary, **Gemini** fallback (Ollama optional) | Two free pools + automatic failover; Ollama = fully local/offline |
| Background work | FastAPI `BackgroundTasks` | No always-on worker = no cost; ingestion is resumable |
| Auth | **JWT** + per-tenant **API keys** | Stateless, horizontally scalable |
| Password hashing | **Argon2** | Memory-hard, modern default |
| ORM / migrations | **SQLAlchemy 2 (async)** + **Alembic** | Async throughout; versioned schema incl. RLS |
| Agent orchestration | hand-rolled **ReAct loop** + **LangGraph** (RAG graph) | Provider-agnostic, runs over plain `generate()` |
| Observability | structlog + Prometheus + optional **Langfuse**/**OpenTelemetry** | LLM-native traces + system spans, all optional |
| Frontend | **React + Vite + TailwindCSS** (TypeScript) | Built to static assets, served by the API |

**Deliberately absent:** Redis, Celery, Qdrant. At this scale, pgvector-style
search in Postgres + in-process tasks + a Postgres usage-counter table cover
those roles for free. The ports/adapters design means each can be reintroduced
behind an existing port without touching the domain.

---

## 3. Architectural style: Clean Architecture + DDD

The codebase is organized into four concentric layers. **Dependencies point
inward only** — the domain knows nothing about FastAPI, SQLAlchemy, or any
provider SDK.

```
            ┌─────────────────────────────────────────────┐
            │                 interfaces/                  │  FastAPI routers, SSE,
            │  (HTTP, SSE, MCP, SPA serving, widget.js)    │  auth deps, middleware, MCP
            │   ┌─────────────────────────────────────┐   │
            │   │            infrastructure/          │   │  SQLAlchemy+Postgres, Gemini/
            │   │  (adapters implementing the ports)  │   │  Groq/Ollama, R2, JWT, LangGraph
            │   │   ┌─────────────────────────────┐   │   │
            │   │   │        application/          │   │   │  use cases + PORTS (Protocols),
            │   │   │  (use cases, ports, agent)  │   │   │  the agent loop/router/registry
            │   │   │   ┌─────────────────────┐   │   │   │
            │   │   │   │      domain/        │   │   │   │  entities, value objects,
            │   │   │   │  (pure business)    │   │   │   │  events, state machines
            │   │   │   └─────────────────────┘   │   │   │
            │   │   └─────────────────────────────┘   │   │
            │   └─────────────────────────────────────┘   │
            └─────────────────────────────────────────────┘
                         config/  = composition root (DI) + settings
```

**The dependency rule in practice**

- `domain/` imports nothing from the outer layers. Pure dataclasses + enums.
- `application/` defines **ports** as `typing.Protocol`s (`ports/repositories.py`,
  `ports/services.py`, `ports/observability.py`) and orchestrates them in **use
  cases**. It never imports a concrete adapter.
- `infrastructure/` provides concrete **adapters** that satisfy the ports
  (SQLAlchemy repositories, Gemini embedder, Groq/Gemini/Ollama providers, R2
  storage, JWT, the LangGraph RAG pipeline, the agent tools).
- `interfaces/` is the delivery mechanism (HTTP/SSE/MCP). It depends on the
  application use cases and on the `Container` for wiring.
- `config/container.py` is the **only** place that constructs concrete
  infrastructure and binds it to ports — the composition root.

This is what lets the README claim "swap Qdrant in via a new `ChunkRepository`
adapter, no domain changes": the seam is the port.

---

## 4. Repository layout

```
src/
  domain/                       Pure business core (no frameworks)
    shared/                     identifiers, errors, base events
    tenant/                     Tenant + User + ApiKey entities, events
    document/                   Document + Chunk entities, ingestion state machine, events
    chatbot/                    Chatbot aggregate, RetrievalConfig, WidgetConfig, origin policy
    chat/                       ChatSession, Message, Citation entities, events
  application/
    ports/                      repositories.py, services.py, observability.py (Protocols)
    use_cases/                  register_tenant, authenticate, ingest_document, documents,
                                ask_chatbot, run_agent
    agent/                      loop.py (ReAct), router.py (model routing), registry.py,
                                tools.py (Tool port), trace.py (AgentTrace)
    dtos.py                     input/output DTOs across the use-case boundary
  infrastructure/
    persistence/                database.py, models.py (ORM), mappers.py, repositories.py,
                                unit_of_work.py
    llm/                        embeddings.py (Gemini), providers.py (Groq/Gemini/Ollama + failover)
    parsing/                    parser.py (PDF/DOCX/MD/TXT), chunker.py (recursive overlap)
    storage/                    object_storage.py (R2 + local disk)
    rag/                        graph.py (LangGraph retrieve→assemble→generate)
    agent/                      builder.py (wires the loop), document_search_tool.py
    ratelimit/                  anon.py (sliding window)
    security/                   hashing.py (Argon2 + api-key hash), tokens.py (JWT)
    messaging/                  event_bus.py (in-process pub/sub)
    observability/              logging.py, tracing.py, langfuse_tracer.py, otel.py
  interfaces/
    api/                        app.py (factory), deps.py (auth), middleware.py, errors.py,
                                schemas.py, routers/ (auth, documents, uploads, chatbots,
                                chat, agent, analytics, public, health)
      static/widget.js          the embeddable widget script
    mcp/                        server.py (FastMCP), tools.py (tenant-scoped MCP tools)
  config/                       settings.py (Pydantic), container.py (DI)
migrations/                     Alembic: 0001 initial+RLS+vector, 0002 provider, 0003 logs, 0004 widget
evals/                          Golden-dataset eval harness (runner, judge, metrics, regression, cli)
frontend/                       React + Vite + Tailwind SPA (admin app + public chat pages)
deploy/                         fly.toml, render.yaml
scripts/start.sh                migrate + launch (container entrypoint)
tests/                          pytest (domain unit tests + integration-ish module tests)
```

---

## 5. Domain layer

Pure Python dataclasses/enums. No I/O, no framework imports. This is the part you
can unit-test with zero mocks.

### 5.1 Shared kernel (`domain/shared/`)

- **identifiers.py** — typed IDs (`TenantId`, `UserId`, `DocumentId`,
  `ChatbotId`, `SessionId`) and `new_id()` (UUIDs). Typed IDs prevent passing a
  document id where a tenant id is expected.
- **errors.py** — the domain error hierarchy: `NotFoundError`,
  `InvalidStateError`, `QuotaExceededError`, `RateLimitedError`, etc. The API
  error handler ([`interfaces/api/errors.py`](../src/interfaces/api/errors.py))
  maps each to an HTTP status, so use cases raise *domain* errors and never
  import `HTTPException`.
- **events.py** — base domain-event type; concrete events live per aggregate.

### 5.2 Tenant aggregate (`domain/tenant/`)

`Tenant` (quotas: `daily_token_quota`, `max_documents`, `is_active`), `User`
(email, password hash, role), `ApiKey` (hashed key + prefix). These model the
account boundary that *all* isolation keys off.

### 5.3 Document aggregate (`domain/document/entities.py`)

The **resumable ingestion state machine** — the most important domain invariant.

```
PENDING ──► UPLOADED ──► PARSING ──► CHUNKING ──► EMBEDDING ──► READY
   │            │            │            │             │
   └────────────┴────────────┴────────────┴─────────────┴──► FAILED
                                                  FAILED ──► UPLOADED   (retry re-enters)
```

- `_TRANSITIONS` encodes the only legal forward moves; `transition_to()` raises
  `InvalidStateError` on an illegal jump. This is what makes resumption safe:
  each step is explicit and persisted, so a host that sleeps mid-`EMBEDDING` can
  be picked up exactly where it left off.
- `mark_failed(reason)` records the error; `mark_ready(chunk_count)` finalizes.
- `Chunk` = a retrievable slice (tenant_id, document_id, ordinal, text,
  token_estimate). The embedding vector is stored alongside in the persistence
  layer, not on the domain entity.

### 5.4 Chatbot aggregate (`domain/chatbot/entities.py`)

- `Chatbot` — name, `system_prompt` (defaults to the strict
  `DEFAULT_SYSTEM_PROMPT`), `RetrievalConfig`, `allowed_document_ids` (empty =
  all ready docs), publishing fields (`is_public`, `public_key`,
  `allowed_origins`, `widget`).
- `RetrievalConfig(top_k=5, min_score=0.0, rerank=False)` — `min_score` is the
  cosine floor (0 = no filter). **`rerank` is a phase-2 placeholder.**
- `DEFAULT_SYSTEM_PROMPT` — instructs *"Answer using ONLY the provided context
  below … Never answer from general knowledge"* and gives an exact refusal
  string used as the grounding signal downstream.
- `generate_public_key()` → `pk_<token>` (Stripe-style publishable key, safe to
  embed). `origin_allowed()` implements the embed allowlist policy (exact match
  or `*.example.com` wildcard; empty list = any origin).
- `WidgetConfig` — owner-controlled theme (color, display name, welcome message,
  launcher position).

### 5.5 Chat aggregate (`domain/chat/`)

`ChatSession`, `Message` (role enum USER/ASSISTANT, content, `citations`,
`tokens_used`, `provider`), `Citation` (document_id, chunk_id, ordinal, score,
snippet). Events: `MessageAnswered` (drives usage/analytics).

---

## 6. Application layer

### 6.1 Ports (`application/ports/`)

Protocols the use cases depend on. Key ones:

- **repositories.py** — `UnitOfWork` (the transaction boundary exposing
  `tenants`, `users`, `api_keys`, `documents`, `chunks`, `chatbots`, `chats`,
  `usage`, `analytics`, `request_logs`), plus each repository protocol and the
  `RequestLog` row type. `ChunkRepository.search(...)` is the retrieval seam.
- **services.py** — `Embedder`, `LLMProvider` (`generate()` + `stream()` +
  `LLMResult`), `DocumentParser`, `Chunker`, `ObjectStorage`, `EventBus`,
  `PasswordHasher`, `TokenService`.
- **observability.py** — `Tracer` / span protocol with a `NoOpTracer` default.

### 6.2 Use cases (`application/use_cases/`)

Each use case owns the **cross-cutting platform concerns** (tenant scope, quota,
rate limit, request logging, event emission) around a thin core.

| Use case | Responsibility |
|---|---|
| `register_tenant` | Create tenant + owner user + initial API key |
| `authenticate` | Verify credentials, mint JWT access/refresh tokens |
| `ingest_document` | The resumable pipeline + `ResumePendingIngestions` startup sweep |
| `documents` | List / get / retry / delete documents |
| `ask_chatbot` | Single-shot RAG: retrieve → context → quota → generate → persist |
| `run_agent` | Multi-step agent with the same guard-rails |

**A critical, repeated pattern — never hold a DB connection across a network
call.** Free-tier Postgres (Neon) caps connections hard, so `AskChatbot` opens a
*short* transaction to validate/quota/persist the user message, **releases it**,
runs the embedding + vector-search in another short transaction, then runs the
(slow) LLM call with **no transaction open**, and finally opens a last short
transaction to persist the answer + usage + request log. See
[`ask_chatbot.py`](../src/application/use_cases/ask_chatbot.py) lines 72–170.

**Request logging is best-effort and always-on.** Every ask — success *or*
failure — writes a `RagRequestLogModel` row (retrieval trace, scores,
`no_context`, `refused`, latency, provider/model, tokens). A logging failure is
swallowed so it can never mask the real error or break the response.

### 6.3 Agent core (`application/agent/`)

Provider-agnostic ReAct loop that runs on the *plain* `generate()` port (no
native tool-calling API required), so it works over Groq **and** Gemini **and**
through the failover router. Covered in detail in [§14](#14-the-agent-system).

---

## 7. Infrastructure layer

### 7.1 Persistence (`infrastructure/persistence/`)

- **database.py** — async engine + `async_sessionmaker`; TLS handling for managed
  Postgres (see settings `database_url_async` / `database_connect_args`).
- **models.py** — SQLAlchemy 2 ORM (`TenantModel`, `UserModel`, `ApiKeyModel`,
  `DocumentModel`, `ChunkModel`, `ChatbotModel`, `ChatSessionModel`,
  `ChatMessageModel`, `RagRequestLogModel`, `UsageCounterModel`,
  `AuditEventModel`). **`ChunkModel.embedding` is `ARRAY(Float)`** (see
  [§13](#13-retrieval--rag-internals) and [§18](#18-known-issues-discrepancies--recommendations)).
- **mappers.py** — translate ORM rows ⇄ domain entities, so the domain never
  sees SQLAlchemy.
- **repositories.py** — concrete repository implementations. Notably
  `ChunkRepositoryImpl.search()` loads candidate rows and computes cosine
  similarity, and `AnalyticsRepositoryImpl` aggregates `rag_request_logs`.
- **unit_of_work.py** — `SqlAlchemyUnitOfWork`: one session = one transaction,
  wires all repositories, binds `app.tenant_id` for RLS via
  `set_config(..., true)` (transaction-local), and **dispatches collected domain
  events only after a successful commit**.

### 7.2 LLM & embeddings (`infrastructure/llm/`)

- **embeddings.py** — `GeminiEmbedder`: calls the Gemini `embedContent` REST API
  directly (httpx, retry/backoff), with `RETRIEVAL_DOCUMENT` vs `RETRIEVAL_QUERY`
  task types and `outputDimensionality = embedding_dim` (768).
- **providers.py** — `GroqProvider`, `GeminiProvider`, `OllamaProvider` (each
  with `generate()` + token-streaming `stream()`), and the **`FailoverLLM`**
  router that tries primary then secondary on any exception. Each leaf reports
  its name through an `on_provider` callback so the persisted answer records the
  backend that *actually* served (failover-aware analytics). `build_llm()` reads
  `generation_primary` / `generation_secondary` from settings.

### 7.3 Parsing (`infrastructure/parsing/`)

- **parser.py** — `MultiFormatParser`: PDF (pypdf), DOCX (python-docx), Markdown,
  plain text. CPU-bound extraction runs in a thread (`asyncio.to_thread`) so it
  never blocks the event loop.
- **chunker.py** — `RecursiveChunker(target_chars=1200, overlap_chars=150)`:
  splits on the largest natural boundary that fits (`\n\n` → `\n` → `. ` → ` `),
  then merges pieces back up to the target with a trailing-overlap window so
  context survives chunk edges. Character-based (≈4 chars/token) to avoid a
  tokenizer dependency.

### 7.4 Storage (`infrastructure/storage/object_storage.py`)

`R2Storage` (boto3 S3 API; presigned PUT, get/put/delete bytes) and
`LocalDiskStorage` (dev fallback whose "presigned" URL points back at an internal
upload route, so the upload flow is identical in dev and prod). `build_storage()`
picks based on `use_object_storage`.

### 7.5 RAG pipeline (`infrastructure/rag/graph.py`)

A **LangGraph** `StateGraph`: `retrieve → assemble → generate → END`. Making it a
graph (not an ad-hoc function) keeps each node independently testable and lets you
later insert `rerank` / `guardrail` / `query-rewrite` nodes without rewriting the
flow. The streaming endpoint reuses `retrieve` (+ context build) then streams
`generate` itself token-by-token. Details in [§13](#13-retrieval--rag-internals).

### 7.6 Agent adapters (`infrastructure/agent/`)

- **document_search_tool.py** — `DocumentSearchTool`, the agent's grounding tool
  (`search_documents`). Embeds the query, runs a tenant-scoped vector search in
  its own short UoW, returns ranked snippets as both an observation string and
  structured `citations` data.
- **builder.py** — `build_agent_loop(container)`: registers the tools, builds the
  `ModelRouter`, and constructs the `AgentLoop` with the step budget and tracer.

### 7.7 Cross-cutting infra

- **ratelimit/anon.py** — `SlidingWindowRateLimiter` (in-process). Two instances:
  anonymous public-widget traffic and the per-tenant agent burst guard.
- **security/hashing.py** — Argon2 password hashing + `hash_api_key()`.
- **security/tokens.py** — `JwtTokenService` (encode/decode access & refresh).
- **messaging/event_bus.py** — `InProcessEventBus` pub/sub for domain events.
- **observability/** — see [§15](#15-observability).

---

## 8. Interfaces layer

### 8.1 API application (`interfaces/api/app.py`)

`create_app()` factory wires, in order:

1. `PublicCorsMiddleware` — reflective, **credential-free** CORS for
   `/api/v1/public/*` and `/widget.js` (so any third-party page can call them).
2. `CORSMiddleware` — credentialed CORS for the authenticated admin/API surface.
3. `ObservabilityMiddleware` — correlation-id binding + Prometheus latency/count
   metrics keyed by route template (bounded cardinality).
4. Error handlers (domain errors → HTTP statuses).
5. Routers: ops at root (`/healthz`, `/readyz`, `/metrics`), `/widget.js`, and
   everything else under `/api/v1`.
6. **SPA catch-all mounted last** (`_mount_spa`) so it never shadows API/ops
   routes; unknown non-API paths fall back to `index.html` so client-side routing
   survives a hard refresh.

**Lifespan**: on startup, runs `ResumePendingIngestions` (picks up any document
left mid-pipeline by a prior shutdown); on shutdown, flushes telemetry and
disposes the DB engine.

**Single deployable origin**: in production the Docker build runs `vite build`
and FastAPI serves the SPA, the share page (`/c/<key>`), `/widget.js`, *and* the
API from one origin — which is exactly what lets a generated embed snippet / link
work on any visitor's machine. Locally `frontend/dist` is absent, so Vite serves
the SPA and `_mount_spa` is a no-op.

### 8.2 Authentication (`interfaces/api/deps.py`)

`current_principal` accepts **either** a Bearer JWT (user sessions) **or** an
`X-API-Key` header (programmatic). Both resolve to a `Principal{tenant_id,
user_id, role}`. **The tenant id is never read from the request body** — it comes
from the verified credential. This is the linchpin of tenant isolation at the
edge.

### 8.3 Routers (`interfaces/api/routers/`)

| Router | Surface |
|---|---|
| `auth` | register, login, refresh |
| `documents` | create (→ presigned upload URL), complete (→ schedule ingest), get/list/status, retry, delete |
| `uploads` | internal raw-bytes PUT endpoint for the local-disk storage fallback |
| `chatbots` | CRUD, publish toggle, `allowed_origins`/`widget` config, `rotate-key` |
| `chat` | create session, ask (JSON), **ask (SSE stream)** |
| `agent` | multi-step agent ask (JSON), with per-tenant rate limit |
| `analytics` | tenant dashboards over `rag_request_logs` |
| `public` | keyed, unauthenticated widget API (config, session, messages, stream) |
| `health` | `/healthz` liveness, `/readyz` DB check, `/metrics` Prometheus |

### 8.4 SSE streaming (`routers/chat.py::ask_stream`)

The streaming contract emits three event types over `text/event-stream`:

1. `citations` — JSON array, sent up front (retrieval runs before generation).
2. `token` — one per LLM delta, streamed as they arrive.
3. `done` — `{tokens_used}`; (or `error` if generation throws).

Retrieval runs through a `_ChunkRepoProxy` that opens its own short transaction
rather than holding one open for the whole stream. The full answer + usage +
request log are persisted at the end. **Whitespace in `token` data is
significant** — see the frontend parser note in [§17](#17-frontend-architecture)
and the bug fixed in [§18](#18-known-issues-discrepancies--recommendations).

### 8.5 MCP server (`interfaces/mcp/`)

A **FastMCP** stdio server (`python -m src.interfaces.mcp.server`) that resolves
the tenant once from `MCP_TENANT_API_KEY`, then exposes three tenant-scoped
tools to any MCP client (e.g. Claude Desktop): `search_documents`,
`list_documents`, `answer_question`. The tool *implementations* in `tools.py` are
SDK-independent (the MCP SDK is imported lazily inside `server.py`), so they unit
test without the dependency. The connector **inherits the platform's
access-control model** rather than inventing its own.

---

## 9. Configuration & dependency injection

### 9.1 Settings (`config/settings.py`)

A single Pydantic `BaseSettings` is the **only** place that reads the
environment. Highlights:

- **Fail-fast prod safety**: in `production`, a placeholder `JWT_SECRET` raises at
  boot (`_require_strong_secret_in_prod`).
- **Managed-Postgres DSN hygiene**: `database_url_async` strips libpq-only query
  params (`sslmode`, `channel_binding`, …) that asyncpg rejects, and
  `database_connect_args` re-applies TLS for any non-local host. This is why a
  raw Neon/Supabase/Render connection string "just works".
- Async driver is coerced (`postgresql://` → `postgresql+asyncpg://`).
- Computed properties: `use_object_storage`, `is_production`, `langfuse_enabled`,
  `public_widget_base`, `public_frontend_base`.
- `get_settings()` is `@lru_cache`d — parsed once per process.

### 9.2 Composition root (`config/container.py`)

`Container` builds process-lifetime **singletons** (event bus, tracer, embedder,
failover LLM, storage, parser, chunker, hasher, JWT service, the two rate
limiters, the prebuilt agent loop) and hands out a **fresh `UnitOfWork` per use
case** via `unit_of_work()`. **Nothing outside this module imports a concrete
infrastructure class** — that is what enforces the dependency direction.
`get_container()` is `@lru_cache`d.

---

## 10. Data model & database

### 10.1 Tables (migration `0001` + `0002`–`0004`)

```
tenants            (id, name, slug, daily_token_quota, max_documents, is_active, created_at)
users              (id, tenant_id→, email, password_hash, role, is_active, created_at)
api_keys           (id, tenant_id→, name, key_hash, prefix, is_active, created_at)
documents          (id, tenant_id→, filename, content_type, size_bytes, storage_key,
                    checksum, status, chunk_count, error, created_at, updated_at)
document_chunks    (id, tenant_id, document_id→, ordinal, text, token_estimate, embedding)
chatbots           (id, tenant_id→, name, system_prompt, retrieval JSONB,
                    allowed_document_ids JSONB, is_public, public_key, allowed_origins JSONB,
                    widget_config JSONB, created_at)
chat_sessions      (id, tenant_id→, chatbot_id→, title, created_at)
chat_messages      (id, tenant_id, session_id→, role, content, citations JSONB,
                    tokens_used, provider, created_at)
rag_request_logs   (id, tenant_id, chatbot_id, session_id, message_id, query, retrieved JSONB,
                    num_retrieved, max_score, no_context, refused, answer, provider, model,
                    tokens_used, status, error, latency_ms, created_at)
usage_counters     (id, tenant_id, day, tokens_used)  UNIQUE(tenant_id, day)
audit_events       (id, tenant_id, name, payload JSONB, occurred_at)
```

- **`usage_counters`** (unique on `tenant_id, day`, atomic upsert) is the
  Redis-free quota mechanism: `tokens_used_today` / `add_tokens`.
- **`rag_request_logs`** is the per-request provenance/eval log, written for
  *every* ask (separate from `chat_messages`, which only records successful
  conversation turns). Migration `0002` added `provider` to messages, `0003`
  added the request-log table, `0004` added the public-widget columns to
  `chatbots`.

### 10.2 Row-Level Security

Migration `0001` enables RLS and a `tenant_isolation` policy on every
tenant-scoped table, keyed on
`current_setting('app.tenant_id', true)::uuid`. The `UnitOfWork` binds that GUC
per transaction.

**Important:** table **owners bypass RLS**, so the policies are *dormant* while
the app connects as the owner. To enforce them, connect the app as a dedicated
non-owner role (`rag_app`) with table-level grants (steps in the README). Until
then, **the active isolation guard is explicit per-query `tenant_id` filtering**
in every repository. Defense-in-depth, two layers.

### 10.3 Migrations

Alembic, run automatically on container start (`scripts/start.sh`). `EMBEDDING_DIM`
is read from settings so the schema matches the configured embedding size.

---

## 11. End-to-end flows

### 11.1 Registration & auth

```
POST /api/v1/auth/register {tenant_name, email, password}
  → RegisterTenant: create Tenant + owner User (Argon2 hash) + API key  → JWT
POST /api/v1/auth/login → Authenticate: verify → access + refresh JWT
Subsequent calls: Authorization: Bearer <jwt>  (or X-API-Key)
  → deps.current_principal → Principal{tenant_id,…}
```

### 11.2 Document ingestion (resumable)

```
POST /api/v1/documents {filename, content_type, size_bytes}
   → create Document(PENDING) + presigned PUT URL
PUT <upload_url> (raw bytes)            → bytes land in R2 (or local disk)
POST /api/v1/documents/{id}/complete    → Document PENDING→UPLOADED, schedule BackgroundTask
   IngestDocument.execute:
     UPLOADED → PARSING   (fetch bytes, extract text)        [persist]
             → CHUNKING   (recursive overlap chunker)        [persist]
             → EMBEDDING  (delete prior chunks; embed in batches of 64; upsert) [persist]
             → READY      (chunk_count set)  + emit DocumentIngested
   on any error → mark_failed(reason) + emit DocumentIngestionFailed
GET /api/v1/documents/{id} → status pending|…|ready|failed
POST .../retry → FAILED→UPLOADED re-enters the pipeline
```

On startup, `ResumePendingIngestions` re-runs any document left in a non-terminal
state. Embedding deletes prior chunks first, so a resumed/retried run is
**idempotent**.

### 11.3 Single-shot RAG ask (JSON)

```
POST /api/v1/sessions/{id}/messages {message}
  txn1: load session+chatbot+tenant; enforce daily quota; persist USER message; commit
  embed query (no txn) → txn2: vector search top_k, min_score → citations; commit
  build context string from citations
  LLM generate(system_prompt, "Context:…\n\nQuestion:…")   (NO txn open; failover-aware)
  txn3: persist ASSISTANT message + add_tokens + rag_request_log + emit MessageAnswered; commit
  → {message_id, answer, citations[], tokens_used, provider}
```

### 11.4 Streaming ask (SSE)

```
POST /api/v1/sessions/{id}/stream {message}
  short txn: validate, quota, persist USER message; commit
  retrieve_only (proxy txn) → citations → build context
  SSE:  event:citations  → event:token (×N) → event:done
  after stream: persist ASSISTANT message + usage + request log
```

### 11.5 Multi-step agent ask

```
POST /api/v1/agent/sessions/{id}/ask {message}
  short txn: validate; quota; per-tenant rate-limit; persist USER message; commit
  AgentLoop.run(ToolContext{tenant_id, chatbot_id, allowed_document_ids}, message):
     think → emit JSON action → execute tool (search_documents) → observe → repeat
     until "final" action or max_steps budget
  citations recovered + de-duped from the trace (highest score per chunk)
  short txn: persist answer + usage + request log (full trace) + event; commit
  → answer + citations + steps[] + tools_used + stop_reason
```

### 11.6 Public widget / share link

```
<script src="https://APP/widget.js" data-chatbot-key="pk_xxx" async></script>
   → Shadow-DOM floating bubble; streams over the public API.
GET  /api/v1/public/chatbots/{pk}/config            → theme + name
POST /api/v1/public/chatbots/{pk}/sessions          → session_id
POST /api/v1/public/chatbots/{pk}/sessions/{id}/stream → SSE

Anonymous guards, in order:
  pk_ resolves to a PUBLIC bot → request Origin on the bot's allowlist (empty=any)
  → per-IP+bot sliding-window rate limit → owning tenant's daily token quota
```

---

## 12. Multi-tenancy & security model

**Isolation is layered, not single-point:**

1. **Edge** — tenant id comes only from the verified JWT/API-key
   (`deps.current_principal`), never from the body.
2. **Application** — every use case calls `uow.set_tenant_scope(tenant_id)` and
   passes `tenant_id` explicitly into repository queries.
3. **Repository** — every query filters by `tenant_id` (the *active* guard).
4. **Database** — RLS policies keyed on `app.tenant_id` (dormant until a
   non-owner DB role is used; then a forgotten filter still can't leak).
5. **Tools/agent** — `ToolContext.tenant_id` scopes every tool call; a model
   asking for data cannot widen scope.

**Other controls**

- **Secrets**: JWT secret strength enforced in prod; passwords Argon2-hashed;
  API keys stored only as hashes (with a short non-secret prefix for display).
- **Public surface**: publishable `pk_` keys are non-secret by design — the
  *layered guards* (public-bot check → origin allowlist → rate limit → quota)
  contain abuse, not the key. `rotate-key` invalidates an embedded snippet.
- **CORS**: public routes reflect the origin **without credentials**; the
  per-chatbot allowlist (enforced in-handler, returns 403) is the real
  authorization layer. The admin API uses standard credentialed CORS.
- **Abuse/cost**: per-tenant daily token quota (hard backstop), per-tenant agent
  rate limit, per-IP+bot anonymous rate limit, upload size cap, max documents.

See [`docs/design/05-authentication.md`](design/05-authentication.md),
[`12-multi-tenancy.md`](design/12-multi-tenancy.md),
[`17-security-review.md`](design/17-security-review.md).

---

## 13. Retrieval & RAG internals

### 13.1 The pipeline (`RagGraph`)

```
retrieve:  embed_query(question, RETRIEVAL_QUERY)
           chunks.search(tenant_id, vec, top_k, document_ids, min_score) → Citations
assemble:  keep citations with score ≥ chatbot.retrieval.min_score
           build context = "[Source N | doc=… | score=…]\n<snippet>" joined, or
           "(no relevant context found)"
generate:  llm.generate(system_prompt, "Context:…\n\nQuestion:…")
```

### 13.2 Chunking & embedding

- Recursive, overlap-aware chunking (~1200 chars, 150 overlap).
- Gemini `gemini-embedding-001` at 768 dims, with task-type hints
  (`RETRIEVAL_DOCUMENT` for chunks, `RETRIEVAL_QUERY` for queries) — asymmetric
  embedding improves retrieval quality.
- Embedding done in batches of 64 to respect free-tier limits.

### 13.3 How the vector search actually works (important)

Despite the "pgvector" naming in docs, the **current implementation does not use
a pgvector index**. `ChunkModel.embedding` is a plain `ARRAY(Float)`, and
`ChunkRepositoryImpl.search()`:

1. `SELECT`s the tenant's candidate chunk rows (optionally filtered by
   `document_id`),
2. computes cosine similarity **in Python** for each row,
3. sorts, applies `min_score`, and returns the top-`k`.

This is correct and fine for the free-tier scale (hundreds of thousands of chunks
is the stated ceiling), and cosine is computed properly (normalized by both
magnitudes, so vector normalization is not required). But it is **O(n) per query
per tenant**, loads vectors into the app, and won't scale like a true ANN index.
Migrating to a pgvector `Vector` column + `ivfflat`/`hnsw` index (or Qdrant) is
the intended growth path — and is a **drop-in `ChunkRepository` adapter swap**,
no domain changes. See [§18](#18-known-issues-discrepancies--recommendations).

### 13.4 Grounding & refusal

The default system prompt forces context-only answering and a fixed refusal
string. Downstream, `refused` is detected by that string (prompt-independent
signal: `no_context`). With a weak local model (e.g. `qwen3:8b` via Ollama),
instruction-following is less reliable — if the context is empty it may answer
from parametric knowledge anyway, so keeping retrieval healthy (a sane
`min_score`) matters more than the prompt alone.

See [`docs/design/07-chunking-engine.md`](design/07-chunking-engine.md),
[`08-embedding-service.md`](design/08-embedding-service.md),
[`09-retrieval-engine.md`](design/09-retrieval-engine.md),
[`10-chat-service.md`](design/10-chat-service.md),
[`11-llm-gateway.md`](design/11-llm-gateway.md).

---

## 14. The agent system

A hand-rolled **ReAct** loop (`application/agent/loop.py`) over the plain
`generate()` port — no native tool-calling API required.

### 14.1 The loop

```
system = template(catalog of tools, refusal string)
transcript = "Question: …"
for step in range(max_steps):
    decision = router.route(question, step_index)         # cheap vs strong tier
    raw = decision.provider.generate(system, transcript)  # one JSON action
    parse → (thought, action, action_input | parse_error)
    if parse_error:  feed corrective observation, continue   # recoverable
    if action == "final":  return answer
    tool = registry.get(action)
    if tool is None: feed "unknown tool" observation, continue
    observation = await tool.run(ctx, **action_input)     # tenant-scoped
    transcript += Thought/Action/Observation
# budget exhausted → one last grounded "answer now" call (stop_reason=max_steps)
```

### 14.2 Design choices that reflect real agent failure modes

- **Hard `max_steps` budget** (`AGENT_MAX_STEPS`, default 6) — a non-converging
  agent must terminate with a best-effort answer, never loop forever or burn the
  token quota.
- **Defensive action parsing** — models wrap JSON in prose/markdown fences or
  hallucinate a tool name; both become *recoverable observations* the planner can
  correct next turn, not crashes (`_parse_action` grabs the first `{…}`).
- **Model routing** (`router.py`) — a cheap heuristic (length, reasoning markers
  like *compare/why/explain*, current step depth) escalates hard turns to a
  stronger model. With one provider it's a no-op that still records the chosen
  tier in the trace (the seam exists for when a second tier is configured).
- **Full `AgentTrace`** (`trace.py`) — every step (thought/action/observation/
  model/tokens) is recorded for observability + eval, persisted on the request
  log, and surfaced in the API response (`steps[]`, `tools_used`, `stop_reason`).

### 14.3 Tools

`Tool` is a Protocol (`tools.py`): `spec: ToolSpec` (name, description, lightweight
param schema rendered into the planner prompt) + async `run(ctx, **kwargs) →
ToolResult{observation, data, ok}`. The shipped tool is `search_documents`
(`infrastructure/agent/document_search_tool.py`). `ToolContext` carries
`tenant_id` so access control is enforced even though "a model asked for it."

Citations from multiple search steps are **de-duplicated** in `run_agent`
(`_citations_from_trace`), keeping the highest-scoring occurrence of each chunk.

See [`docs/design/16-mcp-integration.md`](design/16-mcp-integration.md).

---

## 15. Observability

Three complementary layers, all optional and off by default:

- **Structured logging** (`observability/logging.py`) — structlog with a
  per-request `correlation_id` bound by `ObservabilityMiddleware` and echoed in
  the `x-correlation-id` response header.
- **Metrics** (`/metrics`) — Prometheus `REQUEST_COUNT` / `REQUEST_LATENCY`
  labelled by method + **route template** (bounded cardinality) + status.
- **AI-native tracing** (`tracing.py` → `langfuse_tracer.py` / `otel.py`) —
  `build_tracer()` returns Langfuse, OTel, both, or a `NoOpTracer`. The agent
  loop opens a root span per answer with nested step/tool spans; the
  `search_documents` tool records a `top_retrieval_score` span score (the "review
  outputs" signal). Telemetry is flushed on shutdown.

Toggle via `LANGFUSE_*` / `OTEL_ENABLED`. See
[`docs/design/15-observability.md`](design/15-observability.md).

---

## 16. Evaluation harness

A golden-dataset eval suite under [`evals/`](../evals/) (`docs/design/14`).

- **dataset.py** — `GoldenDataset` of cases (`question`, `relevant_doc_ids`,
  `expect_refusal`, `tags`).
- **target.py** — `EvalTarget` abstraction (run against the live RAG path, the
  agent, etc.).
- **metrics.py** — deterministic retrieval metrics (`RetrievalScores`:
  precision/recall@k, etc.), `citation_grounding`, and `refusal_correct` (a
  policy check applied to every case).
- **judge.py** — optional `LLMJudge` for subjective axes (`faithfulness`,
  `answer_relevance`); the runner skips it for refusal cases and when no judge is
  wired, so the harness runs **fully offline** in CI.
- **runner.py** — drives each case, aggregates per-metric means *only over cases
  where the metric applies* (a sparse metric isn't dragged down by absent rows).
- **regression.py** / **report.py** / **cli.py** — compare against a baseline and
  render reports; tests in `tests/test_eval_*`.

---

## 17. Frontend architecture

React + Vite + TailwindCSS SPA (`frontend/`), TypeScript.

- **Pages**: dashboard (assistants, documents/knowledge, analytics, settings),
  `ChatPage` (authenticated chat), `EmbedChatPage` + `WidgetChatPage` (public
  share/embed), auth pages.
- **API layer** (`src/api/`): `client.ts` (fetch wrapper + JWT header +
  `streamSSE`), `chat.ts`, `public.ts`, etc. Auth token in `localStorage`,
  attached as `Authorization: Bearer`.
- **SSE parsing**: `streamSSE` (authenticated) and `streamPublic` (public) parse
  the `text/event-stream`. **Token whitespace and newlines are significant** —
  the parser must *not* trim token payloads (it strips only the single
  spec-mandated leading space after `data:` and rejoins multi-line data with
  `\n`). Assistant bubbles render with `whitespace-pre-wrap` so line breaks show.
- **Build & serve**: `vite build` → `frontend/dist`, served by FastAPI from the
  same origin in production. The embeddable widget itself is a separate,
  dependency-free script at `interfaces/api/static/widget.js` (Shadow DOM, zero
  CSS clashes).

---

## 18. Known issues, discrepancies & recommendations

These are places where the **code** and the **docs/each-other** diverge, or where
a known foot-gun lives. Worth tracking.

1. **"pgvector" is aspirational.** `ChunkModel.embedding` is `ARRAY(Float)` and
   `ChunkRepositoryImpl.search()` computes cosine **in Python** over all of a
   tenant's chunks — there is no pgvector `Vector` column or ANN index, despite
   the README/migration docstrings saying "pgvector / cosine inside Postgres."
   Fine at free-tier scale; the growth path is a `ChunkRepository` adapter swap
   to a real `Vector` + `ivfflat`/`hnsw` index or Qdrant. *(Action: either
   migrate to pgvector or update the docs to match reality.)*

2. **`min_score` defaults & inconsistency (recently fixed in part).**
   - `RetrievalConfig.min_score` default is `0.0` (no filter). It was briefly
     set to `0.65`, which over-filtered (Gemini cosine scores rarely clear 0.65),
     emptied the context, and made the model answer from general knowledge. The
     RAG graph's `assemble` step also previously hard-coded a `max(min_score,
     0.65)` floor; that override was removed so it now respects the configured
     `min_score`.
   - **Still inconsistent:** the agent's `DocumentSearchTool` hard-codes
     `_MIN_SCORE = 0.65` ([document_search_tool.py:22](../src/infrastructure/agent/document_search_tool.py#L22)).
     So the agent path filters at 0.65 while the single-shot RAG path filters at
     the chatbot's `min_score` (0.0). *(Action: make the tool honor the chatbot's
     `RetrievalConfig.min_score` for parity.)*

3. **SSE token spacing (fixed).** The frontend SSE parsers previously called
   `.trim()` on every `data:` line, deleting the spaces/newlines LLM tokens
   carry, so streamed answers rendered as one run-on word. Fixed to strip only
   the single SSE leading space and preserve newlines; bubbles use
   `whitespace-pre-wrap`. Because FastAPI serves the prebuilt `frontend/dist`,
   the bundle must be rebuilt (`npm run build`) for the fix to take effect in a
   bundled deploy.

4. **RLS is dormant by default.** Policies exist but only enforce when the app
   connects as a non-owner DB role. Until then, per-query `tenant_id` filtering
   is the sole active guard. *(Action: provision the `rag_app` role in prod.)*

5. **In-process rate limiters & event bus** are per-process. With multiple
   replicas, limits are per-replica and events don't fan out across processes.
   Fine for a single free-tier instance; revisit (Redis/queue) when scaling
   horizontally.

6. **`rerank` is a placeholder** (`RetrievalConfig.rerank`) — no reranker is
   wired yet; the LangGraph design leaves a clean node seam for it.

7. **Model defaults vs `.env`.** Settings default `generation_primary="groq"`,
   but a local `.env` may set `ollama` (`qwen3:8b`) as primary — a small model
   that follows grounding instructions less reliably. Prefer Groq
   (`llama-3.3-70b`) as primary for production-quality grounding.

---

## 19. Deployment & operations

**Single deployable unit.** The Docker image builds the SPA and runs FastAPI,
which serves the admin app, the `/c/<key>` share page, `/widget.js`, and the API
from **one origin** — what makes generated links/snippets portable.

**Steps (free path):**

1. **DB** — Neon project, enable `vector` extension, set `DATABASE_URL`.
2. **Files** — Cloudflare R2 bucket + token → `R2_*` (omit to use local disk in
   dev).
3. **Keys** — free `GEMINI_API_KEY` and `GROQ_API_KEY`.
4. **Public URL** — `APP_BASE_URL` = deployed HTTPS domain;
   `WIDGET_BASE_URL`/`FRONTEND_BASE_URL` fall back to it (single-origin: set only
   `APP_BASE_URL`).
5. **Host** — `deploy/fly.toml` (`fly launch`) or `deploy/render.yaml`.
   `scripts/start.sh` runs `alembic upgrade head` then launches uvicorn.
6. Optional: a free uptime pinger on `/healthz` reduces cold starts.

**Ops endpoints:** `/healthz` (liveness), `/readyz` (DB connectivity),
`/metrics` (Prometheus).

**Free-tier caveats:** cold-start lag after idle; shared LLM rate limits
(mitigated by per-tenant quotas + provider failover); the in-Python vector search
ceiling (see §18). See [`docs/design/18-scaling.md`](design/18-scaling.md),
[`13-background-workers.md`](design/13-background-workers.md).

---

## 20. Configuration reference

All from environment / `.env` (see `.env.example`). Key variables:

| Variable | Default | Purpose |
|---|---|---|
| `APP_ENV` | `development` | `development` \| `production` (prod enforces strong JWT secret) |
| `APP_BASE_URL` | `http://localhost:8000` | Public origin; basis for links/snippets |
| `JWT_SECRET` | `change-me` | **Must be strong in prod** |
| `JWT_ACCESS_TTL_MINUTES` / `JWT_REFRESH_TTL_DAYS` | 30 / 14 | Token lifetimes |
| `DATABASE_URL` | local asyncpg DSN | Postgres; libpq params auto-stripped, TLS auto for managed hosts |
| `GEMINI_API_KEY` / `GROQ_API_KEY` | — | LLM + embedding keys |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | `gemini-embedding-001` / `768` | Embeddings (schema dim derives from this) |
| `GENERATION_PRIMARY` / `GENERATION_SECONDARY` | `groq` / `gemini` | Failover order (`groq`\|`gemini`\|`ollama`) |
| `GROQ_MODEL` / `GEMINI_MODEL` | `llama-3.3-70b-versatile` / `gemini-2.5-flash` | Generation models |
| `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `http://localhost:11434` / `qwen2.5` | Local generation |
| `R2_*` / `LOCAL_STORAGE_DIR` | — / `/tmp/uploads` | Object storage (R2 or disk fallback) |
| `CORS_ORIGINS` | `["*"]` | Credentialed admin CORS allowlist |
| `WIDGET_BASE_URL` / `FRONTEND_BASE_URL` / `FRONTEND_DIST_DIR` | fall back to `APP_BASE_URL` / repo `dist` | Public widget + SPA origins/path |
| `PUBLIC_ANON_MAX_MESSAGES` / `PUBLIC_ANON_WINDOW_SECONDS` | 20 / 600 | Anonymous widget rate limit |
| `MAX_UPLOAD_MB` | 20 | Upload size cap |
| `TENANT_DAILY_TOKEN_QUOTA` | 200000 | Per-tenant daily token budget |
| `TENANT_MAX_DOCUMENTS` | 200 | Per-tenant document cap |
| `RETRIEVAL_TOP_K` | 5 | Default retrieval breadth |
| `AGENT_MAX_STEPS` | 6 | Hard agent step budget |
| `AGENT_MAX_REQUESTS` / `AGENT_WINDOW_SECONDS` | 30 / 60 | Per-tenant agent rate limit |
| `LANGFUSE_*` / `OTEL_ENABLED` / `OTEL_SERVICE_NAME` | off / false / `rag-platform` | Observability |

---

## 21. Testing

```powershell
pip install -e ".[dev]"
pytest                 # backend
cd frontend; npx tsc --noEmit   # frontend type-check
```

- `tests/domain/` — pure unit tests of entities, the document state machine,
  chatbot/retrieval config, identifiers, errors, events.
- `tests/test_*` — chunker, agent loop, MCP tools, public widget, settings,
  storage key, tracing, eval metrics & regression.
- The eval harness runs offline (no LLM) for CI smoke runs; wire a judge for the
  subjective axes.

---

## 22. Glossary

- **Tenant** — an isolated customer account; the unit all data and quotas key off.
- **Chatbot** — a configured assistant over a subset (or all) of a tenant's docs.
- **Chunk** — a retrievable slice of a document with an embedding.
- **Citation** — a chunk referenced in an answer (doc id, ordinal, score, snippet).
- **Port** — an interface (`Protocol`) the application depends on.
- **Adapter** — a concrete infrastructure implementation of a port.
- **UnitOfWork** — one DB transaction exposing all repositories + event dispatch.
- **ReAct** — reason+act agent loop (think → act → observe → repeat).
- **RLS** — Postgres Row-Level Security (per-tenant policy on `app.tenant_id`).
- **Publishable key (`pk_`)** — non-secret key identifying a public chatbot to the widget.
- **Failover LLM** — router that tries the primary provider then the secondary.
```
