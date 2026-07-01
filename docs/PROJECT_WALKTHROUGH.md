# RAG Platform — One-Page Walkthrough

**What it is:** A multi-tenant Retrieval-Augmented Generation platform. A company
registers, uploads documents, and instantly gets a grounded AI chatbot — over a
JSON/SSE API, an embeddable web widget, and an MCP server. Built to run on free
tiers (Neon Postgres, Cloudflare R2, Gemini/Groq) with production-grade internals
that scale by swapping adapters, not rewriting.

**Stack:** Python · FastAPI (async) · SQLAlchemy 2 + Alembic · Postgres · React/Vite ·
Groq + Gemini + Ollama (failover) · LangGraph · FastMCP · Langfuse/OpenTelemetry/Prometheus.

---

### Architecture — Clean Architecture + DDD (dependencies point inward only)
```
interfaces/   FastAPI routers, SSE streaming, auth, MCP server, SPA + widget.js
infrastructure/  SQLAlchemy+Postgres, Gemini/Groq/Ollama, R2, JWT, LangGraph, agent tools
application/  use cases + PORTS (Protocols) + the agent loop/router/registry
domain/       pure entities, value objects, the resumable ingestion state machine
config/       Pydantic settings + the DI composition root (the only place adapters are wired)
```
The domain imports nothing outward. Every external dependency sits behind a port,
so "swap pgvector → Qdrant" is one new adapter, zero domain changes.

### The AI Agents platform (the core of the role)
- **Orchestration:** a LangGraph `retrieve→assemble→generate` RAG path **and** a
  provider-agnostic **ReAct loop** that runs over a plain `generate()` call — same
  agent works across Groq, Gemini, and local Ollama.
- **Routing:** per-turn cheap-vs-strong model selection from a heuristic (length,
  reasoning markers, step depth) — a real cost lever.
- **Reusable components:** tools are a `Protocol` + registry; add a capability by
  registering a tool, not editing the loop.
- **Access control:** every tool call is tenant-scoped via `ToolContext` — a model
  asking for data can't widen scope.
- **Resilience:** hard `max_steps` budget; defensive JSON parsing (models wrap
  output in prose / hallucinate tool names → recoverable observations, not crashes);
  provider **failover** on rate-limit/error.

### Evaluation harness (ship with confidence)
Golden-dataset runner with **deterministic** metrics (precision/recall@k, citation
grounding, refusal-correctness) **plus** an optional **LLM judge** (faithfulness,
answer-relevance). Runs **offline in CI** for **regression gating** — agent quality
is a number, not a vibe.

### MCP connectors
A **FastMCP** server exposing tenant-scoped tools (`search_documents`,
`list_documents`, `answer_question`). Tool logic is SDK-independent (unit-tested
without the SDK); the connector inherits the platform's auth — no privilege bypass
just because a model is calling.

### Production rigor
Multi-tenant isolation at 5 layers (verified-credential tenant id → app scope →
per-query filter → Postgres RLS → tool context); Argon2 + JWT + API keys;
**resumable** ingestion (a host that sleeps mid-embed resumes from its last state);
per-tenant token quotas + rate limits; **every** request logged with its retrieval
trace; AI-native tracing + Prometheus + structured logs. Tested across domain,
agent loop, MCP, and evals.

---

### How I debug LLM systems (diagnose before you build)
Reported: *"chatbot won't answer from context, and the text has no spaces."*
1. **Spacing** → a frontend `.trim()` was stripping significant whitespace off every
   streamed SSE token. Rewrote the parser to preserve token whitespace + newlines.
2. **Grounding** → a `min_score` regression (0.0→0.65) over-filtered retrieval so
   context came back empty and the model fell back to its own knowledge — caught
   because an existing test still expected `0.0`.
3. **"Still broken"** → root cause wasn't code: FastAPI serves a prebuilt `dist/`
   that hadn't been rebuilt. Fix was `npm run build`, not a rewrite.

> I read code and traces before changing anything, and I'll take the one-line fix
> over the rewrite.

### Honest edges (and the path forward)
- Vector search currently computes cosine **in Python** over an array column (fine
  at free-tier scale) — clean migration path to a pgvector ANN index or Qdrant via
  one adapter.
- Hybrid search / re-ranking are designed **seams** (clean LangGraph nodes), not yet
  implemented.
- Architected for scale; deployed on free tiers, not yet load-tested at scale.
