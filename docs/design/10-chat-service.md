# Prompt 10 — Chat Service Design

> Scope: the conversational layer the user actually talks to — it owns sessions
> and messages, calls retrieval ([09](09-retrieval-engine.md)), calls the LLM
> through the failover router ([11](11-llm-gateway.md)), and returns grounded,
> cited, streamed answers. The MVP ships this end to end: `AskChatbot`
> ([src/application/use_cases/ask_chatbot.py](../../src/application/use_cases/ask_chatbot.py)),
> the SSE stream endpoint
> ([src/interfaces/api/routers/chat.py](../../src/interfaces/api/routers/chat.py)),
> and the LangGraph flow
> ([src/infrastructure/rag/graph.py](../../src/infrastructure/rag/graph.py)). This
> documents every component and where it grows. No code.

---

## 1. Anatomy of one turn

```
POST /sessions/{id}/messages   (JSON)      POST /sessions/{id}/stream   (SSE)
        │                                          │
        ▼                                          ▼
 load session + chatbot (tenant-scoped)     same, in a short up-front txn
        │                                          │
 quota guard (daily_token_quota)            quota guard
        │                                          │
 retrieve  ([09])                            retrieve_only → citations
        │                                          │
 persist user message                        persist user message + commit
        │                                          │
 assemble context + generate                 emit "citations" event
        │                                          │ then stream "token" events
 persist assistant msg + usage               persist assistant msg + usage
        │                                          │
 return answer + citations (JSON)            emit "done" {tokens_used}
```

Both paths share retrieval, context assembly, the quota guard, and usage
accounting; they differ only in *how the answer is delivered*. The JSON path runs
the full graph (`retrieve → assemble → generate`); the stream path reuses
`retrieve_only` + `build_context`, then streams generation token-by-token.

---

## 2. Streaming

Token-by-token delivery over **SSE** (`EventSourceResponse`, `sse-starlette`).
Perceived latency drops sharply — the user sees progress while the model generates.

The MVP already streams **structured events**, not just text:

| Event | Payload | Purpose |
|---|---|---|
| `citations` | source list (doc, ordinal, score, snippet) | render attribution **before** any token arrives |
| `token` | a text delta | the streamed answer |
| `done` | `{tokens_used}` | finalize; usage persisted |

Design properties:
- **Retrieval happens once, up front** — citations are known before generation, so
  the UI can show sources immediately. Generation streams through
  `LLMProvider.stream`, which the failover router proxies ([11](11-llm-gateway.md)).
- **Read-only retrieval runs outside the write transaction** via `_ChunkRepoProxy`,
  so no DB transaction is held open for the whole stream.
- **Persistence is deferred to stream end:** the assistant message + token usage are
  written after the last token, in their own short transaction.
- **Growth:** add an `error` event for mid-stream provider failure (partial answer +
  graceful close) and propagate client disconnects upstream to abort generation and
  stop paying for tokens.

---

## 3. Conversation memory & context window

Today each turn is **stateless beyond persistence**: messages are stored
(`chat_messages`, with `citations` and `tokens_used`) and listable via
`list_messages`, but the prompt sent to the LLM is just
`Context:\n{context}\n\nQuestion: {message}` — prior turns aren't replayed. That's
the honest MVP state. The design to grow into:

**Memory tiers**
- **Short-term** — the recent turn list from `chat_messages`, injected into the
  prompt so the bot remembers the conversation.
- **Rolling summary** — as a session grows, older turns are summarized (a cheap
  gateway call) into a compact memory, kept instead of raw history to bound tokens.
- **Semantic memory (optional)** — durable facts/preferences stored as retrievable
  items for very long-lived sessions.

