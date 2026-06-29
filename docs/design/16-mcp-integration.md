# Prompt 16 — MCP Integration Layer Design

> Scope: letting a chatbot do more than *read documents* — letting it **act**, by
> calling external systems (CRM, HRMS, Slack, GitHub, Jira, Google Drive) through
> the **Model Context Protocol**. This turns a retrieval bot into an agent. None of
> this ships in the MVP, which is read-only RAG; the seam it hangs off is the
> generation gateway and the LangGraph pipeline
> ([11](11-llm-gateway.md), [src/infrastructure/rag/graph.py](../../src/infrastructure/rag/graph.py)),
> where a "tool call" node sits beside the existing retrieve/generate nodes.
> Security and permissions are the heart of this doc, not an appendix. No code.

---

## 1. What MCP adds, and where it plugs in

Today the pipeline is `retrieve → generate`. MCP adds a **tool-use loop**: the
model may, mid-answer, decide it needs live data or an action, call a tool, read
the result, and continue.

```
question ─► retrieve (RAG context)
              │
              ▼
          generate ──► model emits tool_call(name, args)
              ▲                       │
              │                  [MCP gateway]  ◄── authz, scoping, audit
              │                       │
              └──── tool_result ◄─────┘  (CRM / HRMS / Slack / GitHub / Jira / Drive)
```

- **MCP servers** expose each external system as a set of **tools** (typed
  name + schema + description). The platform runs an **MCP gateway** (an MCP
  *client*/host) that brokers between the model and those servers.
- **It rides the existing seam:** tools are offered to the model through the LLM
  gateway ([11 §2](11-llm-gateway.md)); a `tool` node in the graph executes the
  call and feeds the result back — the chat service contract
  ([10](10-chat-service.md)) is unchanged, the loop just has more nodes.
- **Provider-agnostic by design:** MCP is the standard tool interface, so the same
  tool catalog works whether generation is Groq, Gemini, or a model with native
  tool-use — mirroring the "one port, many backends" thesis
  ([11 §1](11-llm-gateway.md)).

---

## 2. The connectors (tools per system)

Each integration is an MCP server exposing a **narrow, typed** tool set — never raw
API passthrough. Read tools and write tools are distinguished because they carry
very different risk (§4–5).

| System | Representative tools | Predominant risk |
|---|---|---|
| **CRM** (Salesforce/HubSpot) | `find_contact`, `get_deal`, `create_note`, `update_stage` | writes mutate revenue data |
| **HRMS** (Workday/BambooHR) | `get_employee`, `get_pto_balance`, `request_leave` | highly sensitive PII |
| **Slack** | `search_messages`, `post_message`, `list_channels` | posting *as* a user; channel scope |
| **GitHub** | `search_code`, `get_issue`, `create_issue`, `comment_pr` | code exfiltration; repo writes |
| **Jira** | `search_issues`, `get_issue`, `create_issue`, `transition` | workflow mutation |
| **Google Drive** | `search_files`, `read_file`, `list_folder` | broad-scope read of org data |

Design rules for every connector:
- **Least-privilege tools:** expose the specific verbs needed, not "call any
  endpoint." A smaller surface is a smaller attack surface.
- **Typed schemas:** strict input/output schemas so the model can't smuggle
  free-form payloads, and so arguments are validated before any call (§4).
- **Read/write separation:** writes are a distinct capability class requiring extra
  authorization (§5).

---

## 3. Security

The MCP layer hands an LLM the ability to call real systems with real credentials —
it is the **highest-risk surface in the platform** and is treated as adversarial by
default (the model can be manipulated via prompt injection, [17 §1](17-security-review.md)).

- **Credentials never touch the model or the tenant's browser.** OAuth tokens / API
  keys for each connector are stored **encrypted at rest, per tenant**, held only by
  the MCP gateway, and injected server-side at call time. The model sees tool
  *schemas*, never secrets — the same discipline as connector auth in ingestion
  ([06 §2](06-ingestion-pipeline.md)).
- **Tenant isolation extends to tools.** Every tool call is bound to the caller's
  `tenant_id` ([12](12-multi-tenancy.md)); a connector configured for tenant A is
  unreachable by tenant B, and results are never cached across tenants
  ([12 §5](12-multi-tenancy.md)).
