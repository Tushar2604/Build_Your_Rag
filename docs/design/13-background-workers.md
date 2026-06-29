# Prompt 13 — Background Workers Design

> Scope: the worker fleet that does everything too slow, too bursty, or too
> failure-prone to run inside a request. The MVP runs **zero** of this as a
> separate fleet — ingestion executes in-process via FastAPI `BackgroundTasks`
> over a Postgres-persisted state machine
> ([06-ingestion-pipeline.md](06-ingestion-pipeline.md),
> [src/application/use_cases/ingest_document.py](../../src/application/use_cases/ingest_document.py)),
> which is the whole free-tier point (no always-on worker = no cost). This designs
> the **Celery-based fleet** that same work grows into, behind the existing ports.
> No code.

---

## 1. Why a real worker fleet (and why not yet)

In-process `BackgroundTasks` works *because* state lives in Postgres and every
stage is idempotent ([06 §1](06-ingestion-pipeline.md)): a free host that sleeps
mid-job resumes from the last completed step. Its limits are exactly what a fleet
fixes:

- a long crawl or a 1M-doc import ties up an API process and competes with chat;
- there is no cross-process parallelism, no priority, no backpressure on provider
  rate limits beyond one process;
- a restart loses in-flight work until the resume sweep re-queues it.

**Celery** is the adapter that lifts this work off the API process. The migration
is additive: the use cases (`IngestDocument`, etc.) already encapsulate the work;
a Celery task becomes a thin shell that calls the same use case with the same
tenant-scoped repositories. **Nothing in `domain/` or `application/` changes** —
this is an executor swap, the same promise the ingestion doc makes.

```
API process            broker (Redis/RabbitMQ)        worker fleet
   enqueue(task, args) ───────► [ queues ] ───────►  pick up → run use case
                                  ▲                         │
                                  └──── retry / DLQ ◄────────┘
```

---

## 2. The queues (one per workload class)

Workloads have different latencies, failure modes, and rate limits, so they get
**separate queues** routed to **separate worker pools**. Mixing a 20-minute crawl
with a 200ms re-index in one queue means the crawl head-of-lines everything.

| Worker / queue | Job | Why its own lane |
|---|---|---|
| **parsing** | bytes → normalized IR ([06 §3.2](06-ingestion-pipeline.md)) | CPU-bound; a malformed file shouldn't stall embedding |
| **ocr** | scanned-page / image text extraction | heaviest CPU (or GPU); slow, bursty, isolatable |
| **embedding** | chunk batches → vectors ([08](08-embedding-service.md)) | external rate-limited; needs global concurrency cap |
| **crawl** | website fetch within domain/depth ([06 §2](06-ingestion-pipeline.md)) | long-running, politeness-throttled, network-bound |
| **reindex** | re-chunk/re-embed under a new `doc_version` | bulk, low-priority, runs off-peak |
| **analytics** | roll up `analytics_events` → metrics | periodic, deferrable, idempotent |
| **evals** | golden-set / continuous eval runs ([14](14-evaluation-harness.md)) | scheduled + on-demand; bursty, CPU+LLM |

**Priority lanes within a class:** interactive single-file uploads ride a
`*.interactive` queue that workers drain before `*.bulk`, so one tenant's
million-doc import never delays another tenant's single upload
([06 §4](06-ingestion-pipeline.md), fairness).

---

## 3. The workers, one by one

### 3.1 Parsing
Dispatches on `source_type` to a parser yielding the normalized IR. Pure function
of `(bytes, content_type)` → idempotent and freely retryable. Splits oversized
documents into per-section sub-tasks so a 5,000-page PDF parallelizes instead of
pinning one worker. Permanent errors (corrupt/unsupported) fail fast, no retry.

### 3.2 Embedding
Batches chunks and calls the `Embedder` port. The one worker that must respect an
**external rate limit**: a global concurrency gate (a small semaphore keyed per
provider/key in the broker) caps in-flight embedding calls across the *whole
fleet*, not per worker — otherwise 20 workers blow the free-tier RPM instantly.
Checkpoints per batch (`chunks.embedded` watermark) so a failure resumes
mid-document. Key rotation spreads load across free-tier keys
([08 §5](08-embedding-service.md)).

### 3.3 OCR
Fallback path for scanned PDFs/images ([07](07-chunking-engine.md)). The most
expensive worker per item, so it is **its own pool** sized independently (and the
first candidate for GPU/autoscale-to-zero). Emits an `ocr=true` + confidence flag
onto the chunk so retrieval can down-weight low-confidence OCR text
([09 §5](09-retrieval-engine.md)).

### 3.4 Website crawling
Seed URL → BFS within domain/depth, honoring `robots.txt`, dedupe by URL+content
hash. **Politeness is a rate limit, not a failure**: a per-host token bucket
throttles fetches; the crawl is one long task that enqueues a `parse` job per new
page rather than holding everything in memory. Crawl budget (max pages/time) is
enforced so a pathological site can't run forever.

### 3.5 Re-indexing
Triggered by a chunking/embedding-model change, a config change, or a content
refresh. Re-embeds under a **new `doc_version`**, then atomically flips the active
version and deletes old vectors ([04 §7](04-vector-db-design.md),
[06 §3.7](06-ingestion-pipeline.md)) — readers never see a half-reindexed corpus.
Bulk and low-priority; throttled to spare the embedding rate budget for live
ingestion.

