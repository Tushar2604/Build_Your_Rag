# Prompt 14 — Evaluation Harness Design

> Scope: how we know the RAG system is *good* — and stays good — instead of
> guessing. Retrieval and generation are full of silent regressions (a prompt
> tweak, a model swap, a chunking change can quietly wreck answer quality with no
> error). The MVP ships the seams this hangs off: deterministic `Citation`s with
> `document_id`/`ordinal`/`score`, a `provider`/`model` stamp on every answer, and
> token accounting ([09 §9](09-retrieval-engine.md),
> [11 §6](11-llm-gateway.md)). This designs the harness that turns those into
> measured quality. No code.

---

## 1. Two halves: retrieval quality and generation quality

A RAG answer can fail in two independent places, and they need different metrics:

```
question ─► RETRIEVAL ─► did we fetch the right chunks?   (Recall@K, MRR, Precision)
                │
                ▼
            GENERATION ─► did the answer use them faithfully?  (Groundedness,
                                                                 Faithfulness,
                                                                 Hallucination rate)
```

Measuring them separately is the whole point: a bad answer from *good* context is
a generation/prompt bug; a bad answer from *bad* context is a retrieval bug. Mixing
them into one "is it good?" score hides which half to fix.

---

## 2. The golden dataset (the foundation everything rests on)

Without labeled truth there is nothing to measure against. The **golden dataset**
is a tenant-scoped, versioned set of:

- **question**, optionally with conversation history (to test follow-up rewriting,
  [10 §4](10-chat-service.md));
- **relevant chunk ids** — the chunks that *should* be retrieved (powers Recall/MRR/
  Precision);
- **reference answer** — a human-vetted ideal answer (powers answer-quality
  scoring);
- **expected behavior flags** — e.g. "should refuse / answer not in corpus" to test
  the hallucination guardrail ([10 §6](10-chat-service.md));
- **metadata** — source doc, difficulty, category, so failures are sliceable.

Construction & hygiene:
- **Seed from real traffic** — mine `retrieval_logs` ([15 §5](15-observability.md))
  for real questions, label them. Real questions beat invented ones.
- **Version it** — the golden set is pinned and changes are reviewed; a metric
  number is meaningless without the dataset version it ran against.
- **Keep it frozen for regression**, and grow a *separate* expanding set as new
  failure modes are found — never silently relabel, or you can't compare across
  time.
- **Tenant-isolated:** each tenant's golden set references only its own chunks
  ([12](12-multi-tenancy.md)).

---

## 3. Retrieval metrics

Computed by running the **retriever only** ([09](09-retrieval-engine.md),
`retrieve_only`) against each golden question and comparing returned chunk ids to
the labeled relevant set.

| Metric | What it answers | Why it matters here |
|---|---|---|
| **Recall@K** | of the relevant chunks, how many appear in the top K? | the ceiling on everything — downstream stages only *remove* candidates ([09 §4](09-retrieval-engine.md)); a miss here is unrecoverable |
| **MRR** | how high is the *first* relevant chunk ranked? | with a small context budget, rank matters; rank-1 ≫ rank-9 |
| **Precision@K** | of the top K, how many are actually relevant? | low precision = noise in the prompt = confident wrong answers |

Report **per K** (e.g. K=3/5/10) and **sliced** by difficulty/category — an
aggregate number hides that you're great on FAQs and terrible on tables. These
metrics are how you justify adding a reranker: measure Recall/MRR before and after
([09 §6](09-retrieval-engine.md)).

---

## 4. Generation metrics

Computed by running the **full pipeline** and scoring the answer against its
retrieved context and the reference answer. Most need an **LLM-as-judge** (a strong
model grading on a rubric), routed through the gateway like any other call
([11](11-llm-gateway.md)) and itself periodically validated against human labels so
the judge doesn't silently drift.

- **Groundedness** — is every claim in the answer *supported by the retrieved
  context*? Decompose the answer into claims, check each against the context. This
  directly tests the `[Source N]` contract the chat service depends on
  ([10 §6](10-chat-service.md)).
