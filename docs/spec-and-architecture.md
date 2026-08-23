# Argus - Autonomous Incident Response Agent
### Project Spec & Architecture (v1)

> Unified spec: product requirements and technical design in one doc. All `§N` refer to sections of this document.

---

## 1. Problem Statement

Production systems generate more alerts than humans can triage. Today an on-call engineer reads the alert, correlates it with recent changes (deploys, flags, config), forms a hypothesis, mitigates, finds root cause, fixes it, and documents it - slow and inconsistent across engineers.

**Argus** receives an alert via webhook and runs this workflow autonomously: investigate, mitigate reversible causes, propose a code fix, report status live (Slack/email), and produce a postmortem once resolved - escalating to a human whenever it isn't confident enough to act.

Argus is not "a chatbot with tools": it reasons under uncertainty, takes real (reversible) actions, tracks its own hypothesis history to avoid repeating failed attempts, and knows when to stop and hand off.

## 2. Scope

Argus runs against a self-contained **Target Service and Target Environment** that we build and control (§15), not real production. This is deliberate:

- Safe to demo - no real rollback/deploy risk.
- Evaluable - we control ground truth (§21).
- Realistic in interface - exposes the same *kind* of APIs real infra would (metrics query, log fetch, feature-flag service, deploy/CI, a git repo for branches/PRs); swapping in real infra later wouldn't change Argus's code (§12).

**In scope:**
- Webhook ingestion of an alert
- Log/metrics querying and correlation with recent changes
- Root-cause hypothesis generation and testing (ReAct loop)
- Reversible mitigation (flag toggle, deployment rollback)
- Code-level root cause search + PR generation (RAG over the Target Service codebase)
- Slack integration: reading hints, posting updates, creating war-room channels
- Persistent memory: per-incident state + cross-incident knowledge base
- Postmortem + executive summary generation (with cost estimation)
- Escalation to a human on low confidence or exhausted actions
- Dashboard to visualize incidents live and browse history

**Out of scope:**
- Real production infrastructure integration
- Fully autonomous PR merging (always needs human approval, §13)
- Guaranteeing root-cause correctness (accuracy is rigorously evaluated; perfection isn't guaranteed)

## 3. Goals & Success Criteria

| Goal | Success criterion |
|---|---|
| Detect & triage fast | Median time-to-first-hypothesis < 60s (Target Environment) |
| Correct mitigation | ≥ 80% correct mitigation on single-cause benchmark scenarios |
| Root cause accuracy | ≥ 70% correct root cause across benchmark suite |
| Safe autonomy | 0 irreversible actions without human approval, across all test runs |
| Useful documentation | Postmortem has timeline, root cause, actions taken, and a cost estimate with stated assumptions, for 100% of resolved incidents |
| Know its limits | Escalates (rather than loops or guesses) on scenarios designed to be unsolvable |

## 4. Design Principles

1. **State lives in structured data, not an LLM's context.** Incident state, hypotheses, and actions are DB rows, never a reconstructed chat log. Agents read this state and propose changes; the Orchestrator is the sole writer (§7.1).
2. **Every mutating action is tiered before it's taken.** The tier (read-only / reversible / irreversible / escalate) is checked by the Orchestrator before dispatch - never left to agent convention.
3. **Agents are stateless function callers**: a prompt + scoped tools + an LLM call, invoked by the Orchestrator with the relevant incident-state slice. No agent holds its own memory.
4. **Every external integration is a port with a swappable adapter.** Where a standard exists, the adapter implements it; otherwise Argus defines its own minimal interface and ships one adapter for the demo.
5. **Tests are a human-owned contract; code is what AI coding agents write against it.** This boundary is enforced structurally, not by convention.
6. **Everything is replayable.** Every external call (LLM, tool, MCP) is logged to `REPLAY_LOG` (§11.1) with enough detail to replay deterministically, so benchmark runs don't re-spend tokens or re-hit real systems.
7. **HTTP is a boundary concern, not a domain concern.** All external HTTP (webhook, incident read API, config API) is owned by one module, the Web Application (§7.9). Every other module - including the Orchestrator - is reached only as an in-process call.

## 5. Terminology

- **Argus** - the system itself: the Web Application (`argus_web`, its only HTTP surface, §7.9), the Orchestrator, sub-agents, Dashboard, Backoffice, and the tool servers connecting them to the outside world.
- **Target Service** - the app Argus watches: a real, small, runnable app in its own repo (`argus-target-service`), with real feature-flag checkpoints and a real test suite.
- **Target Environment** - everything the Target Service is wired to for a given deployment: flag backend, metrics backend, deployed-commit state. Self-hosted instances for the demo; nothing about Argus changes if these are swapped for real infra later (§12).
- **Scenario control** - a Target Service module that seeds a known incident cause (or none) and reactively decides whether the anomaly is resolved, used by both a demo UI and the benchmark harness (§15.2).

There's no separate "Sandbox" - what might informally be called that is just the Target Service plus its Target Environment, above.

## 6. System Architecture Overview

```mermaid
flowchart LR
    subgraph Real["Real external systems (configured, not hardcoded)"]
        SLK[Slack workspace]
        MAIL[Email recipients]
        GH[argus-target-service repo]
    end

    subgraph TargetEnv["Target Service + Target Environment (self-hosted for the demo)"]
        TS[Target Service<br/>business logic + scenario control + log query API]
        FLAGS[Flag backend<br/>Unleash]
        METRICS[Metrics backend<br/>Prometheus, fed by OTel Collector]
    end

    subgraph Argus["Argus"]
        WEB[argus_web]
        ORCH[Orchestrator - LangGraph]
        AGENTS[Sub-agents]
        MCPS[MCP tool servers]
        PG[(Postgres)]
        CHROMA[(Chroma)]
        VAULT[(HashiCorp Vault)]
        DASH[Dashboard]
        BO[Backoffice]
    end

    TS -->|webhook on alert| WEB
    WEB -->|invoke entrypoint, in-process| ORCH
    ORCH <--> AGENTS
    AGENTS <--> MCPS
    MCPS -->|HTTP: fetch log| TS
    MCPS <--> FLAGS
    MCPS <--> METRICS
    MCPS <--> GH
    MCPS <--> SLK
    MCPS -->|postmortem, exec summary| MAIL
    MCPS <--> CHROMA
    ORCH <--> PG
    MCPS -.->|read secrets| VAULT
    WEB <--> PG
    BO -.->|register config| WEB
    BO -.->|writes secrets| VAULT
    DASH --> WEB
```

**Backend:** `argus_web` as the single HTTP entrypoint (§7.9), the Orchestrator + sub-agents (in-process), Postgres for incident state, Chroma for long-term memory (Investigator + Postmortem agents, §11.2), and the Target Environment (flags, metrics, logs).

**Frontend:** a Dashboard (§7.7) plus a separate Backoffice admin surface (§7.8, §14) - both talk only to the Web Application, never to Postgres or Chroma directly.

## 7. Component Architecture

### 7.1 Orchestrator

A **LangGraph `StateGraph`** whose nodes are the sub-agents below; typed state (`IncidentState`, Pydantic) mirrors the Postgres schema (§11.1). Edges are conditional functions implementing the incident FSM (§10) - the graph defines legal transitions, the LLM picks among them. LangGraph's Postgres checkpointing gives incident-level durability for free: on restart it resumes from the last checkpoint.

No HTTP surface of its own; `argus_web` (§7.9) calls its entrypoint in-process after validating the webhook.

Responsibilities:
- Create the `Incident` row and invoke the graph, called by `argus_web`.
- Run the tier-gate node (§13) before any mutating tool call reaches an MCP server.
- Own the escalation decision (iteration counter + confidence threshold, both config).
- Trigger memory-lookup and log-query steps during investigation (§9).
- Sole writer of all incident-domain Postgres state (`Incident.status`, `HYPOTHESIS`, `ACTION`, `TIMELINE_EVENT`, §11.1) - agents propose changes, the Orchestrator persists them, pairing every state mutation with a `TIMELINE_EVENT` row (§10, §11.1).

### 7.2 Investigator agent

Runs the ReAct loop (§9, §8). Tools: memory read, metrics read, log read, and flag evaluation - all from `argus-read-mcp` (§12.1). Nothing from `argus-write-mcp` is bound to this node. Hints reach it as `TIMELINE_EVENT` rows (§11.1), written by the Orchestrator from hints the Communicator (§7.5) surfaces - not via direct Slack access.

### 7.3 Mitigation agent

Takes a confirmed/high-confidence hypothesis and proposes a reversible action: revert a flag or roll back a deployment (`push_revert_commit`) - both from `argus-write-mcp` (§12.1). Every action carries an undo descriptor, checked by the Orchestrator's gate node (§13). Afterward it re-queries the same metrics/logs and returns a `confirmed`/`refuted` verdict; the Orchestrator writes the resulting `ACTION.outcome` and `HYPOTHESIS` update (§7.1).

### 7.4 Code-Fix agent

Invoked when mitigation fails, or the scenario is bug/config-drift from the start. RAG over the Target Service repo to localize the bug, drafts a patch **plus a regression test**, opens a branch + PR via `argus-write-mcp`'s `open_pull_request`. Writing tests is normal for this agent - unrestricted except for one path: the **seeded ground-truth fixture test** that grades its patch (§15.2; §13 explains why it's protected). Its binding has **no `merge_pull_request` function at all** (tier enforcement by absence).

