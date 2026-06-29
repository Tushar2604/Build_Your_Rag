# Prompt 18 — Scaling Design

> Scope: the path from a free-tier single-process MVP to **10,000 organizations,
> 100M chunks, 50M messages, 500 concurrent users** — without a rewrite. The whole
> series is built for this: a pooled multi-tenant model
> ([12](12-multi-tenancy.md)), ports/adapters so every datastore and executor is
> swappable, and stateless API + JWT auth that scales horizontally
> ([05](05-authentication.md)). This is the capacity plan those choices enable. No
> code — but every lever maps to an adapter already named elsewhere.

---

## 1. The targets, and what each one stresses

| Target | Primary pressure | Lever |
|---|---|---|
| **10,000 orgs** | tenant isolation at density; metadata cardinality | pooled model + sharding (§3) |
| **100M chunks** | vector search latency/recall; index size | pgvector → Qdrant; partition/shard (§3) |
| **50M messages** | write throughput; table size; history reads | partitioning + archival (§3) |
| **500 concurrent users** | request throughput; LLM rate limits | stateless API autoscale + queue/cache (§1,§4,§5) |

The numbers don't all hit one component — they hit *different* tiers, which is why
each scales independently behind its own seam.

---

## 2. Autoscaling

The MVP is one process doing API + ingestion ([README](../../README.md)). Scaling
starts by **separating the tiers** so each scales on its own signal:

- **Stateless API tier** — FastAPI holds no session state (JWT carries identity,
  [05](05-authentication.md)), so it scales **horizontally** behind a load
  balancer. Autoscale on CPU + **request latency / concurrency** (p95 TTFT is the
  signal users feel, [15 §6](15-observability.md)). 500 concurrent users is a
  handful of replicas; the constraint is downstream (LLM rate limits), not the API.
- **Worker tier** — the Celery fleet ([13](13-background-workers.md)) autoscales
  **per queue on queue depth/lag**: embedding workers scale with ingestion backlog,
  OCR scales to zero between bursts, evals spin up nightly. Decoupling ingestion
  from the API ([13 §1](13-background-workers.md)) is what lets a 1M-doc import not
  touch chat latency.
- **Connection management:** more replicas ≠ more DB connections — a **pooler
  (PgBouncer)** sits in front of Postgres so N stateless replicas don't exhaust
  connection limits. This is the first thing that breaks when you naively scale the
  API.
- **Async all the way** keeps per-replica concurrency high (one process serves many
  in-flight streams), so autoscaling is about redundancy/headroom, not single-
  request throughput.

---

## 3. Sharding

At 100M chunks / 50M messages, single tables and a flat vector scan stop being
viable. Three independent moves, all behind existing ports:

- **Vector store: pgvector → Qdrant.** pgvector carries the MVP into the hundreds of
  thousands of chunks; beyond that, swap the `ChunkRepository` adapter for Qdrant
  with **HNSW** indexing ([04 §8](04-vector-db-design.md), [09 §2a](09-retrieval-engine.md)).
  Isolation maps to **collection/namespace per tenant + mandatory `tenant_id`
  payload filter** ([12 §4](12-multi-tenancy.md)) — no domain change.
- **Relational partitioning & sharding.** Partition the big append-mostly tables
  (`chat_messages`, `document_chunks`, `analytics_events`) by time and/or
  `tenant_id`. At extreme scale, **shard by `tenant_id`** — the pooled model already
  keys everything on it ([12](12-multi-tenancy.md)), so the shard key exists today.
  A tenant→shard directory routes queries; cross-tenant queries never happen by
  design, so sharding stays clean (no cross-shard joins on the hot path).
- **Tenant tiering (silo the whales).** The 10,000-org distribution is long-tailed:
  a few huge tenants, many tiny. Pooled is right for the tail; the largest/most-
  sensitive tenants graduate to **dedicated DB/bucket/Qdrant collection**
  ([12 §1](12-multi-tenancy.md)) — same code, different wiring at the composition
  root.
- **Archival:** cold `chat_messages` / old `doc_version`s move to cheaper storage so
  hot tables stay small and fast.

---

## 4. Rate Limiting

With 10k orgs sharing finite (free or paid) LLM capacity, rate limiting is both a
**cost** and a **fairness** control, not just abuse defense ([17 §4](17-security-review.md)):

- **Per-tenant token quotas** (`daily_token_quota`, shipped,
  [10 §7](10-chat-service.md)) cap generation spend per org — the lever that keeps a
  free tier solvent.
