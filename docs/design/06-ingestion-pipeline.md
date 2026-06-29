# Prompt 6 — Document Ingestion Pipeline Design

> Scope: how raw sources become retrievable chunks. The shipped MVP implements a
> resumable `upload → parse → chunk → embed → ready` state machine per document
> ([src/infrastructure/parsing](../../src/infrastructure/parsing),
> [tests/test_document_state_machine.py](../../tests/test_document_state_machine.py)).
> This document generalizes it to many source types (files, websites,
> Confluence, Notion, Google Drive) and to a real background-job system. No code.

---

## 1. The pipeline as a state machine

Every document is a row in `documents` ([03](03-database-design.md)) advancing
through persisted states. **State lives in Postgres, not in memory**, so any step
is resumable after a crash or a free-host sleep — the core property the MVP
already guarantees.

```
discovered → fetching → parsing → cleaning → chunking → enriching → embedding → indexing → ready
                                                                                        ↘ failed
```

Each transition is idempotent and records `status`, `version`, and `error`. A
**startup resume sweep** and a manual `/retry` re-enter the pipeline at the last
incomplete step instead of restarting from scratch.

---

## 2. Sources & connectors

A **connector** abstracts "how do I get bytes + source metadata." All connectors
implement the same port (`list() → fetch(ref) → bytes + metadata`), so the rest
of the pipeline is source-agnostic.

| Source | Connector behavior | Key concerns |
|---|---|---|
| **PDF / DOCX / TXT / MD / HTML (upload)** | presigned upload to object storage (R2/S3); `complete` schedules ingest | virus/size checks, content-type sniffing |
| **Website** | seed URL → crawl within domain/depth, respect `robots.txt`, dedupe by URL+hash | crawl budget, JS-rendered pages, politeness/rate limit |
| **Confluence** | API: list spaces/pages → fetch storage-format HTML + attachments | pagination, permissions, incremental by `version`/`updated` |
| **Notion** | API: list pages/databases → fetch block tree → reconstruct markdown | block-tree → linear text, nested pages, rate limits |
| **Google Drive** | OAuth (Drive scope) → list folder → export Docs/Sheets/Slides + native files | export formats, shared-drive perms, large files |

**Incremental sync:** connectors return a `source_ref` + a change token
(`updated_at`, `version`, ETag). Combined with `documents.checksum`, unchanged
items are **skipped** — so re-syncing a 10k-page Confluence space re-embeds only
what changed. `UNIQUE(kb_id, source_type, source_ref)` enforces one logical doc
per source.

**Connector auth:** Confluence/Notion/Drive credentials are per-org, stored
encrypted, refreshed via OAuth where applicable (Drive reuses the OAuth machinery
from [05](05-authentication.md) but with broader scopes and a stored refresh token).

---

## 3. Stage by stage

### 3.1 Fetching
Pull bytes from the connector into object storage (never process straight from a
third-party API — store first so retries don't re-hit rate limits). Record
`size_bytes`, `content_type`, `checksum` (sha-256). Dedupe on checksum.

### 3.2 Parsing
Dispatch on `source_type` to a parser that yields a **normalized intermediate
representation**: text + structure (headings, lists, tables, page numbers,
images). One IR for everything downstream means the chunker doesn't care whether
the source was a PDF or a Notion page.
- PDF: text-layer extraction; **OCR fallback** for scanned pages (see
  [07 §Image OCR](07-chunking-engine.md)).
- DOCX/Notion/Confluence: structure is explicit — preserve it.
- HTML/Website: strip boilerplate (nav/footer/ads), keep main content + headings.

### 3.3 Cleaning
Normalize whitespace/encoding, drop boilerplate and control chars, fix hyphenation
and broken line-wraps from PDFs, de-duplicate repeated headers/footers, normalize
Unicode. Goal: clean prose/structure so chunk boundaries and embeddings aren't
polluted by layout noise.

### 3.4 Chunking
Hand the IR to the **chunking engine** ([07](07-chunking-engine.md)), which picks
a strategy from the KB's `chunking_config` (recursive, semantic, markdown-aware,
code, table, header-aware). Output: ordered `chunks` rows with `ordinal`,
`content`, `token_count`, and structural `metadata`.