### 7.5 Communicator agent

Owns all Slack writes (creates the incident channel, posts structured status updates) and all outbound email (postmortem, exec summary) via `argus-write-mcp`, and is the only agent that reads Slack for human hints (via `argus-read-mcp`), converting them into a structured hint returned to the Orchestrator, which writes it as a `TIMELINE_EVENT` (§7.1).

### 7.6 Postmortem agent

Triggered once on transition into `resolved` or `escalated`. Consumes the full incident timeline and produces the postmortem: timeline, root cause, actions taken, cost estimate with assumptions, executive summary. Self-checks against a completeness checklist; retries once with missing fields flagged, then hands off regardless - it must terminate even on partial success. Afterward it writes a summary + embedding to long-term memory (§11.2).

### 7.7 Dashboard (`argus_dashboard`)

FastAPI + Jinja2/HTMX - server-rendered, no separate frontend build. Read-only: holds no incident-domain logic, never queries Postgres/Chroma directly, calls `argus_web`'s incident read API instead. Shows a live-incident view (hypothesis tree, action timeline, confidence over time, Slack/PR links) and a history view, both server-rendered; HTMX polling handles "live" updates.

### 7.8 Backoffice

A minimal admin UI, its own module, for editing `INTEGRATION_CONFIG` (§11.3): Slack workspace/channel routing, postmortem/exec-summary recipients, and the adapter configs (git, flags, metrics, logs) - per deployment environment. Each adapter config renders as a structured form matching that adapter's schema, not raw JSON. Secrets referenced here are never stored here (§14).

### 7.9 Web Application (`argus_web`)

The single HTTP-facing surface for Argus. No other module listens on a network port or parses HTTP; everything past its boundary is a plain function call.

Exposes three endpoint groups:
- **Alert webhook** - receives an alert POST, validates it, normalizes it into Argus's own `Alert` domain object, then calls the Orchestrator's entrypoint in-process with that object - never the raw payload (§25).
- **Incident read API** - serves the Dashboard: incident list, incident detail (hypothesis tree, action timeline, confidence-over-time), postmortem history, backed by direct Postgres queries (§11.1).
- **Configuration API** - serves the Backoffice: CRUD over `INTEGRATION_CONFIG` (§11.3).

`argus_web` holds no incident-domain logic - only request validation and response shaping. It calls the Orchestrator as an in-process dependency and reads/writes Postgres using schemas defined in `argus_core` (§20.2).

Normalizing the incoming alert is a boundary/controller responsibility, not domain logic: `argus_web` is the only place a vendor-specific payload shape may appear, and it never crosses into the Orchestrator or beyond. This is deliberately not the ports-and-adapters pattern (§12) - alert sources are inbound and open-ended, not a small set Argus chooses - see §25 for the intended mechanism.

## 8. Agentic Workflow Design

Several patterns, applied to different sub-problems:

- **ReAct** - the Investigator's core loop: observe (query logs/metrics/diff) → reason (form hypothesis) → act (query more, or hand off to Mitigation) → observe result. Detailed in §9.
- **RAG** - two uses: (1) Code-Fix (§7.4) retrieves relevant code/config to localize a bug; (2) the Investigator (§7.2) retrieves similar past incidents from long-term memory (§11.2) as the first step of its ReAct loop (§9), to seed hypotheses faster.
- **Multi-agent orchestration** - the Orchestrator (§7.1) delegates to specialized agents (Investigator, Mitigation, Code-Fix, Communicator, Postmortem), each with a narrow tool set and prompt, coordinated through shared incident state (§11.1).
- **Self-critique / reflection** - before any mitigation or escalation, the agent scores its own confidence against a threshold (§10); after a mitigation, it re-observes state and judges whether its hypothesis was confirmed or refuted (§7.3).

## 9. The Investigation Loop

The `investigating` phase (§10) looks like one node from outside, but runs a ReAct loop with a fixed first two steps:

```mermaid
flowchart TD
    A[Alert received, T0 known] --> B[Query Chroma for similar past incidents]
    B --> C[Query get_metrics_summary: aggregated summary for window]
    C --> D[Identify onset: earliest minute that left the baseline]
    D --> E[Query get_log_lines: window anchored on onset, reaching back before it]
    E --> F[Form/update hypothesis + confidence]
    F --> G{Confidence >= threshold?}
    G -->|Yes| H[Exit to mitigating]
    G -->|No, iterations remain| I[Refine query; widen window if onset is at its edge]
    I --> C
    G -->|No, iterations exhausted| J[Exit to escalated: insufficient evidence]
```

Step B seeds the *first* hypothesis before any log is read - "last 3 times we saw this pattern, it was a bad deploy." Steps C-E are the two-phase, windowed retrieval from §16, which keeps this loop from ever reading a full, unbounded log stream.

