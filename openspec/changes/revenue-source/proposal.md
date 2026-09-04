## Why

The Postmortem's loss estimate needs one figure nothing answers: what the shop
took over a window. The `Revenue` port exists and is wired to a function
returning `None`, so every postmortem published so far carries an absent
estimate with "no revenue source is configured" as its reason - the honest
answer, and the least useful one.

A payment provider answers in the currencies it was paid in, and a shop paid in
two of them has no total. So a source of revenue is only half the change: the
other half is one rate, from a real rate provider, and a stated assumption
saying which rate was used.

## What Changes

- An adapter satisfying the `Revenue` port, built on the **real Stripe SDK**,
  with `base_addresses` aimed by configuration. Against the demo it points at
  the Target Service's Stripe-shaped endpoint; against a real account it points
  nowhere and the SDK's own default applies. The arrangement the Anthropic
  adapter has with its double, for the same reason: a vendor client exercised
  only against a hand-written fake proves nothing about the vendor.
- The Target Service grows that endpoint. It is a shop, it already simulates
  checkouts, and it already stands in for Argo CD the same way.
- Revenue is **succeeded charges less refunds** in the window. A refund taken
  during an outage is part of what the outage cost.
- The adapter sums **per currency** and reports what it found, because that is
  what the provider said. Reducing several currencies to one figure is not the
  adapter's business.
- A rate adapter against **Frankfurter** (ECB reference rates, no credential),
  fetched on first use and cached in Postgres by date. ECB fixes once per
  business day, so a day-keyed cache loses nothing.
- A **reporting currency** setting, defaulting to USD. The estimate converts to
  it and records the rate and its date in the postmortem's assumptions - a rate
  from yesterday's fix, when today's cannot be fetched, is said so rather than
  passed off as current.
- The `Revenue` port answers with an amount **and its currency** rather than a
  bare `Decimal`, which today assumes USD without saying so.
- **No MCP hop.** Every other external read sits behind the read tier because
  an agent chooses to call it; the Postmortem is not agentic and reads nothing
  by choice, so both of these are plain adapters the orchestrator wires into
  the ports. The read tier stays what it is: the tools an agent may use.
- Nothing that cannot be read becomes a zero. An unreachable payment provider,
  or a currency with no rate anywhere, leaves the estimate absent with the
  reason stated - the distinction the ports were defined for, now with real
  sources behind them.

## Capabilities

### New Capabilities
- `revenue-source`: what the revenue adapter answers and how it fails - an
  amount per currency over a window, succeeded charges less refunds, a real
  vendor client aimed by configuration, and no credential or provider name
  reaching the agent that consumes it.
- `exchange-rate-source`: the rate a figure is converted at - one provider's
  published reference rate, cached by the day it was fixed, falling back to the
  most recent rate held when the provider cannot be reached, and disclosed with
  its date wherever a converted figure appears.

### Modified Capabilities
- `postmortem-evidence-sources`: the revenue port answers with an amount and
  its currency rather than an amount alone.
- `incident-postmortem`: the loss estimate names the currency it is stated in,
  and the assumptions carry the rate and the date of the rate for every
  currency converted.

## Impact

- New module `modules/revenue_source/` - the Stripe client, the window query,
  the per-currency sum.
- New module `modules/exchange_rate_source/` - the Frankfurter client, the
  day-keyed cache, the fallback to the newest rate held.
- `modules/agent_postmortem/` - `Revenue` answers with an amount and a
  currency; `estimate.py` reduces several currencies to the reporting one;
  the assumptions gain the rate and its date.
- `modules/orchestrator/` - `postmortem.py` wires both adapters in place of the
  functions returning `None`, and depends on both new modules.
- `argus_core.config` - the Stripe key and base address, the rate provider's
  base URL, the reporting currency. The key absent by default, so a deployment
  cannot ship a working credential by accident.
- `argus_core.schema` - a table holding one day's rates. `CREATE TABLE` only.
- `Argus-Demo-Target-App` - a Stripe-shaped charges endpoint over the checkouts
  the shop already simulates, taking a minority of them in a second currency so
  that conversion is exercised by something other than a unit test.
- New third-party dependency: `stripe`. First vendor SDK besides `anthropic`.
- No new process and no new container: both adapters are libraries, and the
  endpoint lives in a service the stack already runs.
