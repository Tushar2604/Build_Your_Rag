# Prompt 7 — Intelligent Chunking Engine Design

> Scope: how the normalized document IR from
> [06-ingestion-pipeline.md](06-ingestion-pipeline.md) is split into retrieval
> units. The MVP ships a single recursive chunker
> ([tests/test_chunker.py](../../tests/test_chunker.py)); this designs a
> **strategy-based engine** that selects the right splitter per content type,
> configured per knowledge base (`knowledge_bases.chunking_config`). No code.

---

## 1. Why chunking decides RAG quality

The chunk is the atomic unit of retrieval, embedding, and citation. Get it wrong
and everything downstream suffers:
- **Too large** → the embedding averages multiple topics, similarity blurs,
  irrelevant text pads the prompt, citations are imprecise.
- **Too small** → context is severed, a chunk lacks the surrounding meaning
  needed to answer.
- **Boundaries in the wrong place** (mid-sentence, mid-table, mid-function) →
  semantically broken units.

So the engine's job is to produce units that are **semantically self-contained,
embedding-sized, and structurally aligned** to the content. No single algorithm
does this for every content type — hence a **router**.

---

## 2. Engine architecture: a router over strategies

```
IR (text + structure + content-type hints)
        │
        ▼
  ┌───────────────┐   picks strategy from kb.chunking_config + content signals
  │   Router      │────────────────────────────────────────────────┐
  └───────────────┘                                                 │
        │                                                           ▼
        ├── markdown? ──────▶ Markdown / Header-aware chunker
        ├── code block? ───▶ Code chunker
        ├── table? ────────▶ Table chunker
        ├── scanned image? ▶ OCR → re-enter router
        ├── prose? ────────▶ Semantic chunker (fallback: Recursive)
        └── (default) ─────▶ Recursive chunker
        │
        ▼
  Post-processing: overlap, token-bound enforcement, metadata stamping
        │
        ▼
  chunks[] → embedding stage
```

**Shared post-processing for every strategy:**
- **Token-bound enforcement** — every emitted chunk is forced under the model's
  target window (e.g. 256–512 tokens) regardless of strategy.
- **Overlap** — a sliding overlap (e.g. 10–15%) between adjacent chunks preserves
  cross-boundary context for prose strategies.
- **Header-path prefixing** — each chunk carries its heading trail so it reads as
  self-contained (see §3.7).
- **Metadata stamping** — `ordinal`, `heading_path`, `page`, `is_table`,
  `chunk_strategy`, `token_count` (consumed by [03](03-database-design.md) and
  [04](04-vector-db-design.md)).

---

## 3. The strategies

### 3.1 Recursive (character/separator) chunking
**How:** split on a priority list of separators — paragraphs (`\n\n`) → lines →
sentences → words — recursively descending only when a piece still exceeds the
size budget. Add overlap.
**Strength:** robust, fast, structure-agnostic; never produces oversized chunks.
**Weakness:** boundaries are size-driven, not meaning-driven — can split related
sentences.
**Use when:** the default/fallback for arbitrary prose, or when content has no
reliable structure and you want predictable, cheap chunking. *This is the MVP's
current single strategy and the engine's safety net.*

### 3.2 Semantic chunking
**How:** embed sentences (or small windows), then place a boundary where the
**embedding similarity between adjacent windows drops** below a threshold —
i.e. split where the topic actually shifts.
**Strength:** boundaries align to meaning; chunks are topically coherent → best
retrieval precision for flowing prose.
**Weakness:** costs extra embedding calls at ingest time; threshold needs tuning;
overkill for already-structured docs.
**Use when:** long-form unstructured prose where topics drift within sections
(articles, reports, transcripts) and retrieval quality justifies the extra
ingest cost.

### 3.3 Markdown chunking
**How:** parse the markdown tree and split along its native structure — headings,
lists, code fences, blockquotes — keeping each element intact.
**Strength:** respects authored structure; doesn't shatter lists or code fences.
**Weakness:** only as good as the markdown's structure.
**Use when:** markdown sources — and, via the IR, Notion/Confluence content that
was normalized to markdown in [06](06-ingestion-pipeline.md). Pairs with
header-aware enrichment (§3.7).

