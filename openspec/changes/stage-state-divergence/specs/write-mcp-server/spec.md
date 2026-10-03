## ADDED Requirements

### Requirement: The write server can discard named cache entries

The write server SHALL expose a tool that discards a named set of cache entries and
answers with how many of them were removed.

It takes the keys and nothing else that identifies them: no service, no shopper, no
pattern. A tool taking a pattern would be a tool whose blast radius its caller
cannot state, and one taking a service would be one that composed keys from a
format the server holds - which is the service's own and not the server's.

#### Scenario: Named entries are discarded
- **GIVEN** a cache holding the entries a call names
- **WHEN** the tool is called with those keys
- **THEN** they are removed and the number removed is returned

#### Scenario: The tool takes no pattern
- **GIVEN** the tool's schema
- **WHEN** it is read
- **THEN** it accepts a list of keys, and nothing that could match keys it was not
  given

#### Scenario: A cache that could not be reached is reported as such
- **GIVEN** a cache endpoint nothing is listening on
- **WHEN** the tool is called
- **THEN** it reports a platform that could not be reached, apart from an action
  that failed, exactly as the other write tools do

### Requirement: The first write tool that reaches a datastore declares that it does

The write server SHALL state, in the tool's own description, that this write reaches
the cache directly rather than through the deployment platform.

Every other write in this tier goes to a control plane or a flag provider, and a
reader of the tool list is entitled to know that one of them does not. No control
plane offers this write: the platform's built-in resource actions reach a workload's
lifecycle and its size, and none of them reaches what a cache holds.

#### Scenario: The description says where the write goes
- **GIVEN** the tool's description as the model reads it
- **WHEN** it is read
- **THEN** it says the write is issued to the cache itself

### Requirement: The discard is a typed function on the client package

The write client SHALL expose the discard as a typed function taking the keys and
returning the count removed, as every other write tool is exposed.

#### Scenario: The client exposes it as a function
- **GIVEN** the write client package
- **WHEN** the discard is called
- **THEN** it is called as a typed function, with the keys as a sequence and the
  count as its result