**Context window budget** — the assembled prompt must fit the model window with
room to answer. Allocate across: `system_prompt` + retrieved context (bounded by
[09](09-retrieval-engine.md)'s top-N + compression) + conversation history +
current question + reserved output. Under pressure, evict **oldest history first**
(summarize, don't drop silently); always keep system prompt + current question +
retrieved context. Count with the target model's tokenizer rather than the current
`len//4` estimate, which is only good enough for quota accounting.

---

## 4. Follow-up questions

Conversational queries are context-dependent: *"What about its pricing?"* means
nothing to a retriever in isolation. So before retrieval the service performs
**query rewriting / contextualization** — a small gateway call that rewrites the
follow-up into a **standalone query** using recent history. The retriever
([09 §2](09-retrieval-engine.md)) only ever receives that self-contained query.

This is essential, not optional: multi-turn retrieval quality lives or dies here.
It's a new step in front of the graph's `retrieve` node (the graph was explicitly
designed to accept a `query-rewrite` node) and reuses the same `LLMProvider` port.

---

## 5. Citations — *shipped*

Grounding must be verifiable, so citations are first-class throughout:

- Retrieval emits `Citation(document_id, chunk_id, ordinal, score, snippet)`.
- `build_context` formats them as `[Source N | doc=… | score=…]` blocks so the model
  can reference sources by ordinal.
- Citations are **persisted on the assistant message** (`chat_messages.citations`
  JSONB) and returned to the client (JSON response, or the `citations` SSE event).

**Growth:** instruct the model to emit inline `[N]` markers, then **post-validate** —
map each marker back to a real retrieved chunk and drop/flag any citation that
doesn't resolve. This turns "sources we retrieved" into "sources the answer
actually used."

---

## 6. Hallucination prevention

Defense in depth — no single mechanism is trusted:

1. **Grounding prompt** — the chatbot's `system_prompt` instructs "answer *only*
   from the provided context; if it isn't there, say you don't know." Stored per
   chatbot, so each tenant tunes its own guardrail.
2. **High-precision retrieval** — rerank + MMR + compression
   ([09](09-retrieval-engine.md)) keep noise out; garbage context → confident wrong
   answers.
3. **Refuse on empty context** — when retrieval clears nothing above `min_score`,
   the context is literally `"(no relevant context found)"` and the model is told to
   decline rather than invent. (Shipped behavior.)
4. **Citation enforcement** (§5) — every claim should trace to a chunk; unsupported
   claims are the tell.
5. **Faithfulness check (high-stakes, optional)** — a second pass (LLM-as-judge or
   an NLI model) verifies the answer is entailed by the context; low scores trigger
   the "I don't have enough information" fallback.
6. **Low temperature** for factual RAG; surface uncertainty rather than smoothing
   over it.

---

## 7. Cross-cutting: tenancy, quotas, resilience

- **Tenant scope on every turn:** both endpoints call `set_tenant_scope` and load
  session/chatbot tenant-filtered — isolation is enforced here and by RLS
  ([12](12-multi-tenancy.md)).
- **Quota guard:** before generating, `usage.tokens_used_today` is checked against
  the tenant's `daily_token_quota`; over → `QuotaExceededError`. After generating,
  `usage.add_tokens` records the spend (atomic Postgres upsert — the
  no-Redis design, [12](12-multi-tenancy.md)). This protects the shared free-tier
  pools.
- **Generation resilience** is delegated to the gateway's failover router
  ([11](11-llm-gateway.md)), so free-tier rate limits degrade to the secondary pool
  instead of erroring mid-chat.

---

## 8. Why this shape

- **One orchestration, two deliveries:** JSON and SSE share retrieval, quota, and
  usage logic — streaming is a delivery concern, not a separate pipeline.
- **Grounding is structural:** citations flow from retrieval through persistence to
  the client, and empty-context refusal is wired in — hallucination defense isn't
  bolted on, it's the data path.
- **Memory and follow-up rewrite are insertable nodes**, not rewrites — the graph
  and ports already accommodate them, matching the MVP's "grow without rewrite"
  thesis.
- **Cost and isolation are enforced at the turn boundary**, where the user-facing
  request actually is, rather than hoped for deeper down.
