# Prompt 8 — Embedding Service Design

> Scope: how the chunks produced by the
> [07-chunking-engine.md](07-chunking-engine.md) are turned into vectors for the
> pgvector store ([04-vector-db-design.md](04-vector-db-design.md)). The MVP ships
> a single adapter — `GeminiEmbedder` (`text-embedding-004`, 768-dim, free tier,
> [src/infrastructure/llm/embeddings.py](../../src/infrastructure/llm/embeddings.py)) —
> behind the `Embedder` port
> ([src/application/ports/services.py](../../src/application/ports/services.py)).
> This designs the **full embedding service** the port can grow into:
> multi-provider, batched, cached, rate-limited, versioned. No code.

---

## 1. The port is the whole contract

Everything below lives behind one tiny Protocol the core already depends on:

```
Embedder
  dim: int
  embed_documents(texts) -> list[vector]   # ingestion, task_type=retrieval_document
  embed_query(text)       -> vector         # retrieval,  task_type=retrieval_query
```

Two facts in that signature drive the entire design:

1. **Documents and queries are embedded differently.** Gemini takes a
   `task_type` (`retrieval_document` vs `retrieval_query`); Voyage/BGE/Jina take an
   `input_type`/instruction prefix. The service must thread intent through — using
   the document path for queries silently degrades recall. The port already
   separates the two methods, so this is enforced by shape, not discipline.
2. **`dim` is a property of the adapter, not a constant.** The pgvector column is
   `Vector(EMBEDDING_DIM)` fixed at migration time
   ([models.py](../../src/infrastructure/persistence/models.py)). Changing the
   embedder's dimension is a schema + re-index event (§7), never a hot swap.

The rest of the service is internal to the adapter(s) behind this port — the
domain, use cases, and `RagGraph` never see batching, caches, or providers.

---

## 2. Provider abstraction

Each provider becomes an `Embedder` adapter that normalizes three things:
**input shaping** (task-type/prefix), **output shape** (dimension, normalization),
and **error semantics** (what counts as retryable, §5).

| Provider | MVP role | Example model | Native dim | Notes |
|---|---|---|---|---|
| **Gemini** | **shipped default** (free) | `text-embedding-004` | 768 | `task_type` per call; free tier → ingestion costs nothing |
| **OpenAI** | drop-in adapter | `text-embedding-3-small/large` | 1536 / 3072 | Matryoshka `dimensions` truncation (§6) |
| **Voyage** | quality upgrade | `voyage-3`, `voyage-code` | 1024 | input-type aware; strong retrieval & domain models |
| **BGE** | self-host | `bge-m3`, `bge-large` | 1024 | open weights; `bge-m3` yields dense+sparse (feeds hybrid, [09](09-retrieval-engine.md)) |
| **Jina** | self-host / API | `jina-embeddings-v3` | 1024 | long context, task LoRA adapters |

**Why ports/adapters here pays off:** the README's free-tier thesis is "start on
Gemini, grow into paid infra without a rewrite." A new provider is a new class
implementing three methods + a config switch — no change to ingestion, retrieval,
or the domain. Selection is config-driven (an `embedding_provider` setting beside
the existing `embedding_model` / `embedding_dim` in
[settings.py](../../src/config/settings.py)).

**Asymmetric/sparse note:** `bge-m3` can emit a sparse vector alongside the dense
one. That sparse output is exactly the lexical signal the retrieval engine's BM25
stage wants ([09 §3](09-retrieval-engine.md)) — so the embedding service is the
natural producer of both, stamped onto the chunk at ingest.

---

## 3. Batching

Embedding is throughput-bound for ingestion and latency-bound for queries, so the
service runs **two paths behind the same port**:

```
embed_documents(texts)            embed_query(text)
        │                                 │
        ▼                                 ▼
  bulk accumulator                  low-latency path
  key = (provider, model,           tiny/no batch, fast flush
         input_type)                (single query, returned immediately)
  flush on EARLIEST of:
    • size cap   (provider max items/request)
    • token cap  (provider max tokens/request)
    • time window (e.g. 50–100ms)
```

- The **bulk path** fills each request to the provider's hard caps (items/request,
  tokens/request) — the chunker hands over a whole document's chunks, so batching
  is natural and high-yield.
- The **query path** never waits for a batch; interactive latency wins.
- For **self-hosted BGE/Jina**, batching fills the GPU: dynamic batching with
  length-bucketed padding maximizes throughput.
- *MVP reality:* `GeminiEmbedder.embed_documents` currently loops one-by-one. The
  first upgrade behind this port is request-level batching where the provider
  supports it — no caller changes, since the method signature is already
  list-in / list-out.

---

## 4. Caching

An embedding is a **pure function** of `(provider, model, model_version,
input_type, normalized_text)` — perfectly cacheable.

- **Cache key** = hash of that tuple. Normalize text first (trim, Unicode NFC) so
  trivial differences still hit.
