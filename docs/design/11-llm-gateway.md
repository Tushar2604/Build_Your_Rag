# Prompt 11 — Provider-Agnostic LLM Gateway Design

> Scope: the single seam through which all *generation* flows, so the rest of the
> system codes against one interface while the gateway handles provider quirks,
> resilience, routing, and cost. The MVP ships the core of this: the `LLMProvider`
> port ([src/application/ports/services.py](../../src/application/ports/services.py)),
> two adapters + a failover router (`GroqProvider`, `GeminiProvider`, `FailoverLLM`,
> [src/infrastructure/llm/providers.py](../../src/infrastructure/llm/providers.py)),
> and `build_llm` selecting primary/secondary from config
> ([src/config/settings.py](../../src/config/settings.py)). This designs the full
> gateway those grow into. No code.
>
> *Note: Anthropic/Claude tier names below are kept generic; exact model IDs and
> pricing should come from the live model reference, not hard-coded here.*

---

## 1. The port is already the gateway interface

The whole system depends on three methods and one result type:

```
LLMProvider
  name: str
  generate(system, user) -> LLMResult(text, tokens_used, provider, model)
  stream(system, user)   -> AsyncIterator[str]
```

`AskChatbot`, `RagGraph`, and the SSE endpoint depend **only** on this Protocol —
they never know whether the call hit Groq, Gemini, or a five-provider routed mesh.
That indirection is what makes everything below additive: a richer gateway is a
new `LLMProvider` implementation behind the same port, swapped at the composition
root (`build_llm`). The MVP's `FailoverLLM` is already exactly that — a provider
that wraps other providers.

---

## 2. Provider adapters

Each provider is an `LLMProvider` adapter that normalizes the native API into the
common shape: message mapping, response text, **token-usage extraction**, finish
reasons, and error semantics. SDKs are imported lazily (as the MVP does) so a
missing key never breaks module load.

| Provider | MVP role | Strength | Normalization notes |
|---|---|---|---|
| **Groq** | **shipped primary** | ultra-low latency on open models | OpenAI-style chat API; real `usage.total_tokens` |
| **Gemini** | **shipped fallback** | free tier, long context, multimodal | sync SDK → bridged to async via `to_thread`; tokens estimated |
| **OpenAI** | drop-in | mature tools / JSON mode | reference chat schema |
| **Anthropic** | drop-in | strong reasoning, long context, prompt caching | tool-use + system handled distinctly |
| **Ollama** | self-host | zero marginal cost, on-prem data | local endpoint; no rate limit, capacity-bound |
| **OpenRouter** | meta-router | one key → many models | useful as overflow/fallback target |

**Model aliases, not hard providers:** callers request a logical alias
(`chat-default`, `cheap-summarizer`) that config resolves to a concrete
provider/model + an ordered fallback chain. The MVP's `generation_primary` switch
is the seed of this; the full version moves alias→target maps into config so
routing changes need no code change.

---

## 3. Automatic failover — *shipped, generalized*

The MVP's `FailoverLLM` tries the primary and, on **any** exception, falls back to
the secondary — for both `generate` and `stream` — logging `llm.failover`. This is
the key free-tier resilience feature: a rate-limited Groq still gets answered by
Gemini.

Generalized to an **ordered chain per alias**:
- Failover-eligible errors: `5xx`, timeouts, rate-limit-exhausted, provider outage.
  **Not** eligible: `400`/auth — those fail fast.
- **Fallback equivalence classes** — chain only models of comparable
  capability/cost so a failover doesn't silently and badly degrade quality.
- **Circuit breaker** — trip a provider that's failing repeatedly; route around it
  until a health probe shows recovery, instead of paying the timeout every request.
- **Streaming caveat (real):** today, failover on `stream` only triggers if the
  primary fails *before* the first token; once tokens are flowing, mid-stream
  failure can't transparently switch. The design notes this and handles it with an
  `error` event ([10 §2](10-chat-service.md)) rather than pretending it's seamless.

---

## 4. Retries

Per-target retries sit *inside* each adapter (the MVP already wraps
`GroqProvider.generate`/`GeminiProvider.generate` with `tenacity`,
`stop_after_attempt(3)`, exponential backoff). Discipline:

- **Retry transient only** (`429`/`5xx`/timeout); honor `Retry-After`.
- **Bounded attempts + global deadline** so a slow provider doesn't stall a chat.
- **Distinguish two layers:** retry-on-same-provider (transient blip) vs
  failover-to-next (§3, provider down). Retry locally a couple times, then fail over.
- Pure completions are safe to retry; this gateway carries no non-idempotent side
  effects (usage accounting happens once, after a successful answer, in the chat
  service).

---

## 5. Load balancing

Across healthy targets and multiple keys for one provider:
- **Weighted / least-loaded / latency-aware** distribution.
- **Key rotation** to spread RPM/TPM across free-tier keys (mirrors the embedding
  service's key strategy, [08 §5](08-embedding-service.md)).
- **Tier routing** — classify request difficulty and send easy work to cheap/fast
  targets (Groq, a Haiku-class model, local Ollama) and hard work to premium models.
  This is the cost lever that most benefits a free-tier-first deployment.

---

## 6. Cost tracking

The gateway is the **one choke point** all generation flows through, so meter it
here:

- Capture input/output tokens per call from `LLMResult.tokens_used` (real where the
  provider reports it, estimated otherwise — the MVP does both) × per-model rate.
- **Attribute to tenant / chatbot / feature.** This connects directly to the
  shipped accounting: `usage.add_tokens` + the per-tenant `daily_token_quota`
  enforced in the chat service ([10 §7](10-chat-service.md), [12](12-multi-tenancy.md)).
- **Budgets & alerts** — per-tenant spend caps; throttle or fail over to a cheaper
  tier on overrun.
- **Emit metrics** (latency, error rate, tokens, cost, failover count) per
  provider/model — these feed both dashboards and the routing decisions in §3/§5.
- **Prompt caching** (where providers support it, e.g. Anthropic) cuts repeat-prompt
  cost; track hit rates.

---

## 7. Prompt versioning

Prompts are code and need version control. Today the system prompt lives per
chatbot (`chatbots.system_prompt`) and the RAG template is inline in `AskChatbot` /
the stream endpoint. The design:

- **Prompt registry** — templates with semantic versions + metadata (intended
  model, params). Requests reference a prompt id + version (or pin via alias).
- **A/B + gradual rollout + instant rollback** of a prone-to-break prompt.
- **Provenance logging** — record which prompt version + provider/model produced
  each answer (alongside the existing `provider` field on the response and the
  `MessageAnswered` event) for reproducibility and eval.
- **Tie versions to eval suites** so a prompt change is validated before promotion.

---

## 8. Why this shape

- **One port, infinite backends:** `LLMProvider` already abstracts generation;
  failover, routing, retries, and cost tracking are all *just another provider* or
  internal concern behind it — the chat service never changes.
- **Resilience is the default, not an add-on:** the shipped `FailoverLLM` makes "two
  free pools, degrade don't error" the baseline; the design hardens it with circuit
  breakers and equivalence classes.
- **Cost is observable because it's centralized:** every token crosses one seam, so
  per-tenant metering and quotas (already enforced) extend naturally to budgets and
  tier routing.
- **Free-tier now, paid later, no rewrite:** Groq+Gemini today; OpenAI/Anthropic/
  Ollama/OpenRouter are config + an adapter — the same growth promise as the
  embedding service ([08](08-embedding-service.md)).