- **Faithfulness** — does the answer *contradict* the context or invent beyond it?
  (Groundedness asks "is it supported"; faithfulness asks "does it stay within.")
- **Hallucination rate** — the share of answers containing unsupported or fabricated
  claims, **and** the share that failed to refuse when the answer wasn't in the
  corpus (the `"(no relevant context found)"` path,
  [09 §8](09-retrieval-engine.md)). This is the metric that protects user trust.
- **Answer relevance / correctness** — does it actually answer the question, and
  agree with the reference? (semantic similarity + judge rubric.)

---

## 5. Operational metrics (measured on every eval run, not just quality)

- **Latency** — end-to-end and **per stage** (embed → retrieve → rerank →
  generate), p50/p95/p99. Surfaces *where* time goes, reusing the same per-stage
  timing as production tracing ([15 §1](15-observability.md)). Quality at 30s is a
  regression even if the number is right.
- **Token cost** — input/output tokens and $ per answer, from the gateway's
  metering ([11 §6](11-llm-gateway.md)). A prompt change that adds 15% quality for
  3× cost is a *decision*, not an automatic win — the harness makes the trade-off
  explicit.

Quality, latency, and cost are reported **together** for every change, because
improving one usually moves the others.

---

## 6. Regression testing & the promotion gate

The harness exists to **catch silent regressions** before users do.

- **What's a "change":** a new prompt version ([11 §7](11-llm-gateway.md)), a model
  swap, a chunking-config change, a retrieval-config change (reranker on/off, K,
  fusion weights). Each is a candidate that must beat the current baseline on the
  frozen golden set.
- **Promotion gate:** a change is promoted only if it **improves or holds** quality
  metrics without unacceptable latency/cost regression. Thresholds are explicit
  (e.g. "Recall@5 must not drop >1pt; hallucination rate must not rise").
- **Tie to versions:** every prompt/model version is pinned to its eval results, so
  a bad promotion is **instantly rollback-able** to a known-good version
  ([11 §7](11-llm-gateway.md)).
- **CI integration:** the eval suite runs in CI on the golden set; a PR that
  regresses quality fails the same way a broken unit test does.

---

## 7. Continuous evaluation (production, not just CI)

CI eval uses labeled data; **production has truth CI never sees.**

- **Online sampling:** sample a slice of real answers and score them with the
  LLM-judge ([15 §5 retrieval/prompt logs](15-observability.md)) — groundedness and
  refusal-correctness on *live* traffic, catching distribution shift the golden set
  can't.
- **Implicit signals:** thumbs-up/down, follow-up rephrasings (a sign of a bad
  answer), citation click-through, "no relevant context" rate — cheap, abundant
  quality proxies.
- **Drift alerts:** a rising live hallucination rate or falling groundedness fires
  an alert ([15 §8](15-observability.md)) and **feeds the golden set** — new failure
  modes become tomorrow's regression tests (§2).
- **Runs as a worker:** scheduled + on-demand via the `evals` worker
  ([13 §3.7](13-background-workers.md)), so it never touches the request path.

---

## 8. Why this shape

- **Separate retrieval from generation** so a regression points at the half that
  broke instead of a vague "quality dropped."
- **The golden set is the asset:** versioned, real-traffic-seeded, tenant-scoped
  labeled truth is what makes every number meaningful and every comparison fair.
- **Quality + latency + cost together:** no metric is improved in a vacuum on a
  free tier; the harness makes the trade-off a visible decision.
- **Gate, then watch:** offline evals gate promotion and enable instant rollback;
  continuous eval catches what offline can't and refills the golden set — a closed
  loop, not a one-time benchmark.
- **It rides existing seams:** deterministic citations, the `provider`/`model`
  stamp, per-stage timing, and gateway token metering already exist — the harness
  reads them, it doesn't require re-plumbing the system.
