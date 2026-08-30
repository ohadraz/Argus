## 1. Repository read paths

- [x] 1.1 Propose a test for listing incidents newest first, then add `incidents.get_recent` (TDD: test proposed in chat, human pastes, then implement)
- [x] 1.2 Propose a test for every hypothesis of an incident in rank order, then add `hypotheses.get_all_by_incident` - `get_latest_by_incident` returns one, which is the shape that hides a walk
- [x] 1.3 Propose a test for the actions taken during an incident in order, then add `actions.get_by_incident` - `actions.py` has no read side at all today
- [x] 1.4 Confirm the new names obey the repository convention: bare `get()` only for primary-key lookups, descriptive `get_*` for anything relational

## 2. Shaping what the page shows

- [x] 2.1 Define the view models in `argus_web` - incident summary, incident detail, candidate (with evidence and verdict), attempt, timeline entry
- [x] 2.2 Build them from the repository rows, keeping the order the repositories returned rather than re-sorting
- [x] 2.3 Attach each attempt to the candidate its `action.hypothesis_id` names, and show an attempt that names none rather than dropping it
- [x] 2.4 Keep an untried candidate untried, and report an attempt with no verdict yet as undecided rather than undone
- [x] 2.5 Serve no JSON API - the page is the only reader there is, and an endpoint with no client is a second thing to keep honest
- [x] 2.6 Verify nothing here writes: the whole group is reads through the repositories

## 3. The page

- [x] 3.1 Add Jinja2 templating and a static mount to `argus_web`, with htmx vendored into the mount rather than pulled from a CDN
- [x] 3.2 Incident detail template: alert, status, and the walk - every candidate in rank order, tried or not, with action, verdict and undo
- [x] 3.3 Show a candidate's evidence against the candidate, not as a separate dump
- [x] 3.4 Render partial state honestly - an action with no verdict yet is a state, not an absence
- [x] 3.5 History view: incidents and their outcomes, linking to detail and to the postmortem
- [x] 3.6 HTMX polling at the shop console's cadence, stopping once the incident reaches a terminal status
- [x] 3.7 Page handlers read through the repositories and the view builders - never SQL of their own

## 4. Identity

- [x] 4.1 Eye favicon, served from `argus_web`'s static mount
- [x] 4.2 Distinct page title, so Argus's tab is not confusable with the shop's
- [x] 4.3 Serve the README's Argus artwork on the page itself, from the same static mount

## 5. Running it

- [x] 5.1 Add a `stack` nox session that brings the e2e stack up and holds it open - `argus_web` is a local uvicorn on :8000, not a compose service, so there is no port to publish; what was missing was a stack that outlives a test run
- [x] 5.2 Confirm `nox -s test_module(module='argus_web')` covers the new code
- [x] 5.3 Check `nox -s lint typecheck test_all guard_e2e_boundary integration`

## 6. Specification

- [x] 6.1 Rewrite `docs/spec-and-architecture.md` §7.7 and §7.9 to describe `argus_web` serving the view itself - as the intent, not as a change (see the spec-doc-style skill); drop `argus_dashboard` as a planned module
- [x] 6.2 Resolve the open question in design.md: the postmortem is its own page, not a field on the incident - it is the largest body Argus writes and the incident page beside it polls

## 7. Seeing it work

- [x] 7.1 Stage `competing-flag-changes` against the live stack and watch the walk render beside the shop's console
- [x] 7.2 Confirm a finished incident stops polling
- [x] 7.3 Confirm an escalated incident shows every candidate it tried rather than an empty page
