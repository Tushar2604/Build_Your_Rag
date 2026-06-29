# Prompt 12 — Multi-Tenancy & Tenant Isolation Design

> Scope: how the platform guarantees that **Company A can never read, write, or
> infer the existence of Company B's data** — across the database, vectors,
> caching/usage counters, auth, and background work. This is mostly **shipped**:
> `tenant_id` on every table and query, RLS-ready policies bound per transaction
> (`set_tenant_scope` →`app.tenant_id`,
> [src/infrastructure/persistence/unit_of_work.py](../../src/infrastructure/persistence/unit_of_work.py)),
> JWT/API-key auth ([05-authentication.md](05-authentication.md)), and in-process
> resumable ingestion ([06-ingestion-pipeline.md](06-ingestion-pipeline.md)). This
> documents the isolation model end to end. No code.

---

## 1. The invariant and the strategy

**Invariant:** no request authenticated for tenant A can ever touch tenant B's
data — and a single forgotten filter must not be catastrophic.

**Strategy: defense in depth.** Isolation is enforced **independently at multiple
layers**, so any one failing is contained by the next:

```
AuthN  → tenant_id is a signed token claim, not client input        ([05])
AuthZ  → set_tenant_scope binds app.tenant_id for the transaction
DB     → every query filters tenant_id  +  Postgres RLS backstop
Vector → pgvector search is tenant-filtered (same table, same rule)
Usage  → usage_counters keyed by tenant_id (no shared Redis to leak)
Workers→ tenant_id carried across the async boundary
```

This is a **pooled** model (shared Postgres, row-level `tenant_id`) — the densest,
cheapest option, which is why it fits the free-tier thesis. The ports/adapters
design leaves room to **silo** the largest/most-sensitive tenants (separate
DB/bucket) later without touching the domain.

---

## 2. Authentication & authorization

- **AuthN** ([05](05-authentication.md)): every request carries a verified
  identity — a JWT whose claims include `tenant_id`, or a hashed per-tenant API
  key. The tenant is fixed **at token issuance** (`TokenService.issue(user_id,
  tenant_id, role)`) and signed; the client cannot edit it.
- **AuthZ:** API dependencies resolve a `Principal` (tenant_id + role) from the
  token *before* any handler runs, and pass `principal.tenant_id` into every use
  case. Handlers cannot construct a query without it — the repository method
  signatures *require* `tenant_id`.
- **Public chatbots** are the one deliberate cross-auth path
  (`get_public`), and they're still tenant-scoped by the chatbot's own `tenant_id`
  on the data it can reach.

---

## 3. Database (Postgres) — *shipped*

- **Every tenant-scoped table carries an indexed `tenant_id`** (`users`,
  `documents`, `document_chunks`, `chatbots`, `chat_sessions`, `chat_messages`,
  `usage_counters`, `audit_events` —
  [models.py](../../src/infrastructure/persistence/models.py)).
- **Primary guard:** every repository query filters `tenant_id` explicitly
  (`get`, `list_for_tenant`, `search`, … all take it) — see
  [repositories.py](../../src/infrastructure/persistence/repositories.py). FKs never
  cross tenants.
- **Backstop — Row-Level Security:** the Unit of Work binds
  `set_config('app.tenant_id', …, true)` (transaction-local) on enter and commit, so
  RLS policies filter every query by the session's tenant **even if a query forgets
  its `WHERE`**. Policies ship in the initial migration.
- **Activation caveat** (from the README): RLS is **dormant while the app connects
  as the table owner** (owners bypass RLS). To enforce it, connect as a dedicated
  non-owner role (`rag_app`). Until then, the explicit per-query filter is the
  active guard — which is why both layers exist.
- **Connection-pool hygiene:** because the scope is **transaction-local**
  (`set_config(..., true)`), it auto-clears on commit/rollback, so a pooled
  connection can't leak tenant A's scope into tenant B's next transaction.

---

## 4. Vector DB

There is **no separate vector service** — vectors are rows in `document_chunks`
with a pgvector `embedding` column, searched inside Postgres
([04-vector-db-design.md](04-vector-db-design.md)). That's a deliberate isolation
win: **the vector store inherits the exact same tenancy guarantees as the
relational data** — no second system with its own (easily-forgotten) access model.

