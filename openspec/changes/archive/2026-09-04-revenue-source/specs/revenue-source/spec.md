## ADDED Requirements

### Requirement: Revenue is read from the payment provider through its own SDK
The system SHALL read revenue through the payment provider's published client
library, aimed by configuration at whichever host is to answer it. A
deployment SHALL be able to point that library at a stand-in without any code
path differing from the one a real account takes.

#### Scenario: The same code path serves a stand-in and a real account
- **WHEN** the revenue adapter is configured with a base address
- **THEN** the provider's own client library is used against that address, and
  no request is built by hand

#### Scenario: No credential is invented
- **GIVEN** a deployment with no payment credential configured
- **WHEN** revenue is read
- **THEN** the source reports that it could not answer, and no request is sent
  under a fabricated credential

### Requirement: Revenue is what was taken and kept, over the window asked for
The system SHALL count charges that succeeded within the window and SHALL
subtract refunds issued within it. Charges that failed or are still pending
SHALL NOT be counted, because they are not revenue.

#### Scenario: A refund during the window reduces the figure
- **GIVEN** a window containing one succeeded charge and a later refund of part
  of it
- **WHEN** revenue is read for that window
- **THEN** the figure is the charge less the refund

#### Scenario: A failed charge is not revenue
- **GIVEN** a window containing a failed charge
- **WHEN** revenue is read for that window
- **THEN** the failed charge does not appear in the figure

### Requirement: The provider is reported in the currencies it was paid in
The system SHALL report an amount per currency, and SHALL NOT reduce several
currencies to one figure at this boundary. A payment provider holds no
cross-currency total, and inventing one here would hide the rate it rested on
from the document that has to disclose it.

#### Scenario: Two currencies are answered as two amounts
- **GIVEN** a window in which the shop was paid in two currencies
- **WHEN** revenue is read
- **THEN** the answer carries an amount for each, each named by its currency

#### Scenario: A quiet window is answered as nothing taken
- **GIVEN** a window in which no charge succeeded
- **WHEN** revenue is read
- **THEN** the answer is that nothing was taken, which is distinguishable from
  the source being unreadable

### Requirement: The provider's vocabulary stops at the adapter
The system SHALL NOT let the payment provider's names, object shapes or
credentials appear above the revenue port. Nothing that consumes revenue SHALL
be able to tell which provider answered.

#### Scenario: The consumer sees amounts and currencies only
- **WHEN** the postmortem reads revenue
- **THEN** what it receives is amounts and currencies over a window, carrying
  no provider identifier, object type or credential