### 3.5 Enriching (metadata extraction)
Attach the metadata that powers filtering + citations:
- structural: `heading_path`, `page`, `is_table`, `section`;
- derived: `lang` (detection), optional title/summary, entities/keywords;
- provenance: `source_type`, `source_ref`, `document_id`, `doc_version`.
This is what gets copied into the Qdrant payload ([04 §3](04-vector-db-design.md)).

### 3.6 Embedding
Batch chunks → embedding model (Gemini `text-embedding-004` in the MVP; pinned by
the KB's `embedding_model`). Batch for throughput, respect provider rate limits
with backpressure, and **checkpoint per batch** so a failure resumes mid-document.

### 3.7 Indexing
Upsert vectors+payload into Qdrant (or write the pgvector column in the MVP),
keyed by the deterministic `vector_point_id`. For re-ingest, write under the new
`doc_version`, then atomically flip the active version and delete old points
([04 §7](04-vector-db-design.md)). Set `documents.status = ready`,
`chunk_count = N`.

---

## 4. Background jobs

**MVP today:** FastAPI `BackgroundTasks` + a resume sweep — zero extra
infrastructure, which is the whole free-tier point. It works because state is in
Postgres and steps are idempotent.

**Scale-up:** move to a real queue (the ports/adapters design makes this an
adapter swap):
- A durable queue (Redis/RQ, Celery, SQS, or Postgres-as-queue via
  `SELECT … FOR UPDATE SKIP LOCKED`).
- **One job per document per stage**, so work parallelizes across workers and a
  single huge document can't starve the pool.
- **Concurrency limits per provider** (embedding API rate caps) and **per org**
  (fairness — one tenant's 1M-doc import can't monopolize workers).
- **Priority lanes**: interactive single-file uploads jump ahead of bulk syncs.

---

## 5. Retries, failure recovery, progress

### 5.1 Retries
- **Per-stage retry with exponential backoff + jitter**; cap attempts.
- **Classify errors:** *transient* (rate limit, network, provider 5xx) → retry;
  *permanent* (corrupt file, unsupported format, parse error) → fail fast, no
  retry. Don't burn 5 retries on a corrupt PDF.
- **Idempotency:** because each stage is keyed on `(document_id, doc_version)` and
  upserts, a retry that partially succeeded last time simply overwrites — no
  duplicate chunks.

### 5.2 Failure recovery
- A failed document is marked `failed` with a human-readable `error`; it does not
  block the batch.
- **Resume sweep** on startup re-queues anything stuck in a non-terminal state
  (the free-host-slept-mid-job case).
- **Dead-letter** for poison documents after max attempts, surfaced for manual
  inspection / `/retry`.
- **Partial-batch tolerance:** in a 10k-doc import, the 12 that fail are isolated
  and reportable; the other 9,988 reach `ready`.

### 5.3 Progress tracking
- Document level: the `status` column + `chunk_count`.
- Job/import level: a parent **ingestion job** row aggregates child documents
  (`total / completed / failed / in_progress`) for a real progress bar.
- Events (`document.parsed`, `document.embedded`, `document.failed`) flow to
  `analytics_events`, and can stream to the UI via SSE — reusing the same SSE
  channel the chat API already uses.

---

## 6. Why this shape

- **Postgres-persisted state machine** = resumability for free, on free hosts,
  and a clean audit trail.
- **One normalized IR** decouples N source types from M chunking strategies — add
  a connector or a chunker without touching the other side.
- **Idempotent, versioned, checkpointed stages** make retries and re-syncs safe
  and cheap, which is what lets the same pipeline handle a single upload *and* a
  1M-document Confluence import (see [04 §10](04-vector-db-design.md)).
- **Ports/adapters** mean the MVP's in-process tasks and the scale-up's job queue
  are the same pipeline with a different executor.
