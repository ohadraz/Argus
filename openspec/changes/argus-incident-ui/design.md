## Context

`argus_web` is 32 lines and one route: the alert webhook. Everything Argus decides afterwards lands in Postgres - `incident`, `hypothesis`, `action`, `timeline_event`, `postmortem` - and is read today only with a database client. The repositories that own those tables already exist under `orchestrator/repository/`, but they were written for the graph's needs, so their read side is thin: `incidents.get`, `hypotheses.get_latest_by_incident`, `timeline.get_timeline_events`, `postmortems.get_by_incident`, and for actions, nothing at all.

The Target Service already has an operator console, and it is deliberately the *shop's* view - it does not know it is being watched. This change builds the other half.

Two constraints come from the spec rather than from taste. HTTP is a boundary concern owned by one module (§4 principle 7, §7.9), so the page cannot be its own service reaching Postgres. And `argus_web` holds no incident-domain logic (§7.9), so it may shape what the repositories return and nothing more.

## Goals / Non-Goals

**Goals:**
- An incident's walk is legible to somebody who was not watching it happen: every ranked candidate, what was tried, what the verdict was, what was undone.
- A running incident can be watched live, beside the shop's console, without a manual refresh.
- Evidence stays attached to the claim that cited it.
- One process to start. A demo has an audience standing in front of it.

**Non-Goals:**
- The Backoffice (§7.8) and `INTEGRATION_CONFIG` editing.
- Any write, approval or re-run triggered from the page. Irreversible actions require human approval *in the code path*, and a button is not that.
- Authentication, multi-tenancy, or anything about who is looking.
- Charting confidence over time. The walk is the story; a sparkline is decoration until the walk reads clearly.

## Decisions

### The view is served by `argus_web`, not by a separate `argus_dashboard`

§7.7 planned a separate module calling a read API over HTTP. Serving the view from `argus_web` costs one deviation and buys one process.

The reason is the demo: a second service is a second thing to start, a second thing to fail, and a second port to explain. The boundary that mattered - that HTTP lives in exactly one module - is *strengthened* by this, not weakened.

What is genuinely lost is the enforcement that the page cannot reach past a read API into Postgres, which a process boundary gave for free. That is replaced by a structural rule: the page's handlers read through the repositories that own the tables and the view builders beside them, and never write SQL of their own. It is a convention, and conventions are weaker than boundaries - but the alternative convention (remembering to start two services) fails more often.

There is no JSON API under it, either. §7.7's split made one necessary because a second process had to talk to the first; with one process the page is the only reader there is, and an endpoint with no client is a second surface to keep honest for nobody's benefit.

`docs/spec-and-architecture.md` §7.7 and §7.9 are rewritten to describe this as the intent, per the spec-doc convention: a specification, not a changelog.

**Alternative considered:** keep the split and add a compose service. Rejected on demo cost, not on architecture - it is the better architecture.

### Server-rendered Jinja2 + HTMX, no build step

Matches the shop's console (one page, no framework, no bundler) and §7.7's own choice. A compiled frontend would add a toolchain to a Python workspace for one page. HTMX polling gives "live" for the cost of an attribute.

**Alternative considered:** a JSON API plus a static page doing its own `fetch`, exactly as the shop's console does. Genuinely simpler in some ways, and worth reaching for if templating starts to hurt.

### Polling, at the shop console's cadence, and it stops

The shop's console polls every two seconds and that reads as live. The same cadence here means the two screens move together during a demo, which is the point of watching them side by side.

Polling stops once the incident reaches a terminal status: a finished incident's page that keeps asking is a page that will still be asking tomorrow.

### Read paths get repository methods, not SQL in `argus_web`

`argus_web` shapes responses; it does not know SQL about incidents. Three reads do not exist yet and belong in the repositories:

- incidents, newest first, for the history view;
- every hypothesis for an incident in rank order - `get_latest_by_incident` returns one, which is exactly the shape that hides a walk;
- the actions taken for an incident, in order.

Naming follows the repository convention: bare `get()` is reserved for primary-key lookups, so these are `get_*` names that say what they look up by.

### An action is tied to its candidate by the key it carries

`action.hypothesis_id` names the candidate an action was taken for, written while the node taking it still holds that candidate. A reader follows the key, and no consumer has to match on the flag the action and the hypothesis happen to share - a match that is only ever right because the walk refuses to act on one subject twice, which is a rule about not retrying a move rather than about identity.

The column is nullable, so an action can still arrive attributed to nothing. Such an attempt is shown on its own rather than dropped: it is a change Argus made to the service, and losing it would leave the account of what happened incomplete.

**Alternative considered:** match on subject, and leave the key for later. Rejected - it makes this view the second consumer of an accidental invariant, and the association is the one thing the view exists to show.

### The page renders untried candidates too

A walk that resolved on its second candidate had a third and fourth it never reached. Rendering only what was tried would make every incident look like a two-step process, and would hide the difference between "confident and right" and "ran out of options".

## Risks / Trade-offs

- **The page can quietly start querying Postgres directly**, since nothing but convention stops it now → keep the read functions the single entry point, and let the read-only requirement be the thing tests assert.
- **Polling every two seconds per open tab**, against Postgres → the reads are per-incident and small, and the audience is one room. If it ever matters, the incident detail response is one query away from being cached per status.
- **A live incident renders partial state** - a candidate mid-verification, an action with no verdict yet → treat "no verdict yet" as a state to display rather than an absence to hide, the same way the shop's console shows a minute in progress.
- **Deviating from §7.7 makes the spec doc wrong until it is rewritten** → rewriting it is a task in this change, not a follow-up.
- **An action can name no candidate**, since `action.hypothesis_id` is nullable → it is shown as an attempt attributed to nothing rather than silently dropped, so the account of what Argus changed stays complete either way.

## Open Questions

- Should the history view page, or is "every incident this stack has run" small enough by construction? Assuming small for now.
