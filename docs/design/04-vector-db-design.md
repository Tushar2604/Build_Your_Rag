# Prompt 4 — Qdrant Vector Database Design

> Scope: the **vector index for the scale-up tier**. The shipped MVP uses
> Postgres **pgvector** (an HNSW index on `document_chunks.embedding`) precisely
> so it can run free with no extra service. The README states the migration path:
> *"swap in Qdrant via a new `ChunkRepository` adapter — no domain changes."*
> This document designs that Qdrant target. Postgres stays the system of record
> (chunk text + metadata); Qdrant is a **derived, rebuildable index** of vectors
> + a filtered subset of metadata.

---

## 1. Why Qdrant (and when to switch)

pgvector is excellent up to the low millions of vectors, but it shares the OLTP
database's CPU/RAM, can't be scaled independently, and its filtering is bolted
onto SQL planning. Switch to Qdrant when any of these appear:
- vector count pushes past ~1–5M and recall/latency under HNSW degrades,
- you need vector search to scale independently of the transactional DB,
- you need first-class **payload filtering**, **named vectors** (hybrid), and
  **quantization** for memory control.

Because the domain talks to a `ChunkRepository` **port**, the switch is a new
adapter — no use-case or entity changes.

---

## 2. Collections

A **collection** is the unit of vector configuration (distance metric +
dimensionality + index params). The key design question is *collection
granularity*.

**Decision: one collection per embedding contract, NOT one per tenant.**

- A collection's `vector size` and `distance` are fixed at creation, so every
  point in it must come from the **same embedding model**. We therefore key
  collections on the embedding contract, e.g.:
  - `kb_gemini_text-004_768_cosine`
  - `kb_openai_3-large_3072_cosine`
- Tenants/KBs are **not** separate collections. Thousands of collections would
  blow up memory (each carries its own HNSW graph + segments) and make
  cross-tenant ops impossible. Instead, tenancy is enforced by **payload
  filtering** (`org_id`) — see §5.
