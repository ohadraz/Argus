# dependency-restart-mitigation Specification

## Purpose
Answering an internal dependency's failure by restarting the service the
investigation named rather than the one the alert did. The mode is distinct
from a third party's failure by ownership alone; the address it acts on is a
field of the hypothesis rather than the model's description of the fault; and
the mitigation is the restart that already exists, aimed somewhere new. The
restart is confirmed against the dependency's own process and judged by whether
the alerting service recovered.
## Requirements

### Requirement: An internal dependency's failure is a failure mode of its own
The system SHALL hold `internal-dependency-failure` among the failure modes it
can determine: the alerting service is well, and a service it calls - one the
same organisation owns - is not. It SHALL be distinct from
`upstream-dependency-failure`, which is the same shape of propagation with the
dependency belonging to somebody else, and the distinction SHALL be ownership
rather than anything the telemetry carries.

A reader of an incident distinguishes the two, which is the test a mode has to
pass. That this mode and `resource-leak` are both answered by a restart is the
ordinary shape of a lookup, as two modes answered by a rollback already are.

#### Scenario: The mode is available to be determined
- **WHEN** the set of failure modes is offered to the model weighing evidence
- **THEN** `internal-dependency-failure` is among them, with what it means and
  what separates it from a third party's failure

#### Scenario: The mode is persisted on the hypothesis
- **GIVEN** an investigation determining an internal dependency's failure
- **WHEN** the hypothesis is recorded
- **THEN** its failure mode is `internal-dependency-failure`

### Requirement: A hypothesis of this mode names the service at fault
The system SHALL let a hypothesis carry the service at fault as a field of its
own, distinct from the subject the cause names. The subject is the model's
description of what went wrong; this is an address, and it is what a platform
call is sent to.

A hypothesis determining `internal-dependency-failure` SHALL name one, and one
that does not SHALL be treated as having identified no action rather than as a
diagnosis to act on.

#### Scenario: The named service is recorded and available to the mitigation
- **GIVEN** an investigation concluding that a named dependency is at fault
- **WHEN** the hypothesis is recorded and read back
- **THEN** the service it names is carried on the hypothesis, separately from
  its subject

#### Scenario: This mode without an address proposes nothing
- **GIVEN** a hypothesis determining an internal dependency's failure and naming
  no service
- **WHEN** an action is proposed for it
- **THEN** none is, and the refusal recorded is that no mitigation could be
  identified from the evidence

### Requirement: The mitigation is a restart addressed to the named dependency
The system SHALL answer `internal-dependency-failure` by restarting the service
the hypothesis names, not the service the alert names. No new kind of action
SHALL be introduced for it: a restart already carries the service it addresses,
and what is new is where that service comes from.

#### Scenario: The dependency is restarted rather than the alerting service
- **GIVEN** a confirmed hypothesis naming a dependency of the alerting service
- **WHEN** the mitigation is taken
- **THEN** the restart is addressed to the dependency, and the alerting service
  is not restarted

#### Scenario: The account says which service was restarted
- **WHEN** a restart of a dependency is announced and recorded
- **THEN** the sentence a reader sees names the dependency, and does not read as
  though the service the incident is about had been restarted

### Requirement: A restart of a dependency is verified by the alerting service's recovery
The system SHALL confirm the restart landed by reading the restarted service's
own process start time, and SHALL judge whether it helped by whether the
alerting service's symptoms eased. The incident belongs to the service that was
paged, so recovery is measured there; the restart belongs to the dependency, so
it is confirmed there.

#### Scenario: A restart that landed and eased the incident is confirmed
- **GIVEN** a restart of a dependency after which its process start time changed
  and the alerting service's latency returned towards its baseline
- **WHEN** the verdict is measured
- **THEN** the mitigation is confirmed

#### Scenario: A restart that landed and changed nothing is refuted
- **GIVEN** a restart of a dependency after which its process start time changed
  and the alerting service's telemetry is unchanged
- **WHEN** the verdict is measured
- **THEN** the hypothesis is refuted, nothing is unwound because a restart leaves
  nothing to put back, and the walk moves on to the next candidate
