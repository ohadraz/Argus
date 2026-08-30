## Why

Argus's reasoning is currently invisible. Everything it decides - which candidates it ranked, which one it acted on, what the verdict was, why it moved to the next - exists only as Postgres rows and log lines, so the one question an audience asks first ("what did it actually do?") is answered by a database client. The shop has an operator console; the agent watching it has none.

This is also the half of the demo that is missing. The Target Service's console shows the incident from outside - flags moving, error rate falling - and that is deliberately the shop's view, which does not know it is being watched. Nothing yet shows the inside.

## What Changes

- **`argus_web` gains the incident read API** it was always specified to expose (§7.9): incident list, incident detail (ranked candidates, attempts, action timeline, status transitions), and the evidence behind each - backed by direct Postgres queries through the existing repositories.
- **`argus_web` also serves the view itself** - server-rendered Jinja2/HTMX, no frontend build, no second process. This is a deliberate departure from the Dashboard as a separate module (§7.7), taken because Argus is a demo that has to be *started* in front of an audience and a second service is a second thing to go wrong. The read API stays a real HTTP surface, because the page consumes it rather than reaching past it.
- **A live incident view**: the walk as it happens - each candidate in rank order, whether it was tried, the action taken, whether it was confirmed or refuted, and the undo. HTMX polling for "live", at the same cadence the shop's own console refreshes.
- **A history view**: past incidents, their outcome, and their postmortem.
- **The evidence stays attached to the claim**: log lines and metric departures render against the hypothesis that cited them, rather than as a separate dump a reader has to correlate by timestamp.
- Argus gets an identity of its own: an eye favicon, and README artwork.
- **§7.7 and §7.9 of `docs/spec-and-architecture.md` are rewritten** to describe this arrangement as the intent - the spec is a specification, not a changelog.

Not in scope: the Backoffice (§7.8), any write or approval action from the UI, and authentication.

## Capabilities

### New Capabilities
- `incident-read-api`: what `argus_web` serves about incidents - list, detail, timeline, evidence, postmortems - and the guarantees that it is read-only and shapes responses without owning domain logic.
- `incident-dashboard`: the server-rendered view of a live and a past incident, what it must show about a walk, and its constraint of reading only through the read API rather than the database.

### Modified Capabilities
<!-- None. The incident's own lifecycle and the walk are unchanged: this change
     only reads what they already record. -->

## Impact

- **`modules/argus_web/`** - grows from a single webhook route to two endpoint groups plus templates and static assets; still the only module that listens on a port (§4 principle 7), now more so.
- **`orchestrator/repository/`** - read paths may need query methods that do not exist yet (incidents by recency, a walk's attempts in order). Naming follows the repository convention: bare `get()` only for primary-key lookups.
- **`action` has no `hypothesis_id`** - so tying an action row to the candidate it came from is string matching today. The timeline view is the first consumer that makes that gap visible, and may be the reason to close it.
- **`docs/spec-and-architecture.md`** - §7.7 and §7.9 rewritten; `argus_dashboard` stops being a planned module.
- **`docker-compose.yml`** - no new service; `argus_web` gains a published port in the profiles that lacked one.
- No change to the Orchestrator, the agents, the MCP servers, or the recordings.
