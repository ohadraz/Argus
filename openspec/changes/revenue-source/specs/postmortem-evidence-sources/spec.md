## MODIFIED Requirements

### Requirement: Revenue is read as an amount over a window
The system SHALL obtain the revenue taken by the service over a stated window,
as an amount per currency taken in, without naming any payment provider above
the port. A single currency is the ordinary case and not the guaranteed one: a
shop paid in two currencies has two amounts and no total, and a port promising
one figure would have to invent the rate that produced it. The port SHALL NOT
take a service argument: revenue is account-wide, and narrowing it to the
affected path is what the estimate's weight already does.

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