- **Two tiers:**
  - *Query cache* (hot, short TTL) — repeated user questions are extremely common;
    biggest live win. At free-tier scale this is the **Postgres `usage_counters`
    philosophy** ([12](12-multi-tenancy.md)): a small table/keyed store, no Redis
    required. A Redis adapter drops in later behind the same cache port.
  - *Document cache* (durable) — the corpus is already persisted as chunk rows;
    re-ingestion of an unchanged document (same checksum,
    [06](06-ingestion-pipeline.md)) must never re-pay for embeddings.
- **Versioned keys (critical):** `model_version` is part of the key. A vector from
  an old model must never be served into an index built by a new one (§7).
- **Tenant-safe:** embeddings of identical text are tenant-independent and *may* be
  shared in cache, but the cache key must never let one tenant's lookup return
  another tenant's *stored* vector rows — caching is on the text→vector function,
  not on tenant-scoped query results ([12](12-multi-tenancy.md)).

---

## 5. Rate limits

Free tiers (Gemini today; Groq for generation in [11](11-llm-gateway.md))
rate-limit aggressively, so the service self-limits *before* hitting the provider:

- **Client-side limiter** per `(provider, api_key)`: a token-bucket for RPM and a
  separate budget for TPM (estimate tokens before sending; the codebase already
  uses a `len//4` estimate).
- **Bounded concurrency** pool per provider; excess work queues rather than
  firehoses.
- **Adaptive throttle:** on `429`, read `Retry-After`, back off, and *temporarily
  lower the local rate* (AIMD) to find the real ceiling instead of hammering it.
- **Multiple keys:** rotate/shard across keys, tracking limits per key — mirrors
  the multi-pool approach the generation gateway uses for failover.

This protects the same shared free-tier limits the per-tenant `daily_token_quota`
guard protects on the generation side ([12](12-multi-tenancy.md)).

---

## 6. Retries

The MVP already wraps `_embed_one` with `tenacity`
(`stop_after_attempt(4)`, `wait_exponential(min=1, max=20)`). Generalized:

- **Retry only transient failures:** `429`, `5xx`, timeouts, connection resets.
  **Never** retry `400` (bad input) or `401/403` (auth) — those are bugs, not blips.
- **Exponential backoff with full jitter**, capped attempts and a capped total
  deadline so ingestion doesn't stall forever.
- **Idempotent by construction:** embeddings are deterministic, so retries are
  always safe. On a partial batch failure, retry only the failed sub-items, not the
  whole batch.
- **Dead-letter:** items that exhaust retries park on the document as a failed
  step. Because ingestion is a resumable state machine
  ([06](06-ingestion-pipeline.md)), a later `/retry` resumes from `embedding`
  rather than re-parsing — no work is silently lost.

---

## 7. Versioning — the hard operational problem

**A vector is only comparable to vectors from the same provider + model + version
+ dimension + normalization.** Mixing generations inside one index silently
corrupts similarity.

- **Stamp provenance** on every stored chunk: `embedding_provider`,
  `embedding_model`, `model_version`, `dim`. (Extends the chunk metadata in
  [03](03-database-design.md)/[04](04-vector-db-design.md).)
- **An index is pinned to one embedding config.** The pgvector column dimension is
  fixed at migration time, so changing model/dimension is a **new index**, not a
  mutation.
- **Migration = re-embed → backfill → atomic swap (blue/green).** Build the new
  index alongside the old, validate recall, then cut queries over and retire the
  old. Queries route to the index matching their embedding version.
- This is the same **re-index discipline** the chunking engine calls out
  ([07 §4](07-chunking-engine.md)): anything that changes chunk *boundaries* or
  chunk *vectors* invalidates the index and must be rebuilt, never patched in place.

---

## 8. Cost optimization

- **Cache first** — the cheapest embedding is the one never computed (§4).
- **Right-size the model:** `-small`/`-lite` tiers where recall is adequate;
  reserve large models for hard corpora.
- **Dimension truncation** (Matryoshka; OpenAI/Gemini) cuts both API cost and
  pgvector storage/index size when quality permits — but it changes `dim`, so it's
  a §7 re-index decision, not a runtime toggle.
- **Dedup before embedding:** identical/near-identical chunks (boilerplate,
  repeated headers/footers from [06](06-ingestion-pipeline.md)) embed once.
- **Self-host BGE/Jina** past the volume where GPU amortization beats per-token
  pricing — the README's documented growth path off the free tier.
- **Attribute cost per tenant** for the same visibility the generation gateway
  provides ([11 §6](11-llm-gateway.md)).

---

## 9. Why this shape

- **One small port, swappable everything:** providers, batching, caching, and
  limits all live behind `Embedder` — the core (`RagGraph`, `AskChatbot`,
  ingestion) is untouched by any of it.
- **Determinism is leverage:** because embeddings are pure functions, caching is
  trivially correct and retries are trivially safe — the design leans on that
  rather than fighting it.
- **Free-tier now, paid later, no rewrite:** Gemini today; OpenAI/Voyage/self-host
  BGE are config + a new adapter — exactly the architecture promise in the README.
- **Versioning is treated as a first-class index event**, consistent with chunking
  and the vector DB design, so embedding upgrades never silently rot retrieval.