- **The gateway is a policy enforcement point, not a pipe.** It validates every
  call against the tool's schema, checks authorization (§4), enforces rate/spend
  limits per tenant and per connector, and can **deny** — the model proposes, the
  gateway disposes.
- **SSRF & egress control:** connectors reach only their declared, allow-listed
  endpoints; no model-supplied URLs are fetched
  ([17 §5](17-security-review.md)). MCP servers run with locked-down egress.
- **Injection containment:** tool *results* (a Slack message, a Jira ticket, a Drive
  doc) are **untrusted content** and re-enter the prompt as data, not instructions —
  the same indirect-prompt-injection threat as a poisoned document
  ([17 §1–2](17-security-review.md)). They are clearly delimited and never granted
  authority to trigger further privileged actions on their own.
- **Full audit:** every tool invocation is logged (tenant, user, tool, arguments,
  result status, latency) to the audit trail
  ([15 §4](15-observability.md), `audit_events`), so any action is attributable and
  reversible-by-investigation.

---

## 4. Permission handling

Authorization is layered, and **the model is never the authority**:

```
1. Connector enabled for the tenant?          (admin config)
2. Tool allowed for THIS chatbot?             (per-chatbot tool allow-list)
3. Does the acting user have the scope?        (delegated user identity / OAuth scope)
4. Is this a write / high-risk action?         (explicit consent gate, §5)
5. Within rate / spend budget?                 (gateway limits)
   → only then execute, then audit.
```

- **Admin-scoped enablement:** an org admin connects a system (OAuth consent) and
  chooses which connectors exist. Enabling Slack does not enable GitHub.
- **Per-chatbot allow-lists:** a chatbot is granted a *subset* of tools. A public
  support bot ([12 §2](12-multi-tenancy.md)) gets read-only `search`-class tools and
  **no** write tools — ever. An internal ops bot may get more.
- **Delegated identity (the key principle):** where a system supports it, the tool
  acts **as the requesting user** (their OAuth token / scopes), so the bot can never
  see or do more than the human behind it could. It inherits, never escalates,
  permissions. A user who can't read a private Drive folder can't get the bot to
  read it for them.
- **Human-in-the-loop for writes:** a `create_issue` / `post_message` /
  `update_stage` proposes an action and **requires explicit user confirmation**
  before the gateway executes — the model's *intent* is separated from the
  *commit*. Read tools may run unattended; writes default to confirm.
- **Revocation & expiry:** OAuth tokens are refreshed/revocable per connector;
  revoking a connector instantly removes its tools from every chatbot, no redeploy.

---

## 5. Read vs. write, made explicit

The single most important authorization boundary:

- **Reads** (`search`, `get`, `list`) — lower risk, still tenant- and identity-
  scoped, still rate-limited and audited. May run inside the tool loop unattended.
- **Writes** (`create`, `update`, `post`, `transition`) — a distinct capability
  class. They require: the chatbot to hold the write tool, the user to have the
  underlying permission, **and** (by default) explicit confirmation. They are
  idempotency-keyed where possible so a retried tool call can't double-post.

This split is why §2 separates tools by verb: an injection that convinces the model
to "post our pricing to #public and delete the deal" hits a wall — the bot has no
write tools, or the write demands a human click the gateway never auto-supplies.

---

## 6. Why this shape

- **Acting is a privilege, not a default:** the MVP's read-only RAG is the safe
  floor; every tool is opt-in per connector and per chatbot, and writes are gated
  again on top.
- **The gateway, not the model, holds authority:** credentials, scoping, policy,
  rate limits, and audit all live in the MCP gateway — the LLM only ever proposes a
  typed call.
- **Tool results are untrusted input:** they re-enter the prompt as data under the
  same injection containment as poisoned documents
  ([17](17-security-review.md)) — agency doesn't bypass the security model, it
  inherits it.
- **It's the same architecture, extended:** one provider-agnostic interface (MCP),
  per-tenant isolation, encrypted per-tenant credentials, and full audit — the chat
  pipeline ([10](10-chat-service.md)) gains a tool node and nothing else has to
  change.
