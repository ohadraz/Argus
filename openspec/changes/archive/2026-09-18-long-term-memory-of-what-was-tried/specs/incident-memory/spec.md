## ADDED Requirements

### Requirement: An incident that ends is remembered by what was done to it

When an incident reaches a terminal state, the system SHALL write one record of
it to long-term memory. The record SHALL carry the incident's identity, the text
describing what the incident looked like, and every action taken on it with the
outcome that action reached.

Every incident that ends is recorded, not only a resolved one. An incident that
was escalated after three refuted attempts is the more valuable record of the
two: it says what does not work, which nothing in a later incident's own
evidence can supply.

#### Scenario: A resolved incident is recorded with its confirmed action

- **GIVEN** an incident resolved by one confirmed action
- **WHEN** it reaches its terminal state
- **THEN** one record is written naming that action, its subject, and that it
  was confirmed

#### Scenario: An escalated incident is recorded with its refutations

- **GIVEN** an incident escalated after two actions were taken and refuted
- **WHEN** it reaches its terminal state
- **THEN** one record is written naming both actions and that each was refuted

#### Scenario: An incident with nothing determined is not recorded

- **GIVEN** an incident that ended with no action reaching a determined outcome
- **WHEN** it reaches its terminal state
- **THEN** no record is written, because the record's whole content is what
  attempts reached

### Requirement: The record is derived from the incident record, not from prose

The memory record SHALL be built from the incident's stored actions and their
outcomes, and from the alert that opened it. It SHALL NOT be built from the
postmortem document or from any other generated text, and its creation SHALL NOT
depend on a postmortem having been written.

A postmortem is a document for a human to read; a memory record is a fact for a
later walk to consult. Deriving the second from the first would make an
unwritten or partial document into missing memory.

#### Scenario: A memory record is written where no postmortem exists

- **GIVEN** an incident that ended without a postmortem document being stored
- **WHEN** it reaches its terminal state
- **THEN** its memory record is written all the same

#### Scenario: The recorded actions match the stored actions

- **GIVEN** an incident with three stored actions, two refuted and one confirmed
- **WHEN** its memory record is written
- **THEN** the record names exactly those three, with those outcomes

### Requirement: Writing a memory record is a step of its own

The memory record SHALL be written by a step of the walk that does nothing else.
It SHALL NOT be written by the step that produces the postmortem, and a failure
to write it SHALL NOT prevent the postmortem from being stored, nor the reverse.

#### Scenario: A failed memory write leaves the postmortem intact

- **GIVEN** an incident whose memory store cannot be reached
- **WHEN** the incident ends
- **THEN** the postmortem is stored, the incident still reaches its terminal
  state, and the timeline records that the memory could not be written

### Requirement: Memory is searched by what the incident looked like

A search SHALL take the text describing an incident and return past records
ordered by similarity to it, most similar first. The search SHALL be able to
narrow to records sharing stated metadata before ranking by similarity, so that
a small corpus is not ranked on similarity alone.

Similarity rather than an exact match on the alert's name, because one cause
raises differently-named alerts on different days, and two alerts that mean the
same thing are rarely spelled the same way.

#### Scenario: A differently-worded alert still matches

- **GIVEN** a stored record whose incident was described as a checkout error
  spike
- **WHEN** memory is searched with text describing elevated checkout failures
- **THEN** that record is returned

#### Scenario: Results come back most similar first

- **GIVEN** three stored records of differing similarity to a search
- **WHEN** memory is searched
- **THEN** they are returned in descending order of similarity

#### Scenario: An empty corpus returns nothing rather than failing

- **GIVEN** a memory store with no records
- **WHEN** it is searched
- **THEN** an empty result is returned and the caller proceeds

### Requirement: Memory never blocks an incident

A memory store that is unreachable, slow past its bound, or empty SHALL be
treated as a store that returned nothing. Neither a failed search nor a failed
write SHALL escalate an incident, end a walk, or prevent an action from being
taken.

Memory is an advantage, not a dependency: every decision it informs has an
answer without it, and an incident that stalled because a cache of old incidents
was down would be a worse system than one with no memory at all.

#### Scenario: An unreachable store does not stop the walk

- **GIVEN** an incident mid-walk and a memory store that cannot be reached
- **WHEN** the walk consults memory
- **THEN** it proceeds exactly as it would with an empty result, and the
  incident is not escalated on that account

### Requirement: Memory can be switched off

A deployment SHALL be able to disable long-term memory, and with it disabled the
system SHALL neither write records nor consult them, and SHALL behave in every
other respect as it does with an empty store.

Two configurations that differ in exactly one thing are what let the benchmark
(§21) say whether memory is worth its cost.

#### Scenario: Disabled memory writes nothing

- **GIVEN** a deployment with memory disabled
- **WHEN** an incident ends
- **THEN** no record is written

#### Scenario: Disabled memory is not consulted

- **GIVEN** a deployment with memory disabled and a store holding records
- **WHEN** an incident is walked
- **THEN** memory is not searched, and the walk's decisions are those it would
  make with no records at all