Widening is not left to the model's sense of dissatisfaction. Low self-reported confidence is one trigger, but an unreliable one - a model that formed a plausible hypothesis from too little evidence reports high confidence and never widens, because it cannot miss what it never saw. The deterministic trigger is structural: **if the earliest bucket in the window is already anomalous, the incident began before the window did**, so onset lies outside it and the next iteration must reach further back. Read literally, that condition says there is no calm stretch on screen to serve as a baseline - which is the same thing. That decision reads off the metrics summary the loop already has, not off the model's introspection.

"Anomalous" throughout means *relative to the service's own calm baseline in the same window* (§16), never a fixed error rate or latency. A service that normally sits at 8% errors is not permanently on fire, and one that normally sits at 0.5% should not have to reach 10% before Argus notices. An absolute threshold would also duplicate - and eventually contradict - the threshold the operator already configured in their own alerting tool, which is what fired the alert in the first place.

Exhaustion is a real outcome, not a formality. When the iteration budget or the maximum span runs out without a hypothesis clearing the threshold, the loop exits to `escalated` carrying "insufficient evidence" - never a hypothesis manufactured to fill the field. "Argus could not determine the cause" must be expressible and must be distinguishable from a confident answer, both because a human picking up the incident needs to know which one they were handed, and because a widening trigger built on confidence has nothing truthful to read otherwise.

## 10. Incident State Machine

```mermaid
stateDiagram-v2
    [*] --> investigating: webhook received
    investigating --> mitigating: hypothesis confidence >= threshold
    investigating --> escalated: confidence stays low after N iterations
    mitigating --> resolved: mitigation confirmed
    mitigating --> fixing: mitigation refuted / not applicable
    mitigating --> escalated: reversible actions exhausted, still unresolved
    fixing --> resolved: PR opened + target repo's test suite passes against it
    fixing --> escalated: no code-level fix found after N iterations
    resolved --> [*]: postmortem generated
    escalated --> [*]: postmortem generated (partial) + human paged
```

Confidence threshold for `investigating → mitigating`: **0.75**. Escalation trigger: **3 failed hypothesis iterations**. Both are named, environment-driven config - the first values to tune against benchmark results (§21).

Every transition is written as a paired `TimelineEvent` row, per the Orchestrator's single-writer rule (§7.1, §11.1).

## 11. Memory & Data Architecture

Argus needs two kinds of memory, backed by two different stores (§11.4): **episodic (per-incident) memory**, which stops the agent re-toggling a flag it already ruled out, and **long-term (cross-incident) memory**, which biases a new incident by how similar past ones were resolved.

### 11.1 Episodic / operational state (Postgres)

Structured state, not free-text - every graph node reads/writes this, never a reconstructed chat log:

```mermaid
erDiagram
    INCIDENT ||--o{ HYPOTHESIS : has
    INCIDENT ||--o{ ACTION : has
    INCIDENT ||--o{ TIMELINE_EVENT : has
    INCIDENT ||--o| POSTMORTEM : produces
    INCIDENT ||--o{ REPLAY_LOG : logs

    INCIDENT {
        uuid id PK
        jsonb alert_payload
        timestamp created_at
        enum status
        text slack_channel_id
        text pr_url
    }
    HYPOTHESIS {
        uuid id PK
        uuid incident_id FK
        text cause_type
        text description
        bool tested
        enum result
        float confidence
        timestamp created_at
    }
    ACTION {
        uuid id PK
        uuid incident_id FK
        text type
        text target
        bool reversible
        enum tier
        jsonb undo_descriptor
        enum outcome
        timestamp taken_at
        text approved_by
    }
    TIMELINE_EVENT {
        uuid id PK
        uuid incident_id FK
        timestamp ts
        text actor
        text action
        text result
        float confidence
    }
    POSTMORTEM {
        uuid id PK
        uuid incident_id FK
        text root_cause
        jsonb cost_estimate
        jsonb assumptions
        text executive_summary
        bool checklist_complete
    }
    REPLAY_LOG {
        uuid id PK
        uuid incident_id FK
        enum call_type
        text target
        jsonb request
        jsonb response
        int latency_ms
        numeric cost_usd
        timestamp ts
    }
```

Four tables rather than one JSON blob, because the eval metrics (§21) - wasted actions per incident, escalation precision/recall, root-cause accuracy - are counts, joins, and group-bys over structured fields (`tested`, `result`, `confidence`, `tier`). A relational schema already has that structure; free text or a blob would mean re-deriving it at query time.

