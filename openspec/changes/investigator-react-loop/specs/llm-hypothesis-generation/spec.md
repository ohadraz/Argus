## ADDED Requirements

### Requirement: A real LLM produces the hypothesis from retrieved evidence
The system SHALL call a real Claude model to produce a hypothesis from the
metrics and log evidence an iteration retrieved. The call SHALL return a
summary, a cause type (possibly undetermined), a confidence between 0 and 1,
and the evidence the verdict relied on.

#### Scenario: A verdict is produced from evidence
- **GIVEN** an iteration that retrieved metric buckets and log lines
- **WHEN** the hypothesis is requested
- **THEN** a summary, a cause type, a confidence in `[0, 1]`, and the
  supporting evidence are returned

### Requirement: The model's response shape is enforced, not parsed by hand
The system SHALL constrain the model's response to the hypothesis schema using
the API's structured output support, rather than extracting fields from free
text.

#### Scenario: A response that does not match the schema is not accepted
- **GIVEN** a hypothesis request
- **WHEN** the model responds
- **THEN** the result either conforms to the hypothesis schema or the call
  fails, and no partially-parsed hypothesis is returned

### Requirement: A hypothesis carries a cause and a confidence together, or neither
The system SHALL reject the construction of a hypothesis that has a cause type
without a confidence, or a confidence without a cause type. A hypothesis with
no determined cause SHALL never be treated as confident enough to act on, at
any threshold, and this SHALL be enforced by the system rather than relied upon
from the model.

#### Scenario: A confident verdict naming no cause cannot be built
- **WHEN** a hypothesis is constructed with no cause type but with a confidence
- **THEN** construction fails

#### Scenario: A cause without a confidence cannot be built
- **WHEN** a hypothesis is constructed with a cause type but no confidence
- **THEN** construction fails

#### Scenario: An undetermined hypothesis is never confident enough to act on
- **GIVEN** a hypothesis with no determined cause
- **WHEN** it is tested against any confidence threshold
- **THEN** it is not confident enough, and the incident does not route to
  `mitigating`

### Requirement: The LLM is reachable only through an injectable typed seam
The system SHALL expose the model behind a typed client interface that callers
depend on, and SHALL allow that client to be substituted at the call site, so
that tests exercise the loop without contacting the API.

#### Scenario: A substituted client keeps a test offline
- **GIVEN** a test that supplies its own client returning a fixed hypothesis
- **WHEN** the Investigator investigates
- **THEN** the fixed hypothesis is used and no network call is made
