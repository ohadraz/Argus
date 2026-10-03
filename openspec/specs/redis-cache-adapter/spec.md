# redis-cache-adapter Specification

## Purpose
Reaching a datastore rather than a control plane. The write tier discards
cache entries by issuing `UNLINK` over the protocol Redis publishes, because no
control plane offers this write - a platform's own actions reach a workload's
lifecycle and its size, and none of them reaches what a cache holds. One call
carries every key, the count it returns is the action's whole receipt, and a
cache that could not be reached raises rather than reporting that nothing was
removed.
## Requirements

### Requirement: The write tier reaches a cache over Redis's own protocol

The write tier SHALL discard cache entries by issuing `UNLINK` to a Redis over the
protocol Redis publishes, and SHALL NOT require the service whose cache it is to
expose anything for Argus's benefit.

This is the first write channel that reaches a datastore rather than a control
plane. The reason is that no control plane offers this: Argo CD's built-in resource
actions are `restart`, `scale`, `pause` and `resume`, and none of them touches what
a cache holds. `UNLINK` is a standard command, present since Redis 4.0, and a
responder discarding a stale entry by hand issues exactly it.

#### Scenario: Entries are discarded over the published protocol
- **GIVEN** a Redis holding the entries an action names
- **WHEN** the discard is performed
- **THEN** `UNLINK` is issued for those keys, and nothing is asked of the service
  that wrote them

#### Scenario: No bespoke surface is required of the service
- **GIVEN** any service whose cache is a Redis
- **WHEN** Argus discards entries from it
- **THEN** the only thing relied on is Redis's own command set

### Requirement: `UNLINK` is used rather than `DEL` or `FLUSHDB`

The write tier SHALL issue `UNLINK` with every key in one call.

`UNLINK` unlinks each key in constant time and reclaims the memory on another
thread, so a call naming many keys does not block the shop's own reads while it
runs - which `DEL` would. `FLUSHDB` is not used at all: it discards what nobody
proved wrong, and its scope is a decision Argus has no evidence for.

#### Scenario: One call carries every key
- **GIVEN** an action naming many keys
- **WHEN** the discard is performed
- **THEN** one `UNLINK` is issued naming all of them

#### Scenario: A blocking delete is not used
- **GIVEN** any discard, of any size
- **WHEN** it is performed
- **THEN** the command issued is `UNLINK`

### Requirement: The count returned is the action's receipt

The write tier SHALL return the number of keys `UNLINK` reported removing, and that
figure SHALL be what the action reports having done.

`UNLINK` is synchronous in its answer: the count is the server stating which of the
named keys existed and are now gone. Nothing further is read back - a second `GET`
would be the same server answering about the same keys, and the restart's own
follow-up read exists only because Kubernetes performs a restart asynchronously.

#### Scenario: The count reaches the record
- **GIVEN** a discard whose named keys are all present
- **WHEN** it is performed
- **THEN** the action reports a count equal to the number of keys it named

#### Scenario: Keys already gone are reported as not removed
- **GIVEN** a discard some of whose named keys have already been discarded
- **WHEN** it is performed
- **THEN** the count reported is the number that were still there, and that is not an
  error

#### Scenario: No read-back is issued
- **GIVEN** a discard that returned a count
- **WHEN** the action completes
- **THEN** no further command is issued to confirm it

### Requirement: A cache that could not be reached is reported apart from a discard that removed nothing

The write tier SHALL distinguish a cache it could not reach from a cache that
answered and held none of the named keys, and SHALL raise rather than report a
count where no answer arrived.

The two end differently for whoever picks the incident up. A cache that answered
with nothing is a divergence somebody or something else has already cleared; a
cache that did not answer is a mitigation that did not happen, and anything
downstream treating it as done would read the unchanged shop as evidence against
the diagnosis.

#### Scenario: An unreachable cache raises
- **GIVEN** a cache endpoint nothing is listening on
- **WHEN** a discard is attempted
- **THEN** it raises, naming the endpoint dialled, and no count is reported

#### Scenario: A reachable cache holding nothing reports zero
- **GIVEN** a cache that answers and holds none of the named keys
- **WHEN** the discard is performed
- **THEN** zero is reported as the count, and nothing raises

### Requirement: Where the cache is comes from configuration, and which keys from the evidence

The write tier SHALL take the cache's address from its own settings, as it takes
every endpoint it writes to, and SHALL take the keys from the action it was handed.

The address is a fact about the estate, like the platform's URL and the credential
beside it. The keys are a fact about this incident, and the tier composes none of
them.

#### Scenario: The endpoint is configured
- **GIVEN** a write tier configured with a cache endpoint
- **WHEN** a discard is performed
- **THEN** it is issued to that endpoint

#### Scenario: The keys are not composed
- **GIVEN** an action naming keys
- **WHEN** the discard is performed
- **THEN** the keys issued are exactly those, with nothing prefixed, suffixed or
  derived
