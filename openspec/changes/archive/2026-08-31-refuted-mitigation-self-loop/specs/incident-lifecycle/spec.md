## ADDED Requirements

### Requirement: A status is written only when the incident enters it

The system SHALL write an `Incident.status` transition only for a status the
incident actually occupies. A status that is set and immediately overwritten by
the next node SHALL NOT be written at all, because the timeline and the event
stream are read as the account of where the incident has been, and a status it
passed through in name only is a claim about the incident that is not true.

#### Scenario: A refuted action does not pass through a status it never occupies

- **GIVEN** an incident whose mitigation was refuted and which has an untried
  candidate above the mitigate threshold
- **WHEN** the graph runs
- **THEN** the incident's timeline records no transition to `fixing`, and no
  `StatusChanged` event carrying `fixing` is published

### Requirement: `fixing` is the status of an incident a permanent fix is being sought for

The system SHALL use `fixing` for, and only for, an incident that has reached
Code-Fix - the point at which no reversible mitigation is left to try and the
remaining move is a code change. `fixing` SHALL NOT be terminal, because
Code-Fix is still working when it is set. `escalated` SHALL be reached only
once Argus has no move left at all, so that a human reading a status can tell
"Argus is still working on this" from "this is now yours".

#### Scenario: Reaching Code-Fix is recorded as fixing

- **GIVEN** an incident whose candidates are all refuted and whose widening
  schedule has reached its maximum
- **WHEN** the graph hands the incident to Code-Fix
- **THEN** the incident's status is `fixing`, and `fixing` reports itself as
  non-terminal

#### Scenario: A mid-walk refutation is not recorded as fixing

- **GIVEN** an incident whose mitigation was refuted and which has an untried
  candidate above the mitigate threshold
- **WHEN** the graph runs
- **THEN** the incident's status is `mitigating`, not `fixing`

## MODIFIED Requirements

### Requirement: FSM completes the investigating → mitigating → resolved happy path
The system SHALL transition an incident through `investigating` → `mitigating` →
`resolved` (spec §10) with no manual intervention, using stub sub-agent logic for
Code-Fix, Communicator, and Postmortem. The Investigator performs real cause
detection via the bounded ReAct loop (spec §9) - onset-anchored retrieval and an
LLM verdict - for at least the `feature-flag-toggle` scenario. Mitigation
performs a real reversible action and returns a verdict measured from re-queried
metrics: `resolved` SHALL follow only from a `confirmed` verdict, so an incident
is never marked resolved while the condition that caused it is still in effect.
When no cause is determined, the Investigator reports a confidence below the
mitigate threshold and the incident routes to `escalated` rather than continuing
the happy path.

`mitigating` SHALL be re-enterable, and a refuted action SHALL self-loop on it.
The incident stays in `mitigating` for the next candidate rather than passing
through any other status on the way, and it leaves `mitigating` only on a
confirmed action, on an outcome that could not be taken at all, or when the walk
has run out of candidates and wider looks - in which last case it leaves for
`fixing`.

#### Scenario: No scenario seeded escalates rather than resolving
- **GIVEN** a new `Incident` in `investigating` status, and no scenario active on the Target Service
- **WHEN** the graph runs to completion
- **THEN** the Investigator determines no cause at a confidence below the mitigate threshold, and the incident's final status is `escalated`

#### Scenario: Happy path resolves an incident with a real diagnosed cause
- **GIVEN** a new `Incident` in `investigating` status, and the `feature-flag-toggle` scenario active on the Target Service
- **WHEN** the graph runs to completion
- **THEN** the Investigator determines `cause_type = "feature-flag-toggle"` at a
  confidence >= 0.75, Mitigation turns the flag off and confirms recovery from
  the metrics, and the incident's final status is `resolved`

#### Scenario: A resolved incident leaves the condition ended
- **GIVEN** an incident that reached `resolved`
- **WHEN** the flag provider is asked for the flag's state
- **THEN** the flag is off

#### Scenario: An action that does not resolve the symptom is followed by the next candidate
- **GIVEN** an incident whose mitigation was taken and whose metrics still depart
  from baseline afterwards, and an untried candidate above the mitigate threshold
- **WHEN** the graph runs
- **THEN** the recorded outcome for that candidate is `refuted` and the incident
  remains in `mitigating` for the next candidate rather than leaving for `fixing`

#### Scenario: A walk with nothing left routes onward from mitigating
- **GIVEN** an incident whose candidates are all refuted and whose widening
  schedule has reached its maximum
- **WHEN** the graph runs to completion
- **THEN** the incident leaves `mitigating` for `fixing`, a human is paged, and
  the final status is not `resolved`

#### Scenario: A refuted incident leaves the environment as it was found
- **GIVEN** an incident whose mitigation was refuted
- **WHEN** the graph has run to completion
- **THEN** the state the action changed has been restored, and the incident's
  timeline records both the action and its undo
