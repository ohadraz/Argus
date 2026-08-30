## ADDED Requirements

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