- Distance metric: **cosine** (matches the MVP's `vector_cosine_ops`), because
  the embedding models are trained for cosine/normalized dot product.

This mirrors the relational decision in [03](03-database-design.md): the KB row
stores which collection it maps to (`knowledge_bases.vector_collection`).

---

## 3. Points, payload & metadata

A **point** = `{ id, vector(s), payload }`.

- **`id`** = the `chunks.vector_point_id` UUID from Postgres. Deterministic
  mapping means we can re-push or delete any chunk by computing its ID — no
  lookup table.
- **`vector`** = the embedding (named vectors for hybrid, §7).
- **`payload`** = the filterable + display metadata copied from Postgres:

```json
{
  "org_id":      "uuid",        // tenant guard — ALWAYS filtered
  "project_id":  "uuid",
  "kb_id":       "uuid",
  "document_id": "uuid",
  "doc_version": 3,             // for atomic re-index swap
  "ordinal":     17,
  "source_type": "confluence",
  "heading_path":["Guide","Setup","Auth"],
  "page":        4,
  "is_table":    false,
  "lang":        "en",
  "acl_groups":  ["eng","all"], // optional doc-level access control
  "created_at":  1719360000
}
```

**Metadata principle:** payload holds only what you **filter or display** on.
The full chunk text stays in Postgres (or is duplicated as a single `text` field
only if you want Qdrant to return snippets directly). Keeping payload lean keeps
RAM down and writes fast.

---

## 4. Namespaces & tenant isolation

Qdrant has no separate "namespace" primitive (unlike Pinecone); the equivalent
is **mandatory payload filtering on a partition key**. Two layers:

1. **Logical namespace = `(org_id, kb_id)` filter.** Every search *must* include
   `must: [{key: org_id, match: <caller's org>}, {key: kb_id, match: <kb>}]`.
   This is injected by the repository adapter, never by the caller — the same
   defense-in-depth posture as the relational RLS layer.
2. **Tenant-isolation index.** Qdrant supports marking a payload field as a
   **tenant key** (`is_tenant: true` on the `org_id` index). This physically
   co-locates each tenant's points within segments, so a filtered search reads
   only that tenant's data instead of scanning the whole HNSW graph. This is the
   single most important performance + isolation setting for multi-tenancy.

**Why filtering, not per-tenant collections (restated):** isolation by filter +
tenant-key index gives you cheap cross-tenant admin, one HNSW graph to maintain,
and bounded memory, while still reading only one tenant's vectors per query.

For **strong** isolation requirements (regulated tenants), the escape hatch is a
**dedicated collection or even a dedicated Qdrant cluster** per such tenant —
recorded in `knowledge_bases.vector_collection`, so it's a per-KB config flag,
not an architecture change.

---

## 5. Filtering

Qdrant applies payload filters **during** HNSW traversal (filterable HNSW), not
as a post-filter, so precision stays high even with selective filters.

Typical query filter:
```
must:
  - org_id = <caller org>          # tenant guard (always)
  - kb_id  = <target kb>           # retrieval scope
  - doc_version = <active version> # exclude superseded chunks
should/must (optional):
  - source_type in [...]           # "search only Notion"
  - acl_groups match-any <user groups>
  - lang = <ui language>
```

**Indexed payload fields:** `org_id` (tenant key), `kb_id`, `document_id`,
`doc_version`, `source_type`, `lang`. Index only what you filter on — each
payload index costs memory.

---

## 6. Hybrid search

Dense vectors miss exact terms (codes, names, IDs); sparse/keyword catches them.
Qdrant supports both natively via **named vectors** in one collection:

- `dense` — the embedding model output (semantic).
- `sparse` — a learned sparse vector (e.g. SPLADE) or BM25-style term weights
  (lexical).

**Fusion:** run both and combine with **Reciprocal Rank Fusion (RRF)** (or
Qdrant's server-side fusion query), then optionally **rerank** the top-k with a
cross-encoder before sending to the LLM. Pipeline:

```
query → [dense search] ⨉ [sparse search] → RRF fuse → top 50 → cross-encoder rerank → top 8 → LLM
```

**Why hybrid + rerank:** dense recall + lexical precision + a reranker that sees
the actual query/chunk pair together is the configuration that most improves
faithfulness in RAG. The MVP does pure dense; this is a clean upgrade because
the chunk text is already in Postgres to feed the reranker.

---

## 7. Versioning

Two distinct kinds of versioning:

1. **Document version (content changes).** When a document is re-ingested,
   `documents.version` increments and new points are written with the new
   `doc_version` in payload. Searches filter `doc_version = active`. Once the new
   version is fully embedded, a single filter flip makes it live; old points are
   deleted by `doc_version` filter. This gives **atomic, zero-downtime re-ingest**.
2. **Embedding-model version (vector space changes).** A new model means a new
   vector space → a **new collection** (you cannot mix spaces in one collection).
   The KB is re-embedded into the new collection; when complete, the KB row's
   `vector_collection` is repointed and the old collection dropped. This is the
   re-index flow in §9.

Collection **snapshots** (Qdrant's built-in snapshot API) provide point-in-time
backups, but Postgres remains the canonical rebuild source.

---

## 8. Re-indexing

Re-index is needed for: embedding-model upgrades, chunking-strategy changes,
distance/HNSW param changes, or corruption recovery.

**Blue-green re-index (no downtime):**
1. Create the new collection (`..._v2`).
2. Stream chunks from **Postgres** (the source of truth), re-embed, upsert into
   `..._v2`. This is a batch job, idempotent on `vector_point_id`.
3. Run an **eval suite** ([03 §3.9](03-database-design.md)) against `..._v2` to
   confirm recall/quality didn't regress.
4. Flip `knowledge_bases.vector_collection` → `..._v2` in one transaction.
5. Drop the old collection after a grace period.

Because Qdrant is *derived*, a re-index never risks data loss — worst case you
rebuild from Postgres again.

---

## 9. Deletion

Three deletion paths, all by filter (no need to know point IDs):

- **Chunk/document delete:** `delete(filter: document_id == X)` in Qdrant, plus
  the cascade delete in Postgres. The two are reconciled by a periodic
  **consistency sweep** (Postgres is authoritative; orphan Qdrant points are
  pruned).
- **Re-ingest cleanup:** delete old `doc_version` points after the new version
  goes live (§7).
- **Tenant offboarding / GDPR erasure:** `delete(filter: org_id == X)` removes
  every vector for a tenant in one call; Postgres rows are purged by the
  offboarding job. The `org_id` payload index makes this fast and complete.

**Soft vs. hard:** vector deletes are hard (there's no audit value in a dangling
vector). Audit/billing retention lives in Postgres, not Qdrant.

---

## 10. Handling 1,000,000 documents

Assume 1M documents × ~40 chunks ≈ **40M vectors**. How the design copes:

**Memory & quantization.** 40M × 768 dims × 4 bytes ≈ 120 GB raw — too much to
keep in RAM uncompressed. Use **scalar (int8) quantization** (≈4× reduction →
~30 GB) with original vectors on disk for a rescoring pass. Optionally
**on-disk HNSW** for the payload/graph. This trades a little recall for an
order-of-magnitude cheaper memory footprint; the rescore step recovers precision.

**Sharding & replication.** Create the collection with multiple **shards**
(e.g. 6–12) so the 40M points and their HNSW graphs distribute across nodes;
add **replicas** for HA and read throughput. Qdrant routes and merges queries
across shards automatically.

**Tenant-key index** (§4) means a single tenant's query reads only that tenant's
segment, so per-query latency depends on *per-tenant* size, not the global 40M.
This is what makes a 40M-vector multi-tenant collection actually usable.

**Ingestion at scale.** Embedding 40M chunks is the real cost: batch the
embedding calls, run the ingestion pipeline ([06](06-ingestion-pipeline.md)) with
backpressure, and **upsert in bulk** (thousands of points per request) with the
HNSW indexing deferred (`indexing_threshold`) until a batch lands, then trigger
index build. Resumable per-document state means a crash mid-load continues, not
restarts.

**Query path at scale.** hybrid retrieve top-50 → cross-encoder rerank top-8.
The reranker bounds how many candidates the LLM sees regardless of corpus size,
keeping prompt size and latency flat as documents grow.

**Cost control.** Quantization + on-disk storage + per-tenant segment locality
means RAM (the dominant Qdrant cost) scales with *hot* working set, not total
corpus. Cold tenants live mostly on disk.

**Summary:** 1M docs is a *sharded, quantized, tenant-key-indexed* Qdrant
collection fed by a resumable bulk-ingestion pipeline, with Postgres as the
rebuildable source of truth and an eval-gated blue-green path for any re-index.
