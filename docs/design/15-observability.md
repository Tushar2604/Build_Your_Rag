# Prompt 15 — Observability Design

> Scope: making the system explainable in production — what happened, how fast,
> why it failed, and what it cost — across a request path that spans HTTP →
> retrieval → LLM → workers. The MVP ships the foundation: **structlog** JSON logs
> with a per-request correlation id bound by middleware, **Prometheus** counters/
> histograms, and `/healthz` `/readyz` `/metrics` endpoints
> ([src/infrastructure/observability/logging.py](../../src/infrastructure/observability/logging.py),
> [src/interfaces/api/routers/health.py](../../src/interfaces/api/routers/health.py)).
> This designs the full picture those grow into. No code.

---

## 1. Tracing

A single chat answer touches HTTP → query rewrite → embed → retrieve →
(rerank) → generate → assemble, plus async ingestion/eval workers. Without a
trace, a "slow answer" is unattributable.

- **Correlation id today, trace context tomorrow:** the API middleware already
  binds a per-request id into `structlog.contextvars`
  ([logging.py](../../src/infrastructure/observability/logging.py)) so every log
  line for one request is joinable. The next step is **OpenTelemetry** spans: one
  trace id per request, a child **span per pipeline stage** (the same stages the
  LangGraph nodes already are, [09](09-retrieval-engine.md)), carrying timing +
  attributes.
- **Propagation across boundaries:** the trace id rides the SSE response and is
  injected into **worker task payloads** ([13](13-background-workers.md)) alongside
  `tenant_id`, so an ingestion job traces back to the upload that scheduled it.
- **Span attributes:** `tenant_id`, `chatbot_id`, `session_id`, model/provider, K,
  chunk count, token counts — turning a trace into a per-stage cost/latency
  breakdown, which is exactly what the eval harness reports
  ([14 §5](14-evaluation-harness.md)).

---

## 2. Logging

- **Structured JSON in prod, pretty console in dev** — already shipped; machine-
  parseable for any aggregator's free tier
  ([logging.py](../../src/infrastructure/observability/logging.py)).
- **Always-bound context:** `correlation_id`, `tenant_id`, `path`, `status`,
  `duration_ms` on every line via `merge_contextvars`, so logs filter per tenant
  and per request without grepping.
- **Levels with intent:** INFO for lifecycle (request, `llm.failover`,
  `document.embedded`), WARN for handled degradation (retry, rate-limit backoff),
  ERROR for unhandled failures with full traceback.
- **The hard privacy rule:** logs **never contain another tenant's content**, and
  by default don't log raw document text or full prompts at INFO — those go to the
  dedicated, access-controlled prompt/retrieval logs (§4–5) with retention limits.
  This is a multi-tenancy invariant, not a nicety ([12 §7](12-multi-tenancy.md)).

---

## 3. Metrics

Prometheus is the shipped backbone (`/metrics`,
[logging.py](../../src/infrastructure/observability/logging.py)). Existing
counters/histograms — `http_requests_total`, `http_request_duration_seconds`,
`llm_tokens_total{provider}`, `ingest_documents_total{status}` — extend to the
**RED + USE** model:

- **RED** (per endpoint *and* per pipeline stage): **R**ate, **E**rrors,
  **D**uration — request throughput, error ratio, latency histogram.
- **RAG-specific gauges:** retrieval `min_score` pass-rate, "no relevant context"
  rate ([09 §8](09-retrieval-engine.md)), `llm.failover` count, embedding rate-limit
  hits, DLQ depth ([13 §5](13-background-workers.md)), queue lag per worker.
- **Cost as a metric:** tokens and $ per provider/model/tenant from the gateway
  choke point ([11 §6](11-llm-gateway.md)).
- **Cardinality discipline:** label by `tenant_id` only where the series count is
  bounded; high-cardinality IDs (`session_id`) belong in **traces/logs**, not
  metric labels, or Prometheus melts.

---

## 4. Prompt logs

Generation is the least debuggable part of the system, so capture the full
generation record (sampled or full, per policy) **separately** from app logs:

- **Contents:** the resolved prompt + version ([11 §7](11-llm-gateway.md)), system
  prompt, assembled context blocks, the answer, `provider`/`model`, token counts,
  finish reason, latency. This is the provenance the eval harness scores
  ([14 §4](14-evaluation-harness.md)).
- **Why separate:** it contains tenant content, so it lives in an access-controlled
  store with **short retention** and per-tenant scoping — never in the general log
  stream (§2).
- **Use:** reproduce a bad answer exactly, A/B prompt versions, feed continuous
  eval ([14 §7](14-evaluation-harness.md)).

