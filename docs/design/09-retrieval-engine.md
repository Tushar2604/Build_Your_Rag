# Prompt 9 — Retrieval Engine Design

> Scope: how a question becomes a small, ordered, high-precision set of
> `Citation`s for generation. The MVP ships the first stage only — single-vector
> pgvector cosine search with a tenant filter and a `min_score` floor
> (`ChunkRepository.search`,
> [src/infrastructure/persistence/repositories.py](../../src/infrastructure/persistence/repositories.py)),
> wired as the `retrieve` node of the LangGraph pipeline
> ([src/infrastructure/rag/graph.py](../../src/infrastructure/rag/graph.py)). This
> designs the **full multi-stage engine** those nodes can grow into. No code.

---

## 1. The principle: recall-first then precision-first

Retrieval is a funnel. Early stages are **cheap and high-recall** (cast wide over a
large K); later stages are **expensive and high-precision** (refine a small N).
Each stage shrinks the candidate set so the costly models only ever touch a
handful of items.

```
question
   │
   ▼
[1] query processing ── embed_query (Embedder, input_type=query) [08]
   │
   ├──────────────┬───────────────┐
   ▼              ▼               (parallel)
[2a] vector    [2b] BM25
  (pgvector)    (lexical)
   └──────┬───────┘
          ▼
[3] hybrid fusion (RRF)
          ▼
[4] metadata filtering  ── tenant_id (mandatory), document_ids, section, date
          ▼
[5] rerank (cross-encoder)         top-K (≈100) → top-N
          ▼
[6] MMR (diversity)
          ▼
[7] context compression
          ▼
   Citation[] → assemble → generate  ([10] chat service)
```

The MVP collapses this to `[1] → [2a] → (min_score cutoff) → assemble`. Each box
below is an insertable node — the graph's docstring explicitly anticipates
"rerank, guardrail, query-rewrite" nodes dropping in without rewriting the flow.

---

## 2. Stage 1 — Query processing

Before any search: normalize the text, then embed it **as a query**. The MVP
already does the critical part — `embed_query` uses Gemini's `retrieval_query`
task type, distinct from the `retrieval_document` path used at ingest
([08 §1](08-embedding-service.md)). Optional recall boosters that slot in here:

- **Query rewriting / contextualization** — resolve conversational follow-ups into
  standalone queries. This belongs to the chat service and is detailed in
  [10 §4](10-chat-service.md); the retriever only ever sees a self-contained query.
- **HyDE** — generate a hypothetical answer and embed *that* for the dense search.
- **Multi-query** — generate N paraphrases, union their results — helps
  under-specified questions.

These trade extra LLM/embedding calls for recall, so they're config-gated per
chatbot (`chatbots.retrieval`, [03](03-database-design.md)).

---

## 3. Stages 2a/2b — Dense + sparse, in parallel

### 2a. Vector (dense) search — *shipped*
ANN over chunk embeddings. The MVP computes **pgvector cosine distance inside
Postgres**, orders ascending, takes `top_k`, and converts to a similarity
(`1 - distance`) with a `min_score` floor. Captures **semantic** similarity — finds
chunks that *mean* the same thing with no shared words. Weakness: misses exact
terms — IDs, error codes, proper nouns, rare tokens. At scale the flat scan is
swapped for an HNSW/IVF index ([04](04-vector-db-design.md)) behind the same
`ChunkRepository.search` port — no caller change.

### 2b. BM25 (sparse / lexical) search
Classic TF-IDF term ranking. Captures **exact lexical** matches precisely where
dense retrieval is weak. Two ways to source it without a new datastore:
- **Postgres full-text search** (`tsvector`/`ts_rank`) over the existing
  `document_chunks.text` — keeps the "one datastore" free-tier thesis intact.
- **`bge-m3` sparse vectors** emitted by the embedding service at ingest
  ([08 §2](08-embedding-service.md)).

Run dense and sparse **in parallel** over the same tenant-scoped corpus.

---

## 4. Stage 3 — Hybrid fusion

Dense and sparse scores live on incomparable scales, so fuse by **rank**, not raw
score:

- **Reciprocal Rank Fusion (RRF)** — `score = Σ 1/(k + rank_i)` across lists.
  Scale-free, no per-list weight tuning, robust default.
- **Weighted score fusion** — normalize each list then blend; needs calibration,
  use only when you want a tunable dense/sparse bias per chatbot.

Hybrid consistently beats either alone: dense covers semantics, sparse covers
exactness, fusion gets both. This is the recall backbone — everything downstream
only *removes* candidates, so misses here can't be recovered later.

