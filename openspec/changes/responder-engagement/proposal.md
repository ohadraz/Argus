## Why

The Postmortem's `Engagement` port exists and is wired to a function returning
`None`, so every postmortem published so far reports no `engineer_minutes` at
all. The response is the one cost Argus is in a position to observe directly -
it watched the incident from the moment the alert arrived - and reporting
nothing about it leaves the document saying what the incident cost the business
and nothing about what it cost the people.

Revenue is now read from a real payment provider through the vendor's own SDK,
aimed by configuration at the demo shop. On-call is the same shape of problem
with the same shape of answer, and PagerDuty publishes a first-party Python
client that takes a `base_url`.

## What Changes

- An adapter satisfying the `Engagement` port, built on the **real PagerDuty
  SDK** (`pagerduty`, the first-party client that replaced `pdpyras`), with
  `base_url` aimed by configuration. Against the demo it points at the Target
  Service's PagerDuty-shaped endpoints; against a real account it points at
  PagerDuty and the same code path runs.
- The Target Service grows those endpoints. It already stands in for Stripe and
  for Argo CD, and an incident it seeded is an incident someone was paged for.
- Engagement is **when a person first acknowledged the incident until the
  incident resolved**, and **how many distinct people acknowledged it**. Both
  are read from the incident's acknowledgements rather than from anything the
  model says.
- The responder's **job title** is read where PagerDuty publishes it - on the
  user, one call behind the acknowledgement - and carried on the answer. It
  costs one request, it is what a later change needs in order to price the
  minutes, and a title in the document already tells a reader more than a count
  does.
- An unacknowledged incident answers **nobody engaged**, which is not the same
  as an unreadable source. A machine-resolved incident nobody looked at is a
  real answer and a true one.
- **No MCP hop**, for the reason revenue has none: the read tier is the tools an
  agent may choose to call, and the Postmortem is not agentic. This is an
  adapter the orchestrator wires into a port.

## Capabilities

### New Capabilities
- `engagement-source`: what the on-call adapter answers and how it fails - the
  minutes a person was engaged, how many people were, the title each held, a
  real vendor client aimed by configuration, and no provider name or credential
  reaching the agent that consumes it.

### Modified Capabilities
- `postmortem-evidence-sources`: the engagement port answers the responders'
  titles alongside the minutes and the count.
- `incident-postmortem`: the reported response time is the acknowledged span
  rather than the whole incident, and an incident nobody acknowledged reports
  no engagement rather than an absent source.

## Impact

- New module `modules/oncall_source/` - the PagerDuty client, the incident's
  acknowledgements, the user lookup behind them.
- `modules/agent_postmortem/` - `EngagementAnswer` carries the responders'
  titles; the document reports them.
- `modules/orchestrator/` - `postmortem.py` wires the adapter in place of
  `_no_engagement_source`, and depends on the new module.
- `argus_core.config` - the PagerDuty API key and base URL. The key absent by
  default, so a deployment cannot ship a working credential by accident.
- `Argus-Demo-Target-App` - PagerDuty-shaped incident and user endpoints over
  the scenario it already seeds, acknowledged by an authored responder.
- New third-party dependency: `pagerduty`. Third vendor SDK, after `anthropic`
  and `stripe`.
- No new process and no new container: the adapter is a library, and the
  endpoints live in a service the stack already runs.
