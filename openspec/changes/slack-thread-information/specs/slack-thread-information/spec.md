## ADDED Requirements

### Requirement: A lead reaches every model-backed agent

The system SHALL treat a message written in an incident's thread and
understood as information as a lead. The Investigator, Code-Fix and the
Postmortem SHALL each be given every lead understood before they start. The
Investigator and Code-Fix SHALL be given any lead understood while they run,
on their next turn, without a tool call being interrupted.

#### Scenario: A lead written before the walk

- **GIVEN** a lead understood before the investigation starts
- **WHEN** the Investigator starts
- **THEN** its first message carries the lead

#### Scenario: A lead written mid-investigation

- **GIVEN** an investigation in progress
- **WHEN** a lead is understood
- **THEN** the model is given it with the result of its next tool call

#### Scenario: A message that is not a lead

- **GIVEN** a message understood as anything but information
- **THEN** no agent is given it as a lead

### Requirement: A lead is weighed, never obeyed

The Investigator SHALL give every lead it is shown a standing: supported, when
something it read agrees with the lead; refuted, when something it read
contradicts it; unverified, when neither. A refuted lead SHALL NOT be acted on.
An unverified lead MAY become a candidate, at the confidence the model gives
it, and SHALL pass the tier gate as any candidate does. An answer SHALL be
refused while a lead shown is unweighed and the budget leaves a turn to weigh it
in; on the last turn the answer SHALL be taken, and the lead SHALL come back
unweighed. Every standing given SHALL come back with the findings, however the
investigation ends.

#### Scenario: A supported lead is evidence for what it names

- **GIVEN** two changes the evidence supports equally
- **AND** a lead naming one of them
- **WHEN** the Investigator finds evidence agreeing with the lead
- **THEN** the lead is weighed supported, and counts as evidence for the
  change it named like anything else the Investigator read

#### Scenario: An answer with a lead unweighed

- **GIVEN** an Investigator shown a lead
- **WHEN** it answers without weighing it
- **THEN** the answer is refused and the model is told which lead is unweighed

#### Scenario: A lead shown with the last result

- **GIVEN** an Investigator with one turn left
- **AND** a lead written in time to ride on the result before it
- **WHEN** the model answers without weighing the lead
- **THEN** the answer is taken, and the lead comes back unweighed

#### Scenario: An investigation that names no cause

- **GIVEN** an Investigator that has weighed a lead
- **WHEN** it runs out of budget, is cut short, or the model declines
- **THEN** the standing it gave comes back with the findings

#### Scenario: Weighed again after a refutation

- **GIVEN** a lead weighed once, and the walk returning to the Investigator
- **WHEN** the Investigator weighs it again
- **THEN** the later standing is the lead's standing

### Requirement: The person is told how their lead was weighed

The system SHALL record each standing on the incident with its reason, and SHALL
say it on the incident's timeline and in its Slack thread.

#### Scenario: A lead is weighed

- **WHEN** the Investigator weighs a lead
- **THEN** the standing and its reason are on the incident, on its timeline,
  and in its thread

### Requirement: A late lead does not reopen the investigation

A lead understood after the Investigator has answered SHALL reach Code-Fix and
the Postmortem, and SHALL be shown to the Investigator only if the walk returns
to it. Code-Fix SHALL be given each lead with its standing, or as unweighed,
and SHALL give none of its own. Code-Fix and the Postmortem SHALL be told each
standing was given before anything was tried, so a cause an action later
confirmed outranks it.

#### Scenario: A refuted lead whose cause confirmed

- **GIVEN** a lead the Investigator refuted
- **AND** an action on what the lead named, later confirmed
- **THEN** Code-Fix is told the finding outranks the standing, and the
  Postmortem that the actions are the later word

#### Scenario: A lead during Code-Fix

- **GIVEN** a walk in Code-Fix
- **WHEN** a lead is understood
- **THEN** Code-Fix is given it, labelled unweighed, and no investigation
  starts
