## Context

The Postmortem computes its loss estimate as
`revenue_per_hour x duration_hours x error_rate_delta x impact_weight`. Three
terms are measured; the fourth is the model's disclosed judgment. The first
term has no source: `agent_postmortem.sources.Revenue` is a port, and
`orchestrator/postmortem.py` satisfies it with a function returning `None`, so
the estimate has never been anything but absent.

A payment provider answers in the currencies it was paid in. Stripe holds no
cross-currency total, and a shop taking euros and dollars has two amounts and
no sum. The port's `Decimal` return therefore assumes a single currency without
ever saying which - which is why the rate half of this change is not a separate
concern that could be deferred: without it, the first multi-currency shop makes
the estimate silently wrong rather than absent.

The postmortem is not agentic. It retrieves nothing by choice, drives no tool
loop, and every figure it publishes is computed before the model is asked for
prose. That is what settles where these adapters live.

## Goals / Non-Goals

**Goals:**

- A real revenue figure on the postmortem page, from a real vendor SDK.
- Several currencies reduced to one stated figure, at a published rate, with
  the rate and its date disclosed.
- Every failure of either source leaving the estimate *absent with a reason*,
  never zero and never converted at an invented rate.
- The demo stack answering both without a credential, a network call to a paid
  service, or a container that did not exist before.

**Non-Goals:**

- Settlement accuracy. This is a disclosed estimate, not a ledger, and the
  spec grades postmortems on whether assumptions are stated rather than on the
  figure.
- Per-charge conversion through Stripe's `balance_transaction`, which would be
  one extra fetch per charge to buy accuracy nothing here needs.
- A scheduled refresh of rates. See the cache decision.
- Attributing revenue to the affected path. That is what `impact_weight` is,
  and it stays the model's.

## Decisions

### Plain adapters, not MCP tools

Every other external read in Argus sits in `read_mcp_server/` -
`argocd.py`, `flags.py`, `retrieval.py` - and reaches an agent as a typed
client function. Those exist because an *agent* chooses to call them mid-loop;
the MCP boundary is what makes "what an agent may read" a property of a running
process rather than a convention.

Nothing here is chosen by a model. The orchestrator gathers the postmortem's
evidence before the single model call, so routing these reads through MCP would
buy an HTTP hop, a tool schema and a server round trip for a function call with
no caller that can decide anything.

*Alternative considered:* `read_mcp_server/revenue.py`, for consistency and to
keep a vendor credential behind the read tier. Rejected: the credential is held
by whichever process makes the call either way, and diluting the read tier into
"external reads in general" costs the one thing the split was for.

### The real Stripe SDK, aimed by configuration

`StripeClient(api_key, base_addresses={"api": ...})` - a documented TypedDict on
the v8+ client - points the vendor's own library at the Target Service instead
of `api.stripe.com`. The demo therefore exercises the same code path a real
account would: the SDK's request building, its pagination, its object model.

This is the arrangement `argus_core.llm.adapters.anthropic_adapter` already has
with `anthropic_double`, and it exists for the reason stated there: an adapter
tested only against a fake written by the same hand proves the fake, not the
adapter.

*Alternative considered:* a hand-rolled HTTP client against Stripe's REST API.
Rejected - it would be a second implementation of pagination and object shapes
that the SDK already gets right, and it could not be run against a real account
without rewriting.

### Revenue is succeeded charges less refunds, summed per currency

A refund issued during an outage is part of what the outage cost, so it is
subtracted rather than ignored. Failed and pending charges are not revenue and
are excluded.

The adapter returns what the provider said - an amount per currency - and no
more. Reducing that to one figure needs a rate, a policy about which currency
to state, and an assumption to disclose; all three belong to the agent that
publishes the figure, not to the thing that read the provider.

### Rates from Frankfurter, cached in Postgres by date

Frankfurter serves ECB reference rates, needs no credential, and answers a
whole table in one call (`/v2/rates?base=USD`, ~10KB, measured at 50-260ms). ECB
fixes once per business day, so a rate cannot change more than once a day and a
day-keyed cache loses nothing.

Fetched on first use rather than on a schedule. A scheduled job is a second
moving part that can fail overnight, and when it does it leaves exactly what an
on-demand fetch leaves: whatever the cache already holds. The cache is
therefore *kept*, not emptied - when today's fetch fails, the newest rate held
is used and its date is disclosed.

*Alternative considered:* asking the model to convert. Rejected on three
counts: it has no current rates, a remembered one would be stated as fact, and
the agent's whole design is that the model supplies prose and exactly one
number - `impact_weight`. A second number from the model is what the answer
checker exists to catch.

### The reporting currency is a setting, defaulting to USD

Reading it from the Stripe account's settlement currency would be one more call
and would not work against the demo, which has no account. A setting is one
line, and the estimate says which currency it is stated in either way.

### A table for rates, created rather than altered

`CREATE TABLE` in `argus_core.schema`, no `ALTER`: the dev database is
disposable and the schema is stated in one place. One row per currency per
date, so a fetch is one upsert per currency and a lookup is a primary-key read.

## Risks / Trade-offs

- **The rate provider is down and the cache is empty** (a first-ever run during
  an outage) → the estimate is absent with that reason, exactly as an
  unreachable payment provider already behaves. No fabricated rate, no zero.
- **A stale rate is used without the reader noticing** → the rate's date is
  written into the assumptions, and the document already publishes assumptions
  as the thing it is graded on.
- **ECB publishes no rate for a currency the shop was paid in** → that
  currency's takings are excluded and the exclusion is stated, rather than the
  whole estimate being lost.
- **The demo's Stripe endpoint drifts from what the SDK expects** → it is
  exercised through the real SDK by the e2e stack, so a shape the library
  cannot parse fails a test rather than a demo.
- **`stripe` is a new dependency** → one vendor SDK, in one module, behind a
  port that already exists. Nothing above `revenue_source` learns the provider's
  name.

## Open Questions

- Whether the reporting currency should also govern how the incident page
  renders figures, or only the postmortem row. Deferred to whoever next touches
  the page; nothing in this change reads it there.
