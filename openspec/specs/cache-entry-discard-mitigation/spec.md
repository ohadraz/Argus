# cache-entry-discard-mitigation Specification

## Purpose
Answering a derived copy that stopped agreeing with its records by throwing
the copy away. The sixth generic mitigation, and the first that removes
something rather than restoring, adding or stopping something - admissible for
the reason every other member is, membership of the declared set, and
defensible because nothing is lost: the records it was derived from are
untouched and the service rebuilds each figure on the next read. The entries
are addressed by keys the evidence carried, never composed and never routed
through a model's prose, and the action owes no undo because writing the stale
figures back would recreate the incident.
## Requirements

### Requirement: A sixth generic mitigation discards the entries that diverged

The system SHALL answer a determined `state-divergence` by discarding the cache
entries the evidence named, and that action's kind SHALL belong to the declared set
of generic mitigations.

It is the first member that neither restores, adds nor stops something: it removes
a copy. What makes it admissible is unchanged from every other member - membership
of the declared set - and what makes it defensible is that nothing is lost.
The authority the copy was derived from is untouched, the service recomputes from
it by design, and what is gone cannot be stale.

#### Scenario: A state divergence is answered by discarding entries
- **GIVEN** a candidate determining `state-divergence` and naming stale entries
- **WHEN** a mitigation is proposed
- **THEN** the proposed action is a discard of those entries

#### Scenario: The gate takes it without asking
- **GIVEN** a proposed discard of named cache entries
- **WHEN** the gate is asked whether it may proceed
- **THEN** it proceeds, because the kind is a declared generic mitigation

### Requirement: The entries discarded are the ones the evidence named, never every entry

The system SHALL discard a named set of entries and SHALL NOT discard a whole cache
or database.

One reason, and it is sufficient: the set of entries proved wrong is known, so a
wider discard is a change Argus has no evidence for and cannot account for. Entries
nothing proved wrong are left alone.

#### Scenario: Only the named entries go
- **GIVEN** a cache holding more entries than the evidence named
- **WHEN** the discard is performed
- **THEN** exactly the named entries are removed, and every other entry is left as it
  was

#### Scenario: A discard of everything is not available
- **GIVEN** any state divergence, however many entries it affects
- **WHEN** the action is built
- **THEN** it addresses entries by name, and no action in the set empties a cache

### Requirement: The keys travel as data, never through the diagnosis

The system SHALL carry the keys from the evidence that named them to the action
that discards them without routing them through a model's conclusion.

A hypothesis is prose. A list of exact strings asked to arrive through prose arrives
abbreviated, elided or invented, and the model's part in this is to say which mode the
incident is - not to be the courier for addresses it cannot shorten safely.

They SHALL also never be rendered into a prompt. The model reads how many figures
disagree, out of how many, by how much and over how many purchases, and the dates -
not which keys they are. A list of addresses re-rendered on every round of a walk is
token spend for no decision it informs, and a later change that helpfully included
them would otherwise be invisible.

#### Scenario: The strategy is handed the keys
- **GIVEN** evidence naming a set of stale cache keys
- **WHEN** the mitigation for `state-divergence` is proposed
- **THEN** the keys the action carries are the keys the evidence carried, exactly
  and entirely

#### Scenario: No key is rendered to the model
- **GIVEN** an alert and a set of findings carrying stale keys
- **WHEN** everything the model is sent during the walk is read
- **THEN** no key appears in any of it

#### Scenario: A diagnosis naming no keys proposes nothing
- **GIVEN** a candidate determining `state-divergence` where no evidence named a
  stale entry
- **WHEN** a mitigation is proposed
- **THEN** no action is proposed, and the refusal says the mode has an answer that
  this diagnosis did not say what to apply it to

#### Scenario: Keys are never derived
- **GIVEN** a shopper named in the evidence and no key given for them
- **WHEN** the action is built
- **THEN** no key is composed from a format held by Argus

### Requirement: The discard needs no undo, and withdrawal says so

The system SHALL record that this action's change cannot and need not be put back,
and a withdrawal of an incident mitigated this way SHALL say that rather than
report an undo it did not perform.

There is nothing to restore. The entries were a copy of data that never moved, and
the service has already rebuilt the ones anybody asked for. An undo descriptor
promising to write the stale figures back would be promising to recreate the
incident.

#### Scenario: An undo is not attempted
- **GIVEN** an incident mitigated by a discard
- **WHEN** it is withdrawn
- **THEN** no write is made to the cache, and the record says the discard needed no
  undo

#### Scenario: The refuted path does not put entries back either
- **GIVEN** a discard whose candidate is later refuted
- **WHEN** the attempt is unwound
- **THEN** nothing is written back, and the record says why

### Requirement: What is left afterwards is not a patch to the service

The system SHALL report this mode as mitigated rather than resolved, and SHALL
account for what remains: the replication that let a copy fall behind, and the
promotion that made the behind copy the one being served.

`RESOLVED` is unreachable here for a structural reason rather than a circumstantial
one - it means the permanent fix is merged, which Argus does not reach on its own by
construction. What remains is a recurrence path and not a refill one: nothing
upstream is pushing stale values into a promoted primary, and what is untouched is
that a cache which can promote a lagging replica will do it again.

The set also goes on growing while the incident is open, so a discard holds the same
position a restart holds against a leak: it clears what accumulated, and time starts
adding more. The record SHALL say the keys discarded were those a check found at one
minute.

Nothing in the service's own source is at fault, so there is nothing for a code
fix to turn green - as with an internal dependency's failure, the thing to put
right is outside the repository Argus was pointed at.

#### Scenario: The incident ends mitigated
- **GIVEN** a discard that was performed and confirmed
- **WHEN** the incident's status is derived
- **THEN** it is `MITIGATED`, not `RESOLVED`

#### Scenario: The account names the cause that is still there
- **GIVEN** an incident mitigated by a discard
- **WHEN** what it is about is reported
- **THEN** it says the stale copy is gone and the replication that filled it is
  unchanged