### 3.4 Code chunking
**How:** split along **syntactic units** (functions, classes, methods) using a
language-aware parser (e.g. tree-sitter), not blank lines. Keep signatures with
bodies; keep imports/context available.
**Strength:** each chunk is a complete, runnable-meaning unit; preserves
indentation and scope.
**Weakness:** language-specific; very long functions still need a sub-split (fall
back to recursive *within* the function, preserving the signature as a header).
**Use when:** source code, code-heavy docs, API references — anywhere a mid-function
split would destroy meaning.

### 3.5 Table chunking
**How:** keep a table as its own unit; for large tables, split by **row groups**
while **repeating the header row** in each piece so every chunk is self-describing.
Optionally serialize each row as `header: value` pairs, or attach a short
natural-language summary of the table for better embedding.
**Strength:** preserves tabular semantics; each chunk knows its column meaning.
**Weakness:** tables embed poorly as raw text; the row-as-sentence/summary trick
is a workaround, not perfect.
**Use when:** documents with real tables (financials, spec sheets, PDFs/DOCX/
Confluence tables flagged `is_table` in the IR).

### 3.6 Image OCR (a pre-chunking step, not a chunker)
**How:** when the IR marks a page/region as a scanned image or image-only PDF,
run **OCR** to recover text (and layout where possible), then **re-enter the
router** so the recovered text is chunked by the appropriate strategy.
**Strength:** unlocks scanned/secured PDFs and screenshots that have no text layer.
**Weakness:** OCR noise; needs confidence filtering and cleaning
([06 §3.3](06-ingestion-pipeline.md)) before chunking.
**Use when:** scanned documents, image-only PDFs, diagrams with embedded text.
Track `ocr=true` in metadata so retrieval/citations can flag lower-confidence text.

### 3.7 Header-aware chunking (a cross-cutting enrichment)
**How:** track the heading hierarchy while splitting and **prefix each chunk with
its heading path** (e.g. `Guide › Setup › Authentication`), and store it in
metadata.
**Strength:** turns a fragment into a self-contained unit ("a chunk about auth
under setup") — improves both embedding quality and citation readability; enables
**filtering by section** in Qdrant.
**Weakness:** none significant; it augments other strategies rather than replacing
them.
**Use when:** **almost always** for structured content (markdown, Confluence,
Notion, DOCX). It composes with markdown/recursive/semantic chunking rather than
competing with it.

---

## 4. When to use each — decision guide

| Content signal (from IR) | Primary strategy | Composed with |
|---|---|---|
| Plain prose, no structure | Recursive (default) | overlap |
| Long prose, drifting topics, quality-critical | Semantic | header-aware |
| Markdown / Notion / Confluence | Markdown | header-aware |
| Source code / API refs | Code (tree-sitter) | recursive sub-split |
| Tables (`is_table`) | Table (repeat header) | — |
| Scanned / image-only | OCR → re-route | cleaning, then above |
| Any headed document | (above) | **Header-aware** |

**Routing precedence inside a single document:** a real document is *mixed* — a
markdown page can contain code fences and tables. The router operates at the
**element level** of the IR: it chunks each element with the right strategy
(prose→semantic/recursive, fence→code, table→table) and merges the results in
reading order, all stamped with the shared header path. So "which strategy" is
not one choice per document but one per element.

**KB-level configuration:** `knowledge_bases.chunking_config` sets the defaults
and budgets (target tokens, overlap %, semantic threshold, enable/disable
strategies) so different KBs can tune chunking to their corpus without code
changes — and changing it is a **re-index** ([04 §8](04-vector-db-design.md)),
since chunk boundaries change the vectors.

---

## 5. Why a router beats a single chunker

- **No universal optimum:** code, tables, and prose have incompatible notions of
  a "good boundary." A router applies the right one per element instead of
  forcing a compromise.
- **Quality where it pays, cost where it doesn't:** expensive semantic chunking
  is spent only on prose that benefits; cheap recursive handles the rest.
- **Composability:** header-awareness and overlap layer on top of every strategy,
  so improvements (a better table serializer, a new language parser) drop in
  behind the same port without touching ingestion or retrieval.
- **Graceful fallback:** any strategy that can't confidently split falls back to
  recursive, so the engine never fails to produce valid, token-bounded chunks —
  preserving the MVP's reliability guarantee while adding intelligence on top.
