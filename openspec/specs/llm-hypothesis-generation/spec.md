# llm-hypothesis-generation Specification

## Purpose
Covers how Argus turns retrieved evidence into a hypothesis: the real Claude
call behind a typed seam, the enforced response shape, and the domain rule that
a cause and a confidence travel together or not at all.
## Requirements
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

### Requirement: A verdict may carry the alternatives the model weighed
The verdict schema SHALL allow the model to return, alongside its best explanation, the other explanations it considered for the same evidence - each with its own summary, cause type, confidence, supporting evidence, and subject. Alternatives SHALL be optional on the wire: a verdict that omits them is a verdict naming one explanation, not a malformed one.

The field is lenient for the same reason `subject` is. Every recording captured before it existed omits it, and refusing those would turn a replayed answer into a malformed verdict and cost the offline suites the evidence they exist to provide.

#### Scenario: A verdict with alternatives becomes several candidates
- **GIVEN** a verdict naming a primary cause and two alternatives
- **WHEN** it is turned into hypotheses for the incident
- **THEN** three hypotheses are produced, each carrying its own cause, confidence and subject

#### Scenario: A verdict without alternatives is still valid
- **GIVEN** a recorded verdict that carries no alternatives field at all
- **WHEN** it is replayed
- **THEN** it yields a single hypothesis and no error

#### Scenario: An alternative is held to the same coherence rules
- **GIVEN** a verdict whose alternative names a subject but no cause type
- **WHEN** it is turned into hypotheses
- **THEN** the verdict is rejected as malformed, exactly as an incoherent primary answer is

### Requirement: The prompt asks for alternatives, and says what makes one
The system prompt SHALL instruct the model to name the other explanations the same evidence supports, ranked by its own confidence, and SHALL state that an alternative is a competing explanation of the evidence in hand rather than a guess to fill the list. An empty list SHALL be described as a valid answer.

#### Scenario: Evidence supporting one explanation yields no padding
- **GIVEN** evidence that supports exactly one explanation
- **WHEN** the model answers
- **THEN** it names that explanation and no alternatives

### Requirement: Evidence carries what was already tried and refuted
The evidence given to the model SHALL be able to include the attempts already made for this incident - what was changed, to what state, and that the service did not return to baseline. It SHALL be stated as recorded fact rather than as an instruction about what not to say.

#### Scenario: A resumed investigation is told what failed
- **GIVEN** an incident where a named flag was set off and the service did not recover
- **WHEN** evidence for a later round is built
- **THEN** it contains that flag, the state it was set to, and the fact that the service did not recover

#### Scenario: A first investigation carries no attempts
- **GIVEN** an incident with no attempt yet made
- **WHEN** evidence is built
- **THEN** it carries no attempts section

