## ADDED Requirements

### Requirement: An action is bounded by what it is addressed to, as well as by its kind
The system SHALL refuse an action addressed to a service outside the alerting
service's own estate, whatever the action's kind. A service SHALL be within that
estate when it is the alerting service itself, or when the retrieved service
catalogue lists it as a dependency of the alerting service and marks it as owned
by the same organisation. Everything else SHALL be refused, and nothing mutating
SHALL be called.

The bound SHALL come from retrieved evidence rather than from Argus's own
configuration, for the reason the subject of a restart already does: a
configured list of touchable services hardcodes one deployment's answer into the
agent.

This is a second question, not a widening of the first. Membership of the closed
set of generic mitigations stays a property of the kind, and this asks about the
instance - because an address written by a model can name a third party, a
service in another part of the estate, or prose mistaken for a hostname, and no
fact about the kind answers any of those.

#### Scenario: An owned dependency of the alerting service may be acted on
- **GIVEN** a proposed action of an admitted kind, addressed to a service the
  catalogue lists as an owned dependency of the alerting service
- **WHEN** the gate is asked whether it may proceed
- **THEN** it proceeds

#### Scenario: A third party's service is refused
- **GIVEN** a proposed action of an admitted kind, addressed to a dependency the
  catalogue marks as not owned by the organisation
- **WHEN** the gate is asked whether it may proceed
- **THEN** it is refused, the refusal names the service and says it is outside
  what Argus may touch, and no mutating call is made

#### Scenario: A name the catalogue does not know is refused
- **GIVEN** a proposed action addressed to a name that is neither the alerting
  service nor any dependency the catalogue lists
- **WHEN** the gate is asked whether it may proceed
- **THEN** it is refused rather than attempted

#### Scenario: The alerting service itself is always within the bound
- **GIVEN** a proposed action of an admitted kind, addressed to the service the
  incident is about
- **WHEN** the gate is asked whether it may proceed
- **THEN** the bound does not refuse it, whether or not the catalogue holds an
  entry for that service

## MODIFIED Requirements

### Requirement: A determined mode that nothing in the set answers is refused in its own words
The system SHALL distinguish three silences at the gate. An incident whose
hypothesis names no mode, or whose mode names no action anything could
identify, SHALL be refused as a mitigation nobody could propose. An incident
whose mode *is* determined, and which no member of the closed set of generic
mitigations answers, SHALL be refused as a failure this system has no
mitigation for. An incident with an action that was proposed and addressed
outside what Argus may touch SHALL be refused as an action outside its reach.

The distinction SHALL be published on the refusal and SHALL reach the candidate's
own row, the timeline and the postmortem in words a reader can act on: the first
says somebody has to work out what to do, the second says somebody outside this
system has to do it, and the third says Argus knew what to do and was not
permitted to do it there.

Which of the three a refusal is SHALL be answered by the policy that holds the
set of mitigations and the bound on what may be addressed, not by the gate
keeping a second copy of either.

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

#### Scenario: An action outside the estate is refused in its own words
- **GIVEN** a proposed action of an admitted kind, addressed to a service outside
  the alerting service's estate
- **WHEN** the gate is reached
- **THEN** the refusal recorded and published says the action was outside what
  Argus may touch and names the service, and is distinguishable from both other
  refusals

#### Scenario: The incident escalates either way
- **GIVEN** any of the three refusals
- **WHEN** no further candidate remains to try
- **THEN** the incident ends escalated, with a postmortem, and no action taken
