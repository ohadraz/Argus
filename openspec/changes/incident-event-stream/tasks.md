## 1. The event and its publisher

- [x] 1.1 Propose a test for the event models in `argus_core` - one type per thing that happens, each carrying its incident, its moment, and the values that make it readable without the code that published it (TDD: test proposed in chat, human pastes, then implement)
- [x] 1.2 Add the `Publisher` Protocol - one method, saying nothing about transport
- [x] 1.3 Propose a test that a publisher which raises does not fail the caller, then implement the seam that swallows it, with a comment naming why this one exception is swallowed
- [x] 1.4 Confirm no event type carries a value a reader would have to re-derive - a window has both bounds, a retrieval names its channel

## 2. Recording the stream

- [x] 2.1 Add the `incident_event` table to `argus_core.schema` - append-only, ordered, one incident per row's key; no migration, the schema is disposable
- [x] 2.2 Propose a test for the repository's write side, then add it - the subscriber's only job
- [x] 2.3 Propose a test for reading an incident's events back in the order they were published, then add `events.get_by_incident`
- [x] 2.4 Wire the default publisher to that subscriber, in one place
- [x] 2.5 Confirm the single-writer rule holds: recording an event writes no incident, hypothesis, action or timeline row

## 3. Components narrate themselves

- [x] 3.1 Propose a test that the graph publishes an agent invocation, then publish from the nodes
- [x] 3.2 Propose a test that the graph publishes each status change, then publish it
- [x] 3.3 Propose a test that the Investigator publishes each retrieval - channel and both window bounds - and what came back, then publish it
- [x] 3.4 Propose a test that the Investigator publishes the onset it detected and each hypothesis it formed, then publish them
- [x] 3.5 Publish the action taken and the verdict reached from the graph's mitigation node - neither `take_action` nor `Action` is incident-scoped, and threading an incident through an agent purely so it can narrate would put a field in the domain for the account's benefit
- [x] 3.6 Confirm an incident that runs with no subscriber reaches the same conclusion - the account is never part of the work
- [x] 3.7 Give `take_action` an incident and a publisher of its own, so the wait for the service to answer is narrated - it is the longest silence on the page, and the one a viewer is most likely to read as nothing happening
- [x] 3.8 Propose a test that each re-read of the metrics while waiting is published, then publish it

## 4. The live page

- [x] 4.1 Shape the recorded events into what a reader sees - one view model per narration line, carrying the evidence its event held
- [x] 4.2 The front page: the newest incident that has not finished, else the newest overall shown as finished, else a page that says nothing is happening
- [x] 4.3 The header - alert, service, when it started, status shown as live while it runs, elapsed time counting up
- [x] 4.4 The narration itself, in order, each line timed
- [x] 4.5 Metric buckets rendered as a table with the anomalous values marked, as the shop's console marks them
- [x] 4.6 Log lines rendered with their level distinguished - warnings and errors apart from the rest
- [x] 4.7 Poll at the shop console's cadence and stop at a terminal status, the way the incident page already does
- [x] 4.8 Navigation: now, the history, and an incident's detail - reachable without knowing a URL

## 5. Running it

- [x] 5.1 Confirm `nox -s test_module` covers every new module's tests, component tests included
- [x] 5.2 Check `nox -s lint typecheck test_all guard_e2e_boundary integration`
- [x] 5.3 `nox -s stack`, stage a scenario, and watch the narration fill in beside the shop's console

## 6. Specification

- [x] 6.1 State the stream in `docs/spec-and-architecture.md` §4 as principle 8 - `REPLAY_LOG` stays principle 6's own, unbuilt, eval concern - and rewrite §7.7 to describe the live view as the front door (see the spec-doc-style skill)
- [x] 6.2 Add the `incident_event` table to §11.1's ERD
- [x] 6.3 Reconcile the `live-incident-view` delta, the proposal and the design with the evidence being gathered into a table per channel below the narration rather than rendered inline
