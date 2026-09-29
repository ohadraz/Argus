# alert-supplied-onset Specification

## Purpose
When an incident began, where the service's own series cannot say. The measurement of spec §9 is the authority wherever it finds anything; this is what happens when it finds nothing and the alert dates its own finding - so that a fault leaving no operational trace is still an incident with a beginning to anchor retrieval on.
## Requirements
### Requirement: A measured onset wins wherever one exists

The system SHALL measure the onset from the retrieved metrics first, and SHALL
use that minute whenever one is found, even where the alert states an onset of
its own.

A measured onset is evidence and a stated one is testimony. The measurement is
made from the buckets Argus retrieved itself and can be re-derived by anyone
reading the incident; a figure in an alert is whatever the thing that fired it
chose to say. Where both exist they should agree, and where they do not the one
that can be checked is the one to keep.

#### Scenario: A stated onset does not displace a measured one
- **GIVEN** an alert carrying an onset, for a window whose series depart
- **WHEN** the onset is decided
- **THEN** it is the minute measured from the metrics

### Requirement: An onset stated by the alert is accepted when none can be measured

The system SHALL use the onset an alert states whenever no onset can be measured
from the retrieved window, and SHALL investigate from it exactly as it would from
a measured one.

This is what lets an incident be found by something other than a health series. A
window that is flat because nothing was ever wrong and a window that is flat
because what is wrong is a value are the same window, and only the alert can tell
them apart.

#### Scenario: A flat window with a stated onset is investigated
- **GIVEN** an alert carrying an onset, for a window in which no series departs
- **WHEN** the investigation runs
- **THEN** it proceeds from the stated onset, and a model is asked

#### Scenario: A flat window with no stated onset ends as it always did
- **GIVEN** an alert carrying no onset, for a window in which no series departs
- **WHEN** the investigation runs
- **THEN** it returns without asking a model, unchanged from the behaviour every
  other incident relies on

### Requirement: The opening message says a stated onset is uncorroborated

The system SHALL tell the model, in the opening message, when the onset it is
working from was stated by the alert rather than measured - that no series
departs across it, and that the metrics therefore carry no evidence about this
incident at all.

Said rather than left implicit, for the reason the "window opens already
elevated" sentence is said: a model handed a flat window and a confident minute
would otherwise read the flatness as the service being well, and conclude there
is nothing to find.

#### Scenario: The model is told the metrics corroborate nothing
- **GIVEN** an investigation working from an onset the alert stated
- **WHEN** the opening message is built
- **THEN** it says the onset came from the alert and that no series departs
  across it

#### Scenario: A measured onset is described as it always was
- **GIVEN** an investigation working from a measured onset
- **WHEN** the opening message is built
- **THEN** it says the onset was measured from the per-minute metrics, unchanged

### Requirement: A stated onset may sit outside everything retrievable

The system SHALL accept an onset older than the span the metrics source keeps,
and SHALL address the change channels at that minute rather than at the alert.

An alert that carries its own onset is reporting something found long after it
began. Anchoring the change history on when the alert fired would ask what
changed during the discovery rather than during the fault, which for a check that
runs weekly is a week of changes and no answer.

#### Scenario: The change channels are read at the stated onset
- **GIVEN** an investigation working from an onset a week before the alert fired
- **WHEN** the flag and deploy histories are retrieved
- **THEN** they cover the stated onset, not the minute the alert fired
