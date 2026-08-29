## MODIFIED Requirements

### Requirement: A real LLM produces the hypothesis from retrieved evidence
The system SHALL call a real Claude model to produce a hypothesis from the
metrics and log evidence an iteration retrieved. The call SHALL return a
summary, a cause type (possibly undetermined), a confidence between 0 and 1,
the evidence the verdict relied on, and - where the cause is about a specific
named thing - the subject it is about.

#### Scenario: A verdict is produced from evidence
- **GIVEN** an iteration that retrieved metric buckets and log lines
- **WHEN** the hypothesis is requested
- **THEN** a summary, a cause type, a confidence in `[0, 1]`, and the
  supporting evidence are returned

#### Scenario: A flag-toggle verdict names the flag it blames
- **GIVEN** evidence in which one feature flag's evaluation changed
- **WHEN** the hypothesis is requested and the model names a feature-flag
  toggle as the cause
- **THEN** the hypothesis carries that flag's name as its subject, as a field
  rather than only inside its prose

## ADDED Requirements

### Requirement: A hypothesis carries the subject its cause is about
The system SHALL carry, on a hypothesis, the specific thing its cause names -
for a feature-flag toggle, the flag's name - as a typed field distinct from the
summary. The subject SHALL be absent where the cause names nothing specific or
where no cause was determined.

The field exists so that a later phase can act on the Investigator's conclusion
without re-deriving it. A conclusion that survives only as prose forces every
consumer to either parse English or repeat the investigation, and two phases
investigating the same incident separately can reach different answers, of
which the acting one is not the reasoning one.

#### Scenario: A named subject reaches the consumer as a field
- **GIVEN** a verdict naming a feature-flag toggle and the flag it blames
- **WHEN** the verdict becomes a hypothesis
- **THEN** the flag's name is readable from a field on the hypothesis

#### Scenario: An undetermined verdict names no subject
- **GIVEN** a verdict that identified no cause
- **WHEN** the verdict becomes a hypothesis
- **THEN** the hypothesis has no subject

#### Scenario: A subject without a cause cannot be built
- **WHEN** a hypothesis is constructed with a subject but no cause type
- **THEN** construction fails, because a named subject with nothing to blame it
  for is not a conclusion

#### Scenario: The subject is persisted with the hypothesis
- **GIVEN** a hypothesis naming a subject that was stored
- **WHEN** it is read back
- **THEN** the subject is present, so the record of the incident says what was
  blamed and not merely that something was

### Requirement: A named subject is drawn from the evidence, not invented
The system SHALL instruct the model to name a subject only using an identifier
appearing verbatim in the evidence it was given, and SHALL NOT treat a subject
as authorization on its own: a consumer acting on one SHALL confirm it against
the system that owns it before acting.

A name the model invents therefore fails confirmation rather than reaching a
write. This keeps the model's role to selecting among facts the evidence
already contains.

#### Scenario: The prompt constrains where a subject may come from
- **WHEN** the prompt is built for a hypothesis request
- **THEN** it states that the subject must appear verbatim in the evidence
  provided
