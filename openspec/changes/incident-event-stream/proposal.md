## Why

Argus's page can show what an incident *concluded* - candidates, verdicts, transitions - and almost nothing about how it got there. Which metric window the Investigator asked for, what came back, which minute it called the onset, which log lines it read, when it widened and why: all of it happens in-process and is written down nowhere, so the story of a live incident cannot be told without inventing it at read time. That is what stands between a page that reports outcomes and a screen somebody can watch Argus think on, and it becomes spec §4 principle 8: what Argus did is recorded as it happens.

## What Changes

- Components publish typed **incident events** as things happen - an agent invoked, a retrieval requested and what it returned, an onset detected, a hypothesis formed, an action taken, a status changed. A publisher is injected the way every other collaborator in this codebase is; a component says what it did and does not know who listens.
- A **subscriber persists the stream** per incident, in order, as an append-only table. This keeps the single-writer rule intact - the subscriber is the writer - and is what lets an incident's story survive a reload and be read back afterwards.
- Transport stays a swappable detail: in-process dispatch now, a broker later, without touching a publisher or a reader.
- `argus_web` gains a **live view as its front door**: empty until an alert arrives, then a header (alert, service, when it started, the status pulsing while it runs, elapsed time) over a narration of what Argus is doing, with the evidence it read - metrics, log lines, flag history, production changes - gathered into a table per channel below the narration, linked to from the lines that name a row in them, and coloured the way the Target Service's own console colours them.
- **Navigation**: the history moves behind a menu rather than being the front door.
- The alert being acknowledged is published as an **event**, not made into a status: it is a thing that happened, the narration's first line, and the incident's status machine (spec §10) is left exactly as it is.

## Capabilities

### New Capabilities
- `incident-event-stream`: what Argus publishes as it works, what is recorded, and the guarantees a reader gets - ordering, completeness, and that publishing never alters what an agent decides.
- `live-incident-view`: Argus's front door - a live narration of the incident currently running, with the evidence it read shown as it read it.

### Modified Capabilities
- `incident-dashboard`: the view's front door becomes the live page and the history moves behind navigation; the existing pages keep their requirements.

## Impact

- `argus_core`: the event models and the publisher Protocol. `IncidentStatus` is untouched, and so is every test that asserts on it.
- `agent_investigator`, `agent_mitigation`, the Orchestrator graph: each publishes what it does, through an injected publisher with a default that reaches the subscriber.
- `orchestrator/repository`: a new append-only event table and its read side; the schema's `CREATE TABLE` grows, and there is no migration - every stack starts from `down -v`.
- `argus_web`: the live page, its polled fragment, the navigation, and the metric/log table rendering.
- The recordings and e2e suites are unaffected in what they assert; an incident that publishes nothing still runs.
