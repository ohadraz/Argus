## MODIFIED Requirements

### Requirement: The metrics summary is read once, before the loop
The system SHALL read the metrics summary a single time before the conversation with the
model is opened, for one fixed, wide window, and SHALL locate the onset from it. A window
in which no minute departs from the baseline SHALL end the investigation without opening
the conversation at all, except where the alert reports a finding of its own - in which
case the investigation proceeds without an onset. Where such a window ends the
investigation and the alert reported a series condition, the investigation SHALL report
that the alarm was disproven rather than that no cause was determined. The model MAY read
metrics again over another window as an ordinary tool call.

#### Scenario: No anomalous bucket means no onset and no model call
- **GIVEN** a metrics summary in which no bucket is anomalous, for an alert reporting a
  series condition
- **WHEN** the Investigator investigates
- **THEN** it does not report a determined cause, does not fabricate an onset,
  and does not ask the model

#### Scenario: No anomalous bucket under a series alarm reports a disproof
- **GIVEN** a metrics summary in which no bucket is anomalous, for an alert reporting a
  series condition and stating no onset
- **WHEN** the Investigator investigates
- **THEN** it reports that the alarm was disproven, which is a different finding from
  having read every channel and been unable to name a cause

#### Scenario: No anomalous bucket under a finding-carrying alarm still asks the model
- **GIVEN** a metrics summary in which no bucket is anomalous, for an alert reporting a
  finding of its own and stating no onset
- **WHEN** the Investigator investigates
- **THEN** the conversation is opened and the investigation proceeds with no onset