### 3.6 Analytics
Periodic rollups: `analytics_events` → per-tenant usage, retrieval-quality
aggregates, cost summaries ([15](15-observability.md)). Idempotent by design —
keyed on `(tenant, window)` upserts — so a re-run recomputes rather than
double-counts. Deferrable: it runs on a schedule (Celery beat), never blocking
interactive work.

### 3.7 Evaluations
Runs the eval harness ([14](14-evaluation-harness.md)) on a schedule (nightly
regression vs. the golden set) and on-demand (pre-promotion gate for a prompt or
model change). Bursty and mixed CPU+LLM, so it gets a dedicated pool that can be
scaled to zero between runs.

---

## 4. Retries

A single discipline across every worker — the same classification the in-process
pipeline already uses ([06 §5.1](06-ingestion-pipeline.md)), now enforced by
Celery:

- **Exponential backoff + jitter**, capped attempts (`max_retries`,
  `retry_backoff`, `retry_jitter`).
- **Classify the error.** *Transient* (429, network, provider 5xx, timeout) →
  retry; honor `Retry-After`. *Permanent* (corrupt file, unsupported format, 4xx,
  validation) → no retry, straight to `failed`. Never burn five retries on a
  corrupt PDF.
- **Idempotency is the precondition for safe retry.** Every task is keyed on
  `(document_id, doc_version, stage)` and **upserts**, so a retry that partially
  succeeded last time overwrites rather than duplicating — no double chunks, no
  double token spend.
- **Two retry layers, distinct:** transient retry *on the same task* (a blip) vs.
  failover handled inside the adapter (e.g. `FailoverLLM`,
  [11 §3](11-llm-gateway.md)). The worker retries the unit of work; the gateway
  routes around a dead provider.

---

## 5. Dead Letter Queue

When a job exhausts its retries it must not vanish and must not loop forever — it
moves to a **DLQ**.

- **What lands there:** poison jobs (a file that crashes the parser every time),
  exhausted-transient jobs (a provider down for hours), and unclassifiable
  failures.
- **What's recorded:** original task + args, full exception/traceback, attempt
  count, first/last-seen timestamps, and the owning `tenant_id` — a dead job is
  still tenant-scoped and must never leak across tenants when inspected.
- **It's observable:** DLQ depth is a first-class alert ([15 §8](15-observability.md)).
  A rising DLQ means something systemic (a provider outage, a bad deploy), not one
  unlucky file.
- **Recovery:** an operator (or `/retry`) inspects, fixes the root cause, and
  **replays** the job back onto its queue. Replay is safe precisely because tasks
  are idempotent (§4).
- **Quarantine:** the source document is marked `failed` with a human-readable
  `error` and surfaced in the UI — isolated, never blocking the rest of a batch
  ([06 §5.2](06-ingestion-pipeline.md)).

---

## 6. Concurrency, fairness, and rate-limit safety

- **Per-provider global caps** (embedding/LLM RPM/TPM) enforced fleet-wide, not
  per worker — the single most important constraint on a free tier.
- **Per-tenant fairness:** weighted/round-robin consumption (or per-tenant
  sub-queues) so one tenant's bulk import can't monopolize a pool
  ([12 §6](12-multi-tenancy.md)).
- **Tenant context crosses the async boundary:** every task payload carries
  `tenant_id` and re-establishes `set_tenant_scope` when it runs; the rows it
  writes *require* `tenant_id`, so a task that lost its tenant simply can't write
  ([12 §6](12-multi-tenancy.md)).
- **Visibility timeout > longest task** so a slow OCR/crawl job isn't redelivered
  while still running.

---

## 7. Broker & result backend (the free-tier-honest choice)

- **Broker:** Redis (simple, already the cache story) or RabbitMQ (richer routing,
  priority, per-message TTL). For a Postgres-only deployment, the same semantics
  are achievable with `SELECT … FOR UPDATE SKIP LOCKED`
  ([06 §4](06-ingestion-pipeline.md)) — keeping the "one datastore" thesis until
  scale justifies a broker.
- **Result backend:** task *outcomes* belong in Postgres (the `documents` state
  machine, the ingestion-job aggregate, `analytics_events`), **not** the broker —
  results must outlive the broker and be queryable per tenant. Celery's result
  backend is used only for transient task status.
- **Scheduling:** Celery **beat** drives periodic analytics, nightly evals, and
  re-index sweeps. The startup **resume sweep** ([06 §5.2](06-ingestion-pipeline.md))
  survives the migration — it re-queues anything stuck in a non-terminal state.

---

## 8. Why this shape

- **Executor swap, not a rewrite:** the work already lives in use cases over
  ports; a Celery task is a thin shell calling the same `IngestDocument`. The MVP's
  in-process tasks and the fleet are the same pipeline with a different runner
  ([06 §6](06-ingestion-pipeline.md)).
- **Queues per workload** isolate failure and latency: a 20-minute crawl, a
  rate-limited embed batch, and a 200ms re-index never share a lane.
- **Idempotent + versioned + checkpointed** is what makes retries, the DLQ, and
  replay *safe* — every guarantee here rests on that property.
- **Free-tier honest:** none of this runs until scale demands it; Postgres-as-queue
  bridges the gap, and the broker/worker fleet slots in behind the same seams when
  the in-process model finally hurts ([18 §5](18-scaling.md)).