---

## 5. Retrieval logs

The other half of every answer: **what was retrieved and why.**

- **Contents:** the (rewritten) query, candidate chunk ids with scores at each
  stage (dense/sparse/fused/reranked, [09](09-retrieval-engine.md)), the applied
  filters (`tenant_id`, `document_ids`), and which chunks survived into the prompt.
- **Use:** diagnose "wrong answer" as a *retrieval* miss vs. a *generation* miss
  (the split the eval harness is built around, [14 §1](14-evaluation-harness.md)),
  mine real questions to **seed the golden dataset** ([14 §2](14-evaluation-harness.md)),
  and tune K / fusion / reranking with real evidence.
- Tenant-scoped and content-bearing → same access/retention controls as prompt
  logs.

---

## 6. Latency

- **Per-stage, not just end-to-end:** the trace spans (§1) give p50/p95/p99 for
  embed / retrieve / rerank / generate independently — "slow answer" becomes
  "rerank p99 is 800ms."
- **Streaming has two numbers that matter:** **time-to-first-token** (perceived
  responsiveness over SSE, [10 §2](10-chat-service.md)) and total stream duration —
  track both; TTFT is the one users feel.
- **Cold starts are first-class on a free tier:** the first request after a host
  sleeps is slow by design ([README](../../README.md)); measure and label it so it
  isn't mistaken for a regression.

---

## 7. Errors

- **Captured with context:** every error carries `correlation_id` + `tenant_id` +
  stage, so it's traceable to one request and one tenant.
- **Classified the way the system already treats them:** transient (retry/failover,
  [11 §4](11-llm-gateway.md), [13 §4](13-background-workers.md)) vs. permanent
  (fail-fast). Error *dashboards* separate "self-healing" from "needs a human."
- **Aggregation:** an error-tracking sink (Sentry-class) groups by fingerprint so
  one bad deploy is one alert, not 10,000 — with the trace id to jump straight to
  the failing request.
- **Worker errors surface too:** DLQ arrivals ([13 §5](13-background-workers.md))
  are errors with an owning tenant, inspected without leaking across tenants.

---

## 8. Dashboard

One operational view, sliceable by tenant and time:

- **Golden signals:** request rate, error rate, latency (p50/95/99), saturation
  (queue lag, worker pool utilization, DB connections).
- **RAG health:** retrieval pass-rate, "no context" rate, hallucination rate from
  continuous eval ([14 §7](14-evaluation-harness.md)), failover frequency.
- **Cost:** tokens/$ per tenant/provider/model, vs. per-tenant quotas
  ([12 §5](12-multi-tenancy.md), [11 §6](11-llm-gateway.md)).
- **Pipeline:** ingestion throughput, documents by `status`, DLQ depth.
- **Free-tier stack:** Prometheus + Grafana, or a hosted free tier — the `/metrics`
  endpoint already speaks the standard, so this is a scrape target away.

---

## 9. Alerting

Alerts must be **actionable** and **few** — page on symptoms users feel, not on
every blip.

- **Page (user-facing):** error rate over threshold, p99 latency over SLO, `/readyz`
  failing (DB unreachable, [health.py](../../src/interfaces/api/routers/health.py)),
  both LLM providers failing (failover exhausted, [11 §3](11-llm-gateway.md)).
- **Warn (operational):** rising DLQ depth / queue lag, embedding rate-limit
  saturation, a tenant approaching its quota, cold-start frequency climbing.
- **Quality (slow-burn):** continuous-eval hallucination rate up or groundedness
  down — routed to the team that owns prompts, not paged at 3am
  ([14 §7](14-evaluation-harness.md)).
- **Hygiene:** every alert names a runbook and a dashboard link; thresholds are
  tuned to avoid fatigue (a muted alert is worse than none).

---

## 10. Why this shape

- **One request is one story:** correlation id → trace id → per-stage spans means
  "slow/wrong/expensive" is always attributable to a stage, a tenant, and a
  provider — never a shrug.
- **Three log planes, deliberately split:** app logs (no tenant content), prompt
  logs, retrieval logs — so debugging power and tenant privacy don't fight
  ([12 §7](12-multi-tenancy.md)).
- **The seams already exist:** structlog context, Prometheus `/metrics`, the
  `provider`/`model` stamp, and deterministic citations are shipped — observability
  is reading and extending them, not bolting on a new system.
- **It closes the loop with eval:** retrieval/prompt logs feed the golden set and
  continuous eval ([14](14-evaluation-harness.md)); alerts fire on the quality
  metrics that loop produces — observation and improvement are the same pipeline.
