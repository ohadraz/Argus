# disproven-alarm-closure Specification

## Purpose
An alarm that fired about a series the metrics then show never departed is an
alarm the window disproves. Argus says so and stops, rather than handing a
responder an incident it could not explain - which is the same ending for two
opposite findings, and sends them to the service when what is wrong is the rule.

What a window can disprove is a claim about a series. An alarm reporting a
finding of its own - stored values that disagree with the records behind them,
readings that stopped arriving - is about something no series carries, so a
window with no departure in it is not evidence against that alarm and must not
close it. Which of the two a rule is, only the rule knows, so the alert carries
it.
## Requirements

### Requirement: An alert says whether it reports a series or a finding of its own

The system SHALL read, from the alert, whether the condition it reports was
measured on a series the system also retrieves, or is a finding the rule arrived
at by other means. That distinction SHALL be carried by the alert itself and
SHALL NOT be inferred from the alert's name.

A name table would have to gain a row for every rule in the estate, and would
read a rule named after its service as a rule about that service's series. What
distinguishes the two is what the rule looked at, which only the rule knows.

#### Scenario: A rule watching a series says so
- **GIVEN** an alert reporting an error rate above a threshold
- **WHEN** the alert is read
- **THEN** it is carried as reporting a series condition

#### Scenario: A rule carrying its own finding says so
- **GIVEN** an alert from a check that compared stored totals against the records
  behind them
- **WHEN** the alert is read
- **THEN** it is carried as reporting a finding of its own, whatever the alert is
  named

#### Scenario: An alert that says neither is treated as reporting a series
- **GIVEN** an alert carrying nothing about the kind of claim it makes
- **WHEN** the alert is read
- **THEN** it is treated as reporting a series condition, which is what every
  rule watching a threshold is and what a monitoring stack that says nothing
  about itself most likely has

### Requirement: A window with no departure disproves an alarm that reported a series

The system SHALL conclude that the alarm was disproven when the retrieved window
holds no departure in any judged signal, the alert states no onset, and the alert
reports a series condition. The conclusion SHALL record which signals were
judged and over what window, because an assertion that nothing departed is only
as good as the span and the signals it was made over.

#### Scenario: A well service under a series alarm is disproven
- **GIVEN** an alert reporting a high error rate, and a window in which no judged
  signal departs its baseline
- **WHEN** the investigation runs
- **THEN** the alarm is recorded as disproven, naming the signals judged and the
  window judged over

#### Scenario: A departure anywhere in the window is not a disproof
- **GIVEN** an alert reporting a high error rate, and a window in which one
  judged signal departs
- **WHEN** the investigation runs
- **THEN** the alarm is not disproven and the investigation proceeds from the
  onset it measured

### Requirement: A window with no minutes in it disproves nothing

The system SHALL NOT conclude that an alarm was disproven where the window holds
no minutes - whether the metrics could not be retrieved at all, or the retrieval
answered and returned nothing. A window that was read and held no departure says
the service is well; a window with nothing in it says nothing at all about the
service, and closing an alarm on the second would be reporting an absence of
evidence as evidence.

The two are one requirement rather than two because they are one state as far as
this judgement goes, and separating them is how the second gets missed: a read
that fails is plainly no evidence, where a read that succeeds and returns an
empty list looks like an answer and is not.

#### Scenario: An unreadable window escalates as it already does
- **GIVEN** an alert reporting a high error rate, and metrics that cannot be
  retrieved
- **WHEN** the investigation runs
- **THEN** the alarm is not disproven, and the incident ends as it does today for
  a window nobody could read

#### Scenario: A window that answered with nothing escalates
- **GIVEN** an alert reporting a high error rate, and a metrics channel that
  answers with no minutes at all
- **WHEN** the investigation runs
- **THEN** the alarm is not disproven, and the incident escalates - the
  retrieval having answered is not the same as there having been something to
  judge

### Requirement: An alarm carrying its own finding is not disproven by a flat window

The system SHALL go on investigating where the window holds no departure, the
alert states no onset, and the alert reports a finding of its own. The window is
not evidence against such an alarm, and the investigation SHALL proceed without a
date rather than close.

This is the branch a dateless finding needs: a check comparing stored values
against the records behind them can find a disagreement it cannot date, because
what would date it is what went missing. No scenario produces one today, and the
requirement exists so that the closure above cannot swallow one when a scenario
does.

#### Scenario: A finding with no onset is investigated without a date
- **GIVEN** an alert reporting a finding of its own and stating no onset, for a
  window in which no judged signal departs
- **WHEN** the investigation runs
- **THEN** the alarm is not disproven, a model is asked, and the investigation
  works without an onset

#### Scenario: A finding with an onset is unaffected
- **GIVEN** an alert reporting a finding of its own and stating an onset
- **WHEN** the investigation runs
- **THEN** it proceeds from the stated onset exactly as it does today

### Requirement: A disproven alarm forms no candidate and takes no action

The system SHALL form no hypothesis, attempt no mitigation, seek no permanent fix
and ask no model for a cause where the alarm was disproven. The whole of the
finding is that there was no incident, and a walk that went looking anyway would
be spending a model's attention on a service it has already established is well.

#### Scenario: Nothing is tried against a disproven alarm
- **GIVEN** an alert that the window disproves
- **WHEN** the walk runs to its end
- **THEN** no hypothesis row, no action row and no fix proposal is written for
  that incident

### Requirement: A human is told the rule was wrong rather than the service

The system SHALL page once at the end of a disproven alarm, as it does at the end
of any walk, and the message SHALL say that the alarm's own claim was not in the
window - naming the condition the rule reported and what the signals held
instead. A message that said only "no cause determined" would send a responder to
look at a service Argus has established is well.

#### Scenario: The page names the claim and what was found instead
- **GIVEN** an incident whose alarm was disproven
- **WHEN** the walk ends
- **THEN** exactly one page is raised, saying which condition the rule reported
  and that the window held no departure in any judged signal
