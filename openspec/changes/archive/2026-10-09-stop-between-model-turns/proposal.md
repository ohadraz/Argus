## Why

A walk finds out its incident is no longer wanted only at a node boundary and
while Mitigation waits for a service to recover. A node already running carries
on to its end: the Investigator's and Code-Fix's loops keep asking the model and
calling tools for minutes, spending tokens on an incident a person has taken
back, and Mitigation can still change the world after the person said stop if
the word arrives between its node starting and its action being applied. The
spec already says an answer that arrives after a withdrawal is not acted on;
inside those loops it is.

This is the first of three changes towards a human being able to report an
incident resolved (from the Argus UI, then from PagerDuty). That report must
stop Argus as promptly as a withdrawal does, so the stopping is made prompt
first, against the one "stop" that exists today.

## What Changes

- The Investigator's loop asks whether the incident is still wanted before
  every model turn, and stops without a finding when it is not.
- Code-Fix's loop asks the same before every model turn, and stops without a
  fix when it is not.
- Mitigation asks immediately before applying any action, and applies nothing
  when the incident is no longer wanted. An undo of Argus's own refuted change
  is not an action in that sense and still completes.
- A loop that stopped this way is reported to the walk as stopped, which routes
  out exactly as a withdrawal noticed at a node boundary does - not as a failure,
  not as "found nothing", and not as an escalation.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `incident-withdrawal`: "A withdrawn incident is not walked further" is
  checked between model turns in the Investigator and Code-Fix, and immediately
  before Mitigation applies an action - not only at node boundaries and in the
  recovery wait.

## Impact

- `agent_investigator` (`investigation.py` loop), `agent_codefix`
  (`proposing.py` loop), `agent_mitigation` (where an action is applied): each
  takes a "still wanted" question as an injected callable. Agents do not depend
  on `argus_incidents`, so the type they take is their own (or `argus_core`'s).
- `orchestrator`: the investigator, codefix and mitigation nodes pass the
  question in and translate a stopped outcome into `withdrawn` for the routers.
- No schema change, no new event kind, no new recording. Existing replay
  recordings are unaffected: a walk that is never withdrawn asks the question
  and gets "yes" every time.
