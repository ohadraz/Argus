# mitigation-retry-walk Specification

## Purpose
TBD - created by archiving change ranked-hypotheses-retry. Update Purpose after archive.
## Requirements
### Requirement: A refuted candidate is followed by the next candidate
When a mitigation is refuted and an untried candidate remains above the mitigate threshold, the system SHALL propose and take an action for that next candidate rather than ending the incident. Each candidate SHALL pass through the tier gate on its own.

#### Scenario: The second candidate is tried after the first is refuted
- **GIVEN** an incident with two candidates above the threshold
- **WHEN** the action for the first is taken and the service does not return to baseline
- **THEN** an action is proposed and taken for the second candidate

#### Scenario: A confirmed candidate ends the walk
- **GIVEN** an incident mid-walk
- **WHEN** an action is confirmed by the service returning to baseline
- **THEN** no further candidate is tried and the incident resolves

### Requirement: The undo is confirmed before the next attempt begins
Before taking an action for the next candidate, the system SHALL verify that the refuted action's undo actually took effect, by reading the changed state back from the provider that holds it. An undo that cannot be confirmed SHALL end the walk immediately with an escalation, and no further action SHALL be taken.

#### Scenario: A confirmed undo lets the walk continue
- **GIVEN** a refuted action whose flag has been put back
- **WHEN** the provider is asked for that flag's state and reports the original value
- **THEN** the walk proceeds to the next candidate

#### Scenario: An unconfirmed undo stops the walk
- **GIVEN** a refuted action whose undo did not take effect
- **WHEN** the provider reports a state other than the original
- **THEN** the incident escalates, the timeline records that the undo could not be confirmed, and no action is taken for any further candidate

### Requirement: An irreversible candidate is skipped, not fatal
When the tier gate rejects the action proposed for a candidate - because no action was proposed, or because it carries no undo descriptor - the system SHALL record the rejection, post it for a human, and continue to the next candidate. A gate rejection SHALL end the incident only when no candidate remains.

#### Scenario: A rejected action does not end a walk with candidates left
- **GIVEN** an incident whose second candidate yields an action with no undo descriptor
- **WHEN** the gate rejects it
- **THEN** the rejection is recorded and posted, and the third candidate is tried

#### Scenario: A rejected action on the last candidate escalates
- **GIVEN** an incident whose final candidate's action is rejected by the gate
- **WHEN** no candidate remains
- **THEN** the incident escalates

### Requirement: An action that could not be taken ends the walk
An outcome of `escalated` - the action could not be performed at all - SHALL end the walk immediately, without trying a further candidate. Nothing was changed and nothing was measured, so the state of the world is unknown, and a further experiment would be run against a world Argus cannot describe.

#### Scenario: A provider that cannot be written to ends the walk
- **GIVEN** an incident mid-walk whose next action cannot be performed
- **WHEN** the action returns an escalated outcome
- **THEN** the incident escalates and no further candidate is tried

### Requirement: Each attempt is recorded against its own candidate
Every attempt SHALL mark its candidate as tested and record what the attempt did. The action recorded for an attempt SHALL name the hypothesis it was taken for, so the association between a decision and the act carried out for it is stored rather than inferred. The incident's timeline SHALL show which candidates were tried, in what order, and with what result.

#### Scenario: The timeline reads as an ordered set of attempts
- **GIVEN** an incident where two candidates were tried and refuted and a third confirmed
- **WHEN** the incident is read back
- **THEN** three candidates are marked tested, each with its own result, in the order they were attempted

#### Scenario: An action names the candidate it was taken for
- **GIVEN** an attempt on a ranked candidate
- **WHEN** the action taken for it is recorded
- **THEN** the action row names that hypothesis, and a reader follows that reference rather than matching on the subject the two happen to share

#### Scenario: Two candidates naming the same subject
- **GIVEN** two candidates in one incident that name the same flag
- **WHEN** an action is taken for each
- **THEN** each action is still attributable to its own candidate, because the association does not depend on the subject being unique

