## ADDED Requirements

### Requirement: A determined mode that nothing in the set answers is refused in its own words
The system SHALL distinguish two silences at the gate. An incident whose
hypothesis names no mode, or whose mode names no action anything could
identify, SHALL be refused as a mitigation nobody could propose. An incident
whose mode *is* determined, and which no member of the closed set of generic
mitigations answers, SHALL be refused as a failure this system has no
mitigation for.

The distinction SHALL be published on the refusal and SHALL reach the candidate's
own row, the timeline and the postmortem in words a reader can act on: the first
says somebody has to work out what to do, the second says somebody outside this
system has to do it.

Which of the two a refusal is SHALL be answered by the policy that holds the set
of mitigations, not by the gate keeping a second copy of it.

#### Scenario: A mode with no mitigation is refused as such
- **GIVEN** a hypothesis naming a mode that no generic mitigation answers
- **WHEN** the gate is reached with no proposed action
- **THEN** the refusal recorded and published is that nothing in the set answers
  this kind of failure, and no mutating call is made

#### Scenario: An unidentifiable action is still refused as unproposed
- **GIVEN** a hypothesis naming a mode a generic mitigation does answer, but
  whose action could not be identified from the evidence
- **WHEN** the gate is reached with no proposed action
- **THEN** the refusal recorded is that no mitigation was proposed for this
  cause

#### Scenario: The incident escalates either way
- **GIVEN** either refusal
- **WHEN** no further candidate remains to try
- **THEN** the incident ends escalated, with a postmortem, and no action taken