- **Per-tenant + per-IP request limits** at the edge (token-bucket) protect against
  bursts and one tenant starving others.
- **Provider-side limits are the real ceiling:** a fleet-wide concurrency gate per
  provider/key ([13 §3.2](13-background-workers.md)) + key rotation
  ([08 §5](08-embedding-service.md), [11 §5](11-llm-gateway.md)) spreads load across
  pools; failover degrades instead of erroring ([11 §3](11-llm-gateway.md)).
- **Distributed enforcement:** counters move from the single-process
  `usage_counters` table to **Redis** (atomic INCR with TTL) once there are many API
  replicas — keyed `tenant:{id}:…`, never a shared counter
  ([12 §5](12-multi-tenancy.md)).

---

## 5. Queue Scaling

The ingestion/eval/analytics backlog must absorb bursts (a 10k-org onboarding wave)
without dropping work:

- **Broker + per-workload queues** ([13 §2](13-background-workers.md)) with
  **priority lanes** — interactive uploads drain before bulk imports
  ([06 §4](06-ingestion-pipeline.md)), so onboarding a giant tenant never delays a
  small one's single file.
- **Workers autoscale on lag** (§2); the **embedding queue is the bottleneck** and
  is governed by the provider rate gate, so it's the one tuned most carefully.
- **Per-tenant fairness** (weighted consumption / sub-queues,
  [13 §6](13-background-workers.md)) prevents monopolization at 10k-org scale.
- **Backpressure & DLQ:** bounded queues shed/defer under overload; exhausted jobs
  land in the DLQ ([13 §5](13-background-workers.md)) rather than looping — backlog
  is visible (queue depth alert, [15 §8](15-observability.md)), never silent.
- **Postgres-as-queue bridges the gap** (`FOR UPDATE SKIP LOCKED`) until a dedicated
  broker is justified ([13 §7](13-background-workers.md)) — scale the cheap way
  first.

---

## 6. Caching

Caching is the highest-leverage cost/latency win at scale — with one non-negotiable
rule from day one: **every cache key includes `tenant_id`**, or tenant A's answer
leaks to tenant B ([12 §5](12-multi-tenancy.md)).

- **Embedding cache** — identical text → identical vector; cache to skip re-
  embedding on re-ingest and repeated queries ([08 §4](08-embedding-service.md)).
- **Retrieval / answer cache** — cache `(tenant, chatbot, normalized_query)` →
  result for hot repeated questions; invalidate on corpus change (`doc_version`
  flip, [06 §3.7](06-ingestion-pipeline.md)).
- **Prompt caching** at the provider where supported (e.g. Anthropic) cuts repeat-
  context cost ([11 §6](11-llm-gateway.md)).
- **Read-through metadata cache** for hot config (chatbot settings, tenant quotas)
  to spare the DB on every request.
- **Where it lives:** Redis enters here (it's also the broker §5 and the distributed
  rate counter §4) — namespaced `tenant:{id}:…`, evicted by TTL/LRU. The free-tier
  MVP runs *none* of this; it's introduced exactly when the DB/LLM load justifies it
  ([README](../../README.md)).

---

## 7. Capacity sketch (where each number lands)

- **500 concurrent users** → a few autoscaled stateless API replicas behind a
  pooler; the real limit is LLM provider RPM/TPM, handled by rate limits + failover,
  not API CPU.
- **50M messages** → time/tenant-partitioned `chat_messages` + archival; writes are
  append-only and shard-key-clean.
- **100M chunks** → Qdrant (HNSW) per-tenant collections; ANN latency stays flat
  where a pgvector scan would not.
- **10,000 orgs** → pooled by default with the long tail, dedicated silos for the
  few whales; everything already keyed on `tenant_id` so sharding is a routing
  layer, not a remodel.

---

## 8. Why this shape

- **Scale is configuration, not rewrite:** every lever — Qdrant, Celery+broker,
  Redis cache/limits, PgBouncer, tenant silos — is an **adapter swap or a new tier**
  behind a port the MVP already defines. The domain never changes.
- **The shard key already exists:** `tenant_id` on every row and query
  ([12](12-multi-tenancy.md)) means partitioning, sharding, per-tenant caches, and
  per-tenant fairness all fall out of a decision made on day one.
- **Each target scales independently:** API replicas, worker pools, vector store,
  and relational store grow on their own signals — no single bottleneck for all four
  numbers.
- **Free-tier first, paid later:** none of this runs until load demands it
  (Postgres-as-queue, no Redis, pgvector, in-process tasks today) — the architecture
  earns the right to add infrastructure only when the cheap path actually hurts.