---

## 5. Stage 4 — Metadata filtering

Apply hard constraints. **`tenant_id` is mandatory and non-negotiable** — it is a
**pre-filter** pushed into the query (the MVP's `search` already `WHERE
tenant_id = :tid`, backed by RLS, [12](12-multi-tenancy.md)), never a
filter-after-retrieve. Same for `document_ids` (the chatbot's `document_filter()`,
already wired).

- **Pre-filter** (filter → search) for selective/security-critical predicates:
  tenant, document allow-list, permissions. Correctness depends on it.
- **Post-filter** only for loose, non-security predicates where pre-filtering would
  hurt ANN quality.
- Extensible metadata: section/`heading_path` ([07 §3.7](07-chunking-engine.md)),
  date ranges, source type, language, `ocr=true` confidence flags — stored on the
  chunk and pushed into the filtered search.

---

## 6. Stage 5 — Reranking

Take the fused, filtered top-K (say ~100) and rerank with a **cross-encoder**
(Cohere/Voyage/Jina rerank, or `bge-reranker`). A cross-encoder reads
`(query, chunk)` *together*, modeling fine-grained relevance far better than the
bi-encoder embeddings used for the first-pass search. It's expensive per pair, so
it only runs on the already-narrowed set, emitting a clean top-N (≈5–20).

**This is the single biggest precision gain in the pipeline** and the highest-value
node to add after the MVP. It sits behind a new `Reranker` port (sibling to
`Embedder`), so the free tier can skip it and a paid tier can enable it per chatbot
with no pipeline rewrite — exactly the seam the graph was built for.

---

## 7. Stage 6 — MMR (Maximal Marginal Relevance)

The reranked set is often **redundant** — five near-duplicate chunks repeating one
fact waste the prompt budget the chat service must respect
([10 §3](10-chat-service.md)). MMR re-selects to balance **relevance to the query**
against **diversity from already-chosen chunks**:

```
MMR = λ · relevance(chunk, query) − (1 − λ) · max_sim(chunk, already_selected)
```

Result: coverage of multiple facets of the answer instead of one fact echoed.
`λ` (config per chatbot) tunes the relevance↔diversity trade-off. Cheap — it reuses
the embeddings/scores already in hand.

---

## 8. Stage 7 — Context compression

Even the final N chunks carry irrelevant sentences that cost tokens and dilute the
answer. Compression produces the tight context block the generator consumes:

- **Extractive** — keep only sentences scoring high against the query
  (sentence-level rerank / LLMLingua-style pruning). Cheap, lossless-ish.
- **Abstractive** — an LLM summarizes each chunk *conditioned on the query*. Higher
  quality, costs a generation call (route through the gateway, [11](11-llm-gateway.md)).
- **Threshold pruning** — drop chunks below a relevance floor entirely. The MVP's
  `min_score` cutoff is the primitive version of this; if *nothing* clears the bar,
  the context is `"(no relevant context found)"` and the generator is instructed to
  refuse rather than hallucinate ([10 §6](10-chat-service.md)).

Output preserves each chunk's `document_id` / `ordinal` / score so the assemble
node can build `Citation`s — the contract `RagGraph` and `AskChatbot` already
depend on.

---

## 9. The assemble/generate handoff (already shipped)

The final ordered chunks become `Citation`s, formatted by `build_context` into
`[Source N | doc=… | score=…]` blocks. The non-streaming path runs
`retrieve → assemble → generate` in the graph; the streaming path calls
`retrieve_only`, sends citations up front over SSE, then streams generation
([10](10-chat-service.md)). Every stage above plugs in **before** this handoff, so
the contract downstream never changes.

---

## 10. Why a multi-stage funnel beats one search

- **No single retriever is sufficient:** dense misses exact terms, sparse misses
  paraphrase, neither dedups or compresses. Each stage fixes the previous stage's
  blind spot.
- **Cost where it pays:** wide cheap recall up front; expensive cross-encoder and
  LLM compression only on a tiny candidate set.
- **Precision protects the LLM:** garbage context produces confident wrong answers,
  so rerank + MMR + compression are the real defense behind the hallucination
  guardrails in [10 §6](10-chat-service.md).
- **It grows behind fixed seams:** `ChunkRepository.search`, a future `Reranker`
  port, and the graph's insertable nodes mean the MVP's single-vector search
  becomes a full hybrid+rerank pipeline without touching the domain or the API.