- `ChunkRepository.search` is **tenant-pre-filtered**: `WHERE tenant_id = :tid`
  *and then* ANN by cosine distance — never "search globally, filter after." Semantic
  search is the classic silent leak path, and pre-filtering closes it.
- The optional `document_ids` filter (a chatbot's allow-list) narrows further, still
  inside the tenant scope.
- **Growth:** if pgvector is swapped for Qdrant at scale, isolation maps to
  **namespace/collection per tenant** *plus* a mandatory `tenant_id` payload filter —
  belt and suspenders — behind the same `ChunkRepository` port, no domain change
  ([04 §8](04-vector-db-design.md)).

---

## 5. Redis / caching — replaced, not just isolated

The platform runs **no Redis** at free-tier scale; the roles Redis usually plays are
covered by tenant-keyed Postgres, which removes a whole class of cross-tenant cache
bugs:

- **Rate/usage counters:** `usage_counters` is keyed by `(tenant_id, day)` with an
  atomic upsert (`tokens_used = tokens_used + n`) — per-tenant by construction, no
  shared counter to leak or collide.
- **The cache-key trap (called out for when caching *is* added):** any future cache
  — embedding cache ([08 §4](08-embedding-service.md)), query cache, Redis adapter —
  **must include `tenant_id` in the key.** A cache keyed on query text alone would
  serve tenant A's answer to tenant B. This is the single most dangerous
  multi-tenant caching bug, so it's a design rule, not an afterthought.
- **When Redis returns:** namespace every key `tenant:{id}:…` (or a logical DB /
  dedicated instance per high-isolation tenant); flushing one tenant must never
  touch another.

---

## 6. Workers / background jobs

Ingestion runs in-process via FastAPI `BackgroundTasks` (no Celery/worker fleet at
free-tier scale, [06](06-ingestion-pipeline.md)). Isolation rules:

- **Tenant context must survive the async boundary:** every job carries its
  `tenant_id` in its payload and re-establishes scope (`set_tenant_scope`) when it
  runs — the chunk rows it writes already require `tenant_id`, so a job that lost its
  tenant simply can't write.
- **Resume sweep safety:** the startup `list_resumable` sweep operates across
  tenants by design (it's an operator/system action), but each resumed step writes
  back through tenant-scoped repositories, so recovered work stays in its own tenant.
- **Fairness (QoS, not just security):** a noisy tenant shouldn't starve others. The
  `daily_token_quota` per tenant ([10 §7](10-chat-service.md)) bounds generation
  load; if a real worker fleet is added later, per-tenant queues/partitioning extend
  this.

---

## 7. Everything else (cross-cutting)

- **Object storage** ([06](06-ingestion-pipeline.md)): uploads are stored under
  **tenant-prefixed keys** (`storage_key`), and presigned URLs are scoped + size-
  capped, so one tenant's URL can't address another's bytes.
- **Embedding & LLM gateways** ([08](08-embedding-service.md),
  [11](11-llm-gateway.md)): cost and rate limits are metered per tenant; any prompt/
  embedding cache key includes `tenant_id` (§5).
- **Observability** ([structlog](../../src/infrastructure/observability/logging.py)
  + `audit_events`): logs/metrics/traces are tagged with `tenant_id` for
  attribution — but never log another tenant's *content* across streams; audit rows
  themselves carry `tenant_id`.
- **Continuous verification:** automated cross-tenant tests belong in CI — "tenant A's
  token requesting tenant B's resource must 404/403." Isolation that isn't tested
  rots; these tests are the guard that the layers above stay wired.

---

## 8. Why this shape

- **Multiple independent layers:** signed tenant claim → required-argument repository
  filters → RLS backstop → tenant-filtered vector search → tenant-keyed counters.
  Defense in depth means one mistake is contained, not catastrophic.
- **Fewer systems, fewer leaks:** folding vectors into Postgres and replacing Redis
  with a tenant-keyed table eliminates entire categories of cross-tenant bugs that
  separate datastores invite.
- **Isolation is structural:** `tenant_id` is a *required parameter*, not a
  convention — the type signatures make the unsafe call hard to write.
- **Grows without weakening:** pooled now; per-tenant silos, Qdrant namespaces, and a
  worker fleet all slot in behind existing ports while preserving the same invariant.