### Requirement: A withdrawal ends the walk

Where an incident is withdrawn mid-walk, the system SHALL stop the walk without
trying any remaining candidate and without opening a further investigation
round. The walk SHALL NOT treat the withdrawal as a refutation: nothing was
measured, so no candidate is marked tested and no verdict is recorded for the
attempt in progress.

#### Scenario: Candidates left are not tried

- **GIVEN** an incident mid-walk with two untried candidates above the mitigate
  threshold
- **WHEN** it is withdrawn
- **THEN** no action is proposed or taken for either, and the walk ends

#### Scenario: The attempt in progress is not scored

- **GIVEN** an incident withdrawn while an action's verification window is open
- **WHEN** the walk ends
- **THEN** the candidate is not marked tested and no verdict is recorded for it

#### Scenario: No further round is opened

- **GIVEN** an incident withdrawn with investigation rounds remaining
- **WHEN** the walk ends
- **THEN** no further investigation is started

### Requirement: Candidate order is informed by what was tried before

Before the first action of an incident is proposed, the system SHALL search
long-term memory for records of similar past incidents, and SHALL demote any
candidate whose subject was acted on in one of them and refuted. Candidates not
named by any such record SHALL keep their confidence order among themselves.

The search happens once, before the order is fixed, rather than being offered as
something to ask for. A past refutation is not a hypothesis and the walk does
not reason about it - it is an ordering fact, and the walk that consults it every
time is the only one whose behaviour with memory and without it can be compared.

#### Scenario: A subject refuted on a similar incident is tried later

- **GIVEN** an incident with two candidates, the higher-confidence one naming a
  flag that a similar past incident acted on and refuted
- **WHEN** the candidate order is fixed
- **THEN** the other candidate is tried first

#### Scenario: A subject confirmed on a similar incident keeps its place

- **GIVEN** a candidate naming a flag that a similar past incident acted on and
  confirmed
- **WHEN** the candidate order is fixed
- **THEN** it is not demoted

#### Scenario: Candidates untouched by memory keep confidence order

- **GIVEN** three candidates, none named by any past record
- **WHEN** the candidate order is fixed
- **THEN** they are tried in descending confidence order, as they would be with
  no memory at all

### Requirement: Memory demotes a candidate but never removes it

A past refutation SHALL NOT mark a candidate tested, exclude it from the walk, or
prevent it from being tried when every candidate above it has been refuted. Where
memory demotes every candidate, the walk SHALL try them all, in the order memory
gave.

A past incident is evidence about a past incident. The same flag can break the
service twice, and a walk that refused to try the only candidate it had - on the
strength of a different incident's result - would end with an escalation it had
the means to avoid.

#### Scenario: A demoted candidate is still tried in its turn

- **GIVEN** two candidates where memory demoted the first
- **WHEN** the second is tried and refuted
- **THEN** the demoted candidate is tried next

#### Scenario: Every candidate demoted still yields a walk

- **GIVEN** an incident whose every candidate was refuted on similar past
  incidents
- **WHEN** the candidate order is fixed
- **THEN** the walk proceeds and the first of them is tried

### Requirement: The order memory produced is recorded

The incident's timeline SHALL record that memory changed the order candidates
would otherwise have been tried in, naming the past incident whose record caused
the change.

A walk that tried its second-best candidate first, with nothing saying why, is a
walk a human reading the incident back cannot account for.

#### Scenario: A reordering is accounted for

- **GIVEN** an incident where memory demoted the highest-confidence candidate
- **WHEN** the incident is read back
- **THEN** the timeline says the order was changed, and names the past incident
  it was changed on the strength of

#### Scenario: An unchanged order says nothing

- **GIVEN** an incident where memory named none of the candidates
- **WHEN** the incident is read back
- **THEN** the timeline records no reordering
