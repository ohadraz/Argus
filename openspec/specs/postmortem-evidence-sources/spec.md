# postmortem-evidence-sources

## Purpose

Covers the two ports the Postmortem agent reads through - revenue in a window,
and responder timings - defined by what the agent needs rather than by what any
provider offers, so an adapter satisfies a seam that already exists.

## Requirements

### Requirement: Revenue is read as an amount over a window
The system SHALL obtain the revenue taken by the service over a stated window,
as an amount per currency taken in, without naming any payment provider above
the port. A single currency is the ordinary case and not the guaranteed one: a
shop paid in two currencies has two amounts and no total, and a port promising
one figure would have to invent the rate that produced it. The port SHALL NOT
take a service argument: revenue is account-wide, and the estimate reads it
twice - once for a calm window, once for the incident - rather than narrowing
it to a path.

#### Scenario: A window is answered with an amount
- **WHEN** revenue is requested for a window
- **THEN** the answer is an amount and the currency it is in

#### Scenario: A window in two currencies is answered with both
- **GIVEN** a window in which the service was paid in two currencies
- **WHEN** revenue is requested for it
- **THEN** the answer carries both amounts, each named by its currency, and
  no total across them

#### Scenario: Nothing above the port names a provider
- **WHEN** the postmortem reads revenue
- **THEN** it does so in terms of a window and an amount, with no provider's
  vocabulary crossing the port

### Requirement: Responder timings are read as when people engaged
The system SHALL obtain, for one incident, when a person first acknowledged it,
when they were done, and how many people responded - without naming any
incident-management provider above the port.

#### Scenario: Engagement is answered for an incident
- **WHEN** responder timings are requested for an incident
- **THEN** the answer carries when a person first engaged, when engagement
  ended, and how many people responded

### Requirement: A source that cannot answer says so, and is never read as an absence
The system SHALL distinguish a source that could not be reached from a source
answering that there was nothing. A failure to read SHALL NOT be presented as
zero revenue or as nobody having responded.

#### Scenario: Unavailability is distinguishable from nothing
- **GIVEN** a source that cannot be reached
- **WHEN** it is read
- **THEN** the caller can tell that from a source that answered with nothing