Neither `HYPOTHESIS` nor `ACTION` has row history - both are mutated in place (`HYPOTHESIS.tested`/`.result`/`.confidence` as the ReAct loop refines, §9 step F; `ACTION.outcome` once a mitigation is confirmed/refuted, §7.3), written in the same transaction as a paired `TIMELINE_EVENT` row (single-writer rule, §7.1). Without that pairing, the confidence trajectory (Dashboard's "confidence over time," §7.7) and the incident narrative the Postmortem agent consumes (§7.6) would collapse to only their last value.

A fifth table, `REPLAY_LOG`, serves a different purpose: it's Argus's own eval infrastructure (Design Principle 6, §4), not incident-domain state, written at a different granularity - one row per LLM completion or MCP call. It's written inside the Orchestrator's process, from whichever agent node makes the call, via a shared instrumented client in `argus_core` - never by the MCP servers themselves, keeping them as pure as §13's MCP-server-boundary guardrail requires.

### 11.2 Long-term memory (Chroma)

One collection, one record per resolved incident:

```
{
  incident_id, embedding(summary_text),
  metadata: { alert_type, root_cause_category, resolution_type, resolved_at }
}
```

After each resolved incident, a summary + embedding is written here. On new incidents, the Investigator retrieves similar past ones to bias its first hypotheses (§9 step B) - this is the RAG component from §8, and a measurable factor in evaluation (§21: does retrieval speed up time-to-hypothesis on repeat scenario types?).

Retrieval filters by `alert_type` metadata first, then ranks by embedding similarity - coarse filter, fine ranking - which matters on a small corpus where pure semantic search alone would be noisy. Chroma runs embedded (in-process, persisted volume) for local dev, and as its own container with a persistent volume for the hosted demo.

### 11.3 Configuration (Postgres)

```
INTEGRATION_CONFIG {
    uuid id PK
    jsonb git_config           -- git tools: repo URL, branch, etc.
    jsonb flag_config          -- flag tools: adapter-specific (e.g. base URL)
    jsonb metrics_config       -- metrics tools: adapter-specific (e.g. base URL)
    jsonb log_config           -- log tools: adapter-specific (e.g. URL, shared path, or bucket/key)
    text slack_workspace_id
    text slack_default_channel_prefix
    jsonb postmortem_recipients      -- array of email addresses
    jsonb exec_summary_recipients    -- array of email addresses
    jsonb vault_secret_paths         -- references only, never secret values; see §14
    timestamp created_at
    timestamp updated_at
    text updated_by
}
```

The four `*_config` blobs are opaque to `argus_web`/Backoffice - each is parsed only by its own MCP server, per its own small schema (Design Principle 4, §4). This is what lets a second adapter (e.g. logs via shared filesystem or S3 instead of HTTP) be added without a schema migration. Edited by humans through the Backoffice, via `argus_web`'s configuration API (§7.9); changes rarely, and no agent ever writes to it.

### 11.4 Why relational for operational state

Free text or embeddings-only would fight several requirements above:

1. The eval metrics (§21) are inherently relational (§11.1).
2. The tier-gate node (§13) needs a deterministic answer to "does this action have a populated undo descriptor" every time - a vector store optimizes for semantic nearness, the wrong model for a safety-critical check.
3. Retries or a re-entrant graph run (e.g. after a restart, §7.1) can revisit the same incident; Postgres transactions give the Orchestrator's single-writer updates atomicity for free.
4. Follows Design Principle 1 (§4) - free-text state would just move "state an LLM has to re-parse" into a database instead of a chat log.

The one place a semantic store is the right tool is where it's already used: "have we seen an alert pattern like this before" has no relational answer - no foreign key from a new alert to similar past ones - which is exactly what Chroma's similarity search is for (§11.2). The design is a deliberate **hybrid**: Postgres for anything the system must count, join, or gate on deterministically; Chroma for anything it must recall by similarity.

## 12. Tool Integration Strategy: Ports and Adapters

Every external system (§7) is reached through a small internal interface (a "port") plus exactly one implementation for the demo (an "adapter"). Where a cross-vendor standard exists, the adapter implements it directly; otherwise the port is Argus's own minimal contract, so a second adapter could be added later without touching any agent's tool-calling code.

This applies to *outbound* integrations - systems Argus itself chooses to call, from a small set it controls. Alert ingestion is the opposite shape: an *inbound*, open-ended set of possible senders Argus doesn't get to pick. That's handled differently - see §25.

| Integration | Read/query standard | Write/mutate standard | Demo adapter |
|---|---|---|---|
| Feature flags | **Yes - OFREP** (OpenFeature Remote Evaluation Protocol): single/bulk flag evaluation, `ETag` caching, bearer-token auth | No - flag management (create/toggle/target) is vendor-specific (LaunchDarkly, Unleash, Flagsmith all differ) | **Unleash**, self-hosted: OFREP for reads, Unleash's admin REST API for the toggle/revert Mitigation performs |
| Deployment state / rollback | No | No - GitOps tools (ArgoCD, Flux) reconcile from Git with their own rollback commands; CI tools (GitHub Actions, CircleCI) each have their own trigger API; nothing shared | **Git revert + push**, GitOps-style, via `argus-write-mcp`. "Currently deployed" = current HEAD of a designated branch. Reuses the git tooling Code-Fix needs, at a different tool/tier (§13) |
| Logs | No - format and storage both vary per team, no interop standard | N/A - Argus never writes to Target Service logs | Target Service HTTP log endpoint (`GET /logs`, no params - returns full log), windowing/filtering done in `argus-read-mcp` itself (§16) |
| Metrics | **De facto - Prometheus-compatible query API** (PromQL); emission standardized via **OTLP**, but OTel isn't a backend itself | N/A - Argus only reads metrics | Target Service → OTel SDK → local **OTel Collector** → **Prometheus**; `argus-read-mcp` queries Prometheus's HTTP API |
| Chat (Slack) | N/A - one real vendor, no abstraction needed | - | Slack Web API - reads via `argus-read-mcp`, writes via `argus-write-mcp` |
| Email | SMTP is already the standard | - | `argus-write-mcp` via configured SMTP relay |
| Long-term memory | N/A - internal to Argus | - | Chroma directly - queries via `argus-read-mcp`, writes via `argus-write-mcp` |

### 12.1 MCP server topology

Tools are served by **two FastMCP servers, split by autonomy tier (§13)** - each a network-facing, independently deployable module (§20.1):

| Server | Exposes |
|---|---|
| `argus-read-mcp` | `get_log_lines(window, filters)` - fetches full log via HTTP, windows/filters/caps in the server itself (§16); `get_metrics_summary(window)` - Prometheus range query; OFREP flag evaluation; Chroma memory query; Slack channel/thread reads |
| `argus-write-mcp` | Unleash admin toggle + revert (reversible tier); `push_revert_commit` (Mitigation, reversible tier); `open_pull_request` (Code-Fix, no test-path writes) - deliberately **no `merge_pull_request` function exists**; Slack post/create-channel; email send via SMTP relay; Chroma memory write |

**Why split by tier, and not one server per integration.** The per-integration split (`logs-mcp`, `flags-mcp`, `git-mcp`, ...) is the convention for *publicly distributed* MCP servers, where each is installed independently by strangers. Argus owns all of its tools, so that reason doesn't apply, and seven processes would mean seven ports, healthchecks, images and startup orderings for a single team. What *does* justify a process boundary is a difference in **blast radius**: a process holding the GitHub PAT and the Unleash admin token is a fundamentally different risk object from one that can only read. That boundary is what makes §13's first guardrail structural rather than conventional - `argus-read-mcp` has no mutating code path and no credential that could authorize one, so no bug, prompt injection, or confused caller can talk it into writing. Splitting `logs` from `metrics` buys none of that: same tier, same failure domain, same (absent) secrets.

A single combined server would collapse that boundary; per-integration servers pay six extra processes for a partition that doesn't line up with any real risk difference. Two is the cut where the guardrail is real and the operational cost isn't.

Each agent's LangGraph node still binds only the individual tool functions its role needs - e.g. the Investigator (§7.2) binds the log, metrics, flag-read and memory-read functions from `argus-read-mcp`, and nothing from `argus-write-mcp`. Tool binding controls what an agent is *offered*; the server split controls what the process is *capable of* - only the second survives a compromised caller, which is why both exist.

**Each server is paired with a typed client package** (§20.1): `read_mcp_client`, `write_mcp_client`. A server is a deployed process; its client is a library installed into whichever agent calls it. The client exposes each tool as a real typed Python function (`get_log_lines(window, filters) -> list[str]`), rather than agents calling a generic `call_tool(name, **kwargs)` with a stringly-typed tool name and an untyped payload - so a mistyped tool name or argument is a static type error, not a runtime failure discovered in an incident. The generic streamable-HTTP transport underneath is shared, and lives once in `argus_core`.

## 13. Guardrails: Autonomy Tier Enforcement

Every action is tiered, which determines how much autonomy the agent has:

| Tier | Examples | Autonomy |
|---|---|---|
| Read-only | query logs, read Slack, read code | Fully autonomous |
| Reversible mitigation | toggle flag back, roll back deploy | Autonomous, but announced in Slack immediately + logged, with an explicit "undo" recorded |
| Irreversible / high blast radius | merge PR, Terraform apply | **Never autonomous.** Agent proposes; a human must approve |
| Give up / escalate | confidence stays below threshold after N iterations, or no reversible action resolves the alert | Autonomous - pages a human with full context, doesn't keep guessing |

Enforced redundantly at four layers:

| Layer | Mechanism |
|---|---|
| **MCP server boundary** | `argus-read-mcp` (§12.1) has no code path to mutate anything, and holds no credential that could authorize one - enforced at the server, not the caller. The tier split *is* the process split, so "read-only" is a property of the running process, not a convention. |
| **LangGraph node tool binding** | Each node's tool list is scoped at graph-definition time (§12.1). Code-Fix has no `merge_pull_request` function bound - because it doesn't exist anywhere in `argus-write-mcp`. |
| **Orchestrator gate node** | Before any `ACTION` with `tier=reversible` reaches its MCP call, a gate node requires a populated `undo_descriptor` (§11.1). `tier=irreversible` actions go straight to "notify human," never to a mutating call. |
| **Path-scoped write access** | `argus-write-mcp`'s git write functions are restricted per calling agent to specific file-path patterns. Code-Fix has normal write access across the repo (including its own regression tests) - except the seeded **ground-truth fixture test** for the active scenario, which protects **evaluation integrity**: without this, nothing would stop it from "passing" by weakening the grading test instead of fixing the bug. |

This four-layer redundancy is what lets the eval suite (§21) claim "zero irreversible actions without human approval" as a hard, testable metric.

## 14. Secrets and Configuration

**Secrets** (GitHub PAT, Slack bot token, Unleash admin token, SMTP credentials) live in **HashiCorp Vault**. Each MCP server authenticates to Vault at startup (or per-request, for short-lived leases) and reads only its own secret path. Every write credential belongs to `argus-write-mcp` alone; `argus-read-mcp` is issued none of them, and reads only what its read paths require (e.g. the OFREP evaluation token) - so the tier boundary in §12.1 is enforced by credential possession as well as by code, a fifth guardrail layer (§13).

**Non-secret registration data** (repo, Slack workspace, email recipients, flag/metrics/log endpoints) lives in `INTEGRATION_CONFIG` (§11.3), edited by a human through the Backoffice (§7.8). The table stores **Vault paths**, never secret values - the database itself can't leak secrets. This gives real secrets management (not hardcoded, not committed to git, editable without redeploy) without an identity platform like Keycloak.

**The Backoffice UI has no login.** Deliberate: it's a single-team, demo-scale admin surface, and adding auth (accounts, sessions, an identity provider) would spend course time on a concern orthogonal to the agent itself. It's not internet-exposed (§19) - access is via the same network boundary as the rest of the stack. Beyond a course project, Backoffice auth would need revisiting first.

## 15. The Target Service

### 15.1 What it is

A real, small, runnable app (e.g. a toy checkout/orders API) in its own repo, `argus-target-service`:

- **Business logic** - real endpoints with real feature-flag checkpoints, reading live flag state through an OFREP client pointed at Unleash (§12).
- **A log endpoint** - `GET /logs`, returns the full log with no filtering; windowing/capping logic lives in `argus-read-mcp` (§16), not the adapter.
- **A committed test suite**, including, per scenario, a **ground-truth fixture test** that fails against the seeded "bad" commit and passes once correctly patched. This is what Code-Fix's PRs are graded against, and the one file it can't modify (§13) - everything else, including new tests it adds, is unrestricted.
- **A scenario-control module**, under its own route prefix (e.g. `/demo-control/*`), structurally separate from business-logic routes so the business logic never needs to know a control panel exists.

Dedicated repo rather than a subfolder, because: GitHub's PR machinery is repo-scoped; the GitHub PAT can be scoped to exactly this one repo (least privilege - "Argus cannot touch its own codebase"); and the repo can be reset to a known commit between benchmark runs without touching Argus's own history.

### 15.2 Scenario control

One control API drives both a demo UI and the benchmark harness (headless, scripted, repeatable) - the same mechanism, which matters because the harness needs an honest, non-human-judged "resolved" signal:

- **Seeding a scenario** picks one or more root-cause types:
  - *Feature flag* - a flag set to its "bad" value.
  - *Bad deploy* - the deploy-record (HEAD of the designated branch) points at a seeded bad commit.
  - *Bug / config drift* - a seeded buggy commit is checked out; the repo's own test for it fails.
  - *No evidence* - nothing is seeded; nothing for Argus to find, forcing escalation.
  - *Multiple causes* - two of the above seeded together (e.g. bad flag + bad deploy), to test against false attribution to only one.
- **The log/metric generator reacts to live state, not a script.** It emits an anomaly matching the chosen root cause(s) *while the underlying condition(s) remain true*, and stops once all seeded conditions become false - regardless of who changed them or why. *Upstream dependency failure* has no Argus-controllable condition, so it never stops via Argus action - same "no honest resolution possible" property as *No evidence*, forcing escalation. This makes grading honest: revert the wrong flag or roll back the wrong thing, and the anomaly just keeps appearing, no separate "mark failed" logic needed.
- For bug/config-drift, "resolved" means **the repo's own test suite passes against Code-Fix's PR branch** - gradable immediately, independent of whether the PR is ever merged/redeployed (human-gated).
- The UI's start/force-stop button is a thin wrapper over this same control API - useful for demos (e.g. forcing escalation to show live), never a second source of truth.

### 15.3 The scenario types, end to end

| Scenario | Seeded state | Anomaly stops when | Correct Argus behavior |
|---|---|---|---|
| Feature flag | flag set to bad value | flag reverted to good value | toggle it back, confirm recovery |
| Bad deploy | deploy-record at bad commit | deploy-record points at previous commit | roll back via `argus-write-mcp` revert+push, confirm recovery |
| Bug / config drift | buggy commit checked out, a test fails against it | repo's test suite passes against Code-Fix's PR branch | open PR, human merges (out of Argus's autonomy) |
| No evidence | nothing correlated | never, automatically | exhaust reversible options, escalate |
| Upstream dependency failure | simulated downstream failure, no controllable cause | never, automatically | exhaust reversible options, escalate |
| Multiple causes | two of the above seeded together | all seeded conditions reverted | mitigate/fix each without false-attributing to only one |

## 16. Log and Metrics Windowing Strategy

Unbounded logs are slow and a poor use of context, so retrieval is windowed in time and staged in two phases.

**Time window.** The two phases anchor differently, because they cost differently. Metrics are pre-aggregated - one minute is four numbers - so the summary is fetched wide around the alert timestamp `T0`, spanning the full configured maximum. What it yields is the incident's *onset*: the first minute whose values break from baseline. Log lines are expensive, so they are fetched narrow and anchored on that onset rather than on `T0` - an alert fires when a threshold trips, which can be well after the incident began, so a window centred on `T0` can miss the causal change entirely. The cheap phase aims the expensive one.

Only the log window iterates. The metrics window is fixed at the configured maximum span and stays there - narrowing the cheap signal would hide the very onset it exists to find, and it is small enough that there is no reason to be stingy. The log window's initial lookback and lookahead are config, setting the *first* iteration only; later iterations choose their own (§9), bounded by that same maximum span the server enforces, so widening cannot degenerate into a full dump. "Now" keeps moving, so the upper bound is re-evaluated each iteration. The risk is asymmetric - too wide wastes context, too narrow loses the evidence silently - so these are tunable per benchmark scenario rather than hardcoded.

**Two-phase retrieval:**
1. `get_metrics_summary(window)` - a Prometheus range query, pre-aggregated buckets (per-minute error rate, p50/p95 latency, volume). Cheap, small, called first every iteration - re-read not to widen but to pick up the minutes that elapsed since the last one, which is how the loop notices the incident self-resolving or worsening while it investigates.
2. `get_log_lines(window, filters)` - raw lines for a window anchored on the onset the summary located.

**Why the log phase takes a window and not a list of anomalous minutes.** Scoping log retrieval to the minutes the summary flagged is wrong: it can only ever return symptoms. A cause is a point-in-time *event* - a flag flipped, a version deployed - and the error rate reacts to it a minute or more later, so the causal line sits in a minute that still looks perfectly healthy and would be excluded by exactly the filter meant to find it. Anomalous minutes tell you *when* to look; the window is what reaches back *before* them. This is also why the log window anchors on onset rather than on the loudest bucket.

Both live in `argus-read-mcp` (§12.1). Windowing and filtering are the server's responsibility, not the adapter's - the port only guarantees "return the log"; not every backend (e.g. a filesystem or S3 adapter) could support server-side filtering, so the logic stays centralized and adapter-agnostic.

The Investigator's default path (§9): aggregate → locate onset → read a narrow window anchored on it - never a full dump.

## 17. Model Selection Per Task

Free-tier terms and rate limits for hosted LLM APIs change often - verify current limits rather than treating the figures below as fixed.

| Task | Recommended model class | Why | Suggested free option |
|---|---|---|---|
| Investigator ReAct loop | Fast, cheap, large context | High call volume; digesting windowed excerpts, not deep reasoning | Gemini 2.5 Flash / Flash-Lite (no card required, large context) |
| Slack hint parsing | Fast, cheap | Short inputs, simple structured extraction, high volume | Groq free tier, open-weight model (e.g. Llama 3.3 70B) - low latency, generous cap |
| Slack/email writing | Mid-tier, strong instruction-following | Must fill a fixed template reliably | Gemini 2.5 Flash or Groq Llama 3.3 70B |
| Code-Fix (RAG + patch drafting) | Strongest free reasoning/code model | Patch is graded directly against the repo's test; low call volume, tighter cap tolerable | Gemini 2.5 Pro free tier |
| Postmortem + executive summary | Strong long-form writing | Graded against a completeness checklist; low call volume | Gemini 2.5 Pro free tier |

**Spreading load across providers** (e.g. Gemini for Investigator/Code-Fix/Postmortem, Groq for Slack) means a demo/benchmark burst doesn't exhaust one provider's cap and stall the pipeline. Both are reachable via thin, near-OpenAI-compatible SDKs, so model-per-node is a config value in `argus_core`'s LLM client factory, not a code change.

**If free-tier limits bottleneck benchmark runs** specifically, self-hosting an open-weight model (Llama 3.1/3.3, Qwen2.5) via Ollama or vLLM removes the rate-limit ceiling, at the cost of setup time and somewhat weaker Code-Fix/Postmortem quality.

## 18. Engineering Practices

### 18.1 Language and typing

Python throughout, including the Target Service, with **type hints mandatory, enforced in CI** via `mypy --strict` (or `pyright`). Pydantic models are the canonical representation of `IncidentState`, tool I/O schemas, and MCP tool signatures - runtime validation from the same types that give static-analysis coverage.

### 18.2 Test-driven development

Built test-first, per unit of work:
1. A human (evaluator or engineer, §22) writes the test(s) for the next unit of behavior.
2. Committed to the module's `tests/` directory.
3. An AI coding agent is given the failing test and writes the implementation - only the implementation.
4. Refactor with tests green.

### 18.3 AI coding agent test policy (Argus's own repo only)

A policy about **building Argus itself**, unrelated to what Argus does at runtime. **The AI coding agent used to implement Argus (e.g. Claude Code) may never create, edit, or delete test code under `argus/modules/*`, `argus/benchmark/*`, or root `argus/tests/*` (§20.2).** Proposed tests are presented as text/diff for a human to copy in manually - never written directly. This exists because the project is test-first (§18.2), and that division only holds if enforced.

Enforced in layers - narrower than originally envisioned:

| Layer | Mechanism |
|---|---|
| Instruction file | A committed `AGENTS.md` at the repo root states the policy for any coding agent; per-module `AGENTS.md` files land as each module is scaffolded. |
| Tool-level block (Claude Code) | `.claude/settings.json` + a `PreToolUse` hook hard-block Claude's `Write`/`Edit`/`NotebookEdit` from any `tests/` path (module-level and root) - the one real technical guarantee. Claude's `Bash`/`PowerShell` calls are **not** blocked, nor is any other AI tool or a human editing the repo directly - those rely on `AGENTS.md` and human vigilance only. |

This policy doesn't apply to Argus's own runtime Code-Fix agent (§7.4), and is unrelated to the Target Service repo rule (§13, §15.1) - different agent, different thing protected (evaluation integrity vs. development-process integrity).

### 18.4 Per-module CI

Each module under `modules/` has its own test suite and CI pipeline (lint → type-check → unit tests → build image), triggered on changes to its own path. For library-only modules (`argus_core`, the Orchestrator, each `agent_` package), the build-image step just validates a clean build - that image is never pushed or run standalone (§20.1). For network-facing modules, the same build produces the deployed image. Either way, this is what makes independent per-module versioning - and, for network-facing modules, independent deployment (§19, §20.1) - actually true.

## 19. Deployment Architecture

```mermaid
flowchart TB
    subgraph ArgusDeploy["Argus - Docker Compose / Railway"]
        WEB[argus_web service<br/>HTTP + Orchestrator + sub-agents, in-process]
        MCPS[argus-read-mcp,<br/>argus-write-mcp]
        PG[(Postgres)]
        CHROMA[(Chroma)]
        FE[argus_dashboard<br/>FastAPI + Jinja2/HTMX]
        BO[Backoffice]
    end
    subgraph TargetDeploy["Target Service + Target Environment - Docker Compose / Railway"]
        TS[Target Service]
        UNLEASH[Unleash]
        OTELCOL[OTel Collector]
        PROM[Prometheus]
    end
    VAULT[(HashiCorp Vault)]

    TS -->|webhook| WEB
    WEB --> MCPS
    MCPS -->|replay logs| PG
    MCPS --> CHROMA
    MCPS -->|OFREP + admin API| UNLEASH
    MCPS -->|PromQL| PROM
    MCPS -->|HTTP: fetch log| TS
    MCPS -->|Slack Web API| ExternalSlack[Slack]
    MCPS -->|SMTP| ExternalMail[Email]
    MCPS -->|Git ops| ExternalGH[GitHub]
    MCPS -.->|read secrets| VAULT
    BO -.->|write secrets| VAULT
    TS --> UNLEASH
    TS -->|OTLP| OTELCOL --> PROM
    FE --> WEB
    BO --> WEB
```

Only modules with their own network entrypoint - the Web Application, each MCP server, the Dashboard, the Backoffice (§20.1) - appear as separate boxes and ship their own Dockerfile; `docker-compose.yml` wires them together locally, and the same images deploy as separate Railway/Fly services for the hosted demo. `argus_core`, the Orchestrator, and the agent packages have no box here - they're installed inside the Web Application's image and run in-process within it.

The Target Environment deploys independently of Argus, reflecting that in a real deployment it would simply be swapped for actual production infrastructure.

## 20. Repository and Module Structure

### 20.1 Approach

A `uv` workspace covers `modules/*` (§20.2): the Orchestrator, Web Application, Dashboard, each sub-agent package, each MCP server, the Backoffice, and `argus_core` are each their own installable Python package with its own `pyproject.toml`, independently versioned. A root workspace `pyproject.toml` (`[tool.uv.workspace]`, members = `modules/*`) ties these together for local dev (`uv sync` installs everything editable) without forcing a shared version or deploy lifecycle; `uv`'s lockfile covers the whole workspace.

Independent *versioning* is true of every module; independent *deployment* is not - only modules with a network entrypoint (Web Application, MCP servers, Dashboard, Backoffice) ship a Dockerfile and deploy as their own service (§19). `argus_core`, the Orchestrator, each `agent_*` package, and each MCP *client* package have no deployment image; they're installed as dependencies into the Web Application, the only place they run (§7.1, §7.9). Their per-module CI (§18.4) still builds/tests them in isolation - what independent versioning buys even without independent deployment.

The benchmark harness sits outside the workspace entirely: its own `pyproject.toml`, not deployed as a service (§19) - a script/CLI run against an already-deployed Argus stack (§21.4), consuming `argus_core` schemas as a regular dependency.

### 20.2 Repository tree

```
argus/
├── pyproject.toml                 # workspace root: [tool.uv.workspace] members = ["modules/*"]
├── uv.lock
├── docker-compose.yml
├── AGENTS.md                      # AI coding agent test policy (§18.3), repo-root scope
├── docs/
│   └── spec-and-architecture.md   # this document
├── tests/                          # cross-module tests only, none touch a single module in isolation
│   ├── integration/                 # multiple modules interacting in-process
│   ├── contract/                    # an agent's exposed MCP tool schema still matches what the Orchestrator expects
│   └── e2e/                         # full stack via docker-compose, real chaos scenarios end-to-end
├── modules/
│   ├── argus_core/                  # shared Pydantic models, tool schemas, config/LLM client factory
│   ├── orchestrator/                # LangGraph graph, FSM, tier-gate node
│   ├── argus_web/                   # HTTP surface: alert webhook, incident read API, config API
│   ├── agent_investigator/
│   ├── agent_mitigation/
│   ├── agent_codefix/
│   ├── agent_communicator/
│   ├── agent_postmortem/
│   ├── read_mcp_server/             # argus-read-mcp: log, metrics, flag-eval, memory-query, Slack-read tools
│   ├── read_mcp_client/             # typed client for argus-read-mcp, imported by consuming agents
│   ├── write_mcp_server/            # argus-write-mcp: flag toggle, git revert/PR, Slack post, email, memory write
│   ├── write_mcp_client/            # typed client for argus-write-mcp, imported by consuming agents
│   ├── backoffice/                  # admin UI only - no HTTP of its own, calls argus_web's config API
│   └── argus_dashboard/             # FastAPI + Jinja2/HTMX read-only UI, calls argus_web's incident read API
└── benchmark/                       # scenario runner + evaluator harness, own pyproject.toml
    ├── scenarios/
    └── tests/
```

`argus-target-service` is a **separate repository entirely** - deliberately not part of this workspace (§15.1).

Every module under `modules/*` follows the same shape (`src/<pkg>/`, `tests/`, `Dockerfile`, `pyproject.toml`, its own `AGENTS.md`), which lets the CI gate in §18.4 be written once and applied uniformly via a matrix build.

Root `tests/` and `benchmark/` are separate concerns: `tests/` holds developer correctness tests spanning multiple modules (integration/contract/e2e - not covered by §18.4's per-module CI since they're cross-module); `benchmark/` is the scenario runner and evaluator (§21) grading Argus's behavior against seeded ground truth - an evaluation concern, not correctness testing. `benchmark/tests/` is the benchmark package's own unit tests, not to be confused with root `tests/`.

## 21. Evaluation & Benchmark Design

The hardest and most important part of the project - build it early, not last.

### 21.1 Benchmark suite

A library of scripted chaos scenarios injected into the Target Environment (§15.2), each with known ground truth:
1. Feature flag toggled → error spike (single cause, reversible)
2. Bad deployment → latency spike (single cause, reversible via rollback)
3. Config drift (e.g. wrong env var) → needs a code/config fix, not just rollback
4. Upstream dependency failure → not fixable by the agent; correct behavior is detect-and-escalate
5. Two simultaneous causes → tests whether the agent avoids false attribution to only one
6. Ambiguous alert, no clear cause in logs → tests escalation behavior
7. A Slack expert posts a correcting hint mid-incident → tests whether the agent incorporates human input

### 21.2 Metrics

- **Time-to-first-hypothesis**, **time-to-mitigation**, **time-to-resolution**
- **Root-cause accuracy** (does the cause match ground truth?)
- **Mitigation correctness** (right action for the actual cause)
- **Wasted actions** (incorrect hypotheses tested before the correct one)
- **False positive rate** (mitigating something that wasn't the cause)
- **Escalation precision/recall** (escalates exactly when it should?)
- **PR fix quality** (does the patch make the injected-bug test pass?)
- **Postmortem completeness** (timeline, root cause, cost estimate, assumptions present)

### 21.3 Cost/impact estimation methodology

Kept transparent and simple rather than falsely precise:
```
affected_users ≈ error_count_during_incident / baseline_error_rate_delta
customer_cost_estimate ≈ affected_users × avg_revenue_per_user × incident_duration_hours × impact_weight
internal_cost_estimate ≈ engineer_hours_involved × loaded_hourly_rate + agent_compute_cost
```
Label these clearly as **estimates with stated assumptions** in the postmortem - grade postmortems on whether assumptions are disclosed, not on numeric "accuracy" (there's no ground-truth dollar figure).

### 21.4 Evaluation harness (implementation)

A separate runner, not part of Argus, depending on:

1. **The scenario-control API on the Target Service** (§15.2) - seeds a root cause and holds ground truth, without Argus having access to it.
2. **Full replay logs** - every LLM and MCP call Argus makes is persisted (prompt, response, timestamp) keyed by `incident_id` (Design Principle 6, §4), so a benchmark run can be re-scored offline without re-invoking the LLM, and metrics like "wasted actions" or "escalation precision/recall" computed purely from stored data. These live in Postgres, in a dedicated `REPLAY_LOG` table separate from §11.1's incident-domain tables - an evaluation concern, deliberately excluded from that ER diagram.

The evaluator consumes the §11.1 Postgres tables directly, plus the Target Service's scenario ground truth - no separate export step.

## 22. Team Roles

| Role | Responsibilities |
|---|---|
| **Spec writer** | Owns this document, keeps scope/requirements current, writes the final report |
| **Product owner** | Prioritizes features vs. deadline, decides scope cuts, owns the demo narrative |
| **Evaluator** | Owns the benchmark suite (§21), runs evaluations, tracks metrics, writes the eval section of the report |
| **Engineer(s)** | Build the Orchestrator, Web Application, sub-agents, Target Environment APIs, memory layer, Slack/git integration, Dashboard, Backoffice, Docker/deployment |

(With a small team, one person can be spec writer + product owner, but keep evaluator a distinct hat - easy to let slide if the same person also builds features.)

## 23. Milestones

| # | Milestone | Deliverable |
|---|---|---|
| 1 | Spec finalized + architecture agreed | This document, reviewed by the team |
| 2 | Target Environment built | Mock logs/metrics/flags/deploy API + seeded git repo, fake but interface-realistic (§15) |
| 3 | Webhook → Web Application → Orchestrator → basic Investigator (ReAct loop) | Ingests an alert, produces a ranked hypothesis list from logs |
| 4 | Mitigation agent + episodic memory | Toggles flags/rolls back deploys, tracks what's been tried, avoids repeats |
| 5 | Slack integration | Reads hints, posts updates, creates/manages incident channel |
| 6 | Code-Fix agent (RAG + PR) | Given an unresolved-by-mitigation incident, finds relevant code and opens a draft PR |
| 7 | Long-term memory + retrieval | Past incidents retrievable and used to seed new investigations |
| 8 | Postmortem + executive summary generation | Full doc with timeline, root cause, cost estimate |
| 9 | Dashboard | Live incident view + history view, via the Web Application's read API (§7.9) |
| 10 | Benchmark suite + evaluation run | All §21.1 scenarios scripted and run, metrics collected |
| 11 | Dockerized deployment (Railway or similar) | One-command deploy, demo-ready |
| 12 | Final report + demo | Report covering all of the above, live or recorded demo |

Suggest running milestones 3-4 in parallel with 2 once basic Target Environment endpoints exist, rather than strictly sequential (§22).

## 24. Locked-In Design Decisions (Summary)

| Decision | Call | Why |
|---|---|---|
| Tool integration | MCP via FastMCP, servers split by autonomy tier, ports-and-adapters for non-standardized integrations (§12) | Satisfies the tools/MCP requirement properly, with real enforcement, not just tidiness - the read/write split makes §13's guardrail structural rather than procedural |
| Orchestration | LangGraph `StateGraph` over the incident FSM (§7.1, §10) | Conditional edges map directly to the state machine; built-in checkpointing removes bespoke resume logic |
| Web/API layer | Single Web Application module (`argus_web`) owns all HTTP; everything else called in-process (§7.9, §4) | Keeps transport concerns out of domain logic |
| Dashboard stack | FastAPI + Jinja2/HTMX, server-rendered, no separate JS build (§7.7) | Consistent with the Web Application's stack; no extra tooling for a read-only UI |
| Long-term memory | Chroma (§11.2) | Simple to run embedded for dev and as one container for the demo; no managed service needed |
| Secrets | HashiCorp Vault (§14) | Real secrets management without hardcoding or committing credentials |
| Feature flags | Unleash, OFREP for reads, Unleash admin API for writes (§12) | OFREP is a genuine adopted standard for reads; Unleash is a solid free adapter |
| Deploy/rollback | Git revert + push via `argus-write-mcp`, GitOps-style (§12) | No cross-vendor standard exists; reuses the git tooling Code-Fix already needs |
| Metrics | OTLP for emission, Prometheus-compatible query API for reads (§12) | OTLP is a real emission standard; Prometheus's query API is the closest thing to a de facto read standard |
| Logs | Target Service HTTP log endpoint, two-phase windowed retrieval (§16) | No standard exists; dumb full-log endpoint keeps windowing logic in `argus-read-mcp`, not the adapter, so other backends (filesystem, S3) stay swappable without filtering support |
| Confidence thresholds | Mitigation ≥ 0.75, escalate after 3 failed iterations (§10) | Empirically tunable, but named config from day one |
| Repository structure | `uv` workspace, one `pyproject.toml` per module (§20) | Independent versioning/deployment inside one repo |
| Testing discipline | TDD in Argus's own repo - the coding agent never writes/edits/deletes tests there (§18.3). Separately, the runtime Code-Fix agent writes tests freely in the Target Service repo, except one protected ground-truth fixture (§13) | Two distinct rules, two agents, two reasons: development process integrity vs. evaluation grading integrity |
| Model selection | Per-task model class, spread across free-tier providers (§17) | Matches call volume/reasoning needs and avoids one provider's rate limit stalling a demo |
| Backoffice access | No login (§14) | Deliberate scope limit for a single-team, non-internet-exposed, demo-scale admin surface |

## 25. Risks & Open Questions

- How much realism to build into the Target Environment (§15) vs. time spent on agent logic - timebox early. The interface must match a real environment's *kind* of APIs (§2); depth beyond that is a judgment call per component.
- LLM cost/latency of multiple agent hops per incident - consider caching and scenario replay for the benchmark suite (§21.4) so eval runs don't re-spend tokens, and load-test per-incident latency for the live demo path (webhook → resolution) specifically, not just the benchmark re-run path.
- How much of the two-phase windowing strategy (§16) generalizes if a future adapter swaps Prometheus or the Target Service's log endpoint for something else (CloudWatch, Elasticsearch, S3) - the ports-and-adapters design (§12) is meant to allow this, and the `jsonb` adapter-config shape (§11.3) is meant to make it schema-free, but no second adapter has been built to validate either claim.
- Alert ingestion needs to accept any reasonable third-party format (Grafana, Datadog, PagerDuty, a team's own webhook, ...) without a hand-written parser per vendor - this isn't ports-and-adapters (§12), since Argus doesn't choose who sends it alerts. The intended mechanism is LLM-based structured extraction at the `argus_web` boundary: a single, non-agentic LLM call that fills in the `Alert` domain model's schema from the raw payload, validated by the model itself - not a ReAct loop. Not yet built - the walking-skeleton change deliberately ships one hardcoded, deterministic parser (Grafana's format) to prove the graph/DB wiring first, without also taking on LLM-extraction-reliability risk in the same change. Generic ingestion is real, tracked future work, likely its own follow-up change once the skeleton lands.
- The confidence-threshold numbers in §10 (0.75 to mitigate, escalate after 3 failed iterations) are testable, not fixed - expect to tune them against real benchmark results (§21).
- Whether MCP (§12) vs. a simpler internal tool-calling layer was right for the course timeline - worth a retrospective once a few MCP servers are built; either satisfies the "Tools/MCP" requirement, but the tradeoff is easier to judge with real implementation experience.
- Alert ingestion needs to accept any reasonable third-party format
  (Grafana, Datadog, PagerDuty, a team's own webhook, ...) without a hand-written parser per vendor - this isn't ports-and-adapters (§12), since Argus doesn't choose who sends it alerts. The intended mechanism is LLM-based structured extraction at the `argus_web` boundary: a single, non-agentic LLM call that fills in the `Alert` domain model's schema from the raw payload, validated by the model itself - not a ReAct loop. Generic ingestion is real, tracked future work, likely its own follow-up change once the skeleton lands.


---

*Section numbers ("§N") always refer to sections of this document itself.*
