## Why

A postmortem reports how many people responded, what they were, and how many
person-minutes they spent - and stops there. What those minutes were worth is
the other half of an incident's cost, and it is the half an exec summary is
usually written to answer. The minutes are already measured; only a rate is
missing.

## What Changes

- The postmortem reports what the response cost: each responder's minutes at
  the pay band their title sits in, summed. A headline figure from the band's
  midpoint, with the min-max range beside it, so a reader sees both the number
  and how wide the number is.
- The rate comes from an HR source's own pay bands - a range attached to a
  compensation level that job titles are assigned to - never from an
  individual's compensation. The document goes on recording titles and never
  names.
- A title the bands do not cover leaves the figure absent, naming the title.
  Never zero, and never a subtotal over the responders who happened to match.
- The annual band becomes a per-minute rate through a configured working-hours
  year, defaulting to 2080, which the document states as an assumption.
- A BambooHR double stands in for the HR source in dev, `e2e_replay` and CI,
  and the Target Environment seeds the bands it serves.

## Capabilities

### New Capabilities
- `responder-rate-source`: where a title's pay band comes from, what it means
  for a title the bands do not cover, and what the deployment never reads.
- `responder-cost`: the cost of an incident's person-minutes, its range, and
  the assumptions it rests on.

### Modified Capabilities
- `incident-postmortem`: the document carries what the response cost beside the
  minutes it already carries.

## Impact

- New `modules/responder_rate_source`, beside `revenue_source`,
  `exchange_rate_source` and `oncall_source`.
- `modules/agent_postmortem`: the figure, its range, and its assumption lines.
- `modules/argus_core.config`: the HR source's base URL and credential, the
  working-hours year, and `.env.example`.
- `modules/orchestrator`: the `postmortem` row gains the figures.
- `Argus-Demo-Target-App`: pay bands and their job-title assignments, served in
  the HR API's own wire shape, seeded per scenario.
- `noxfile.py` and the compose stack: the double joins the local services.
