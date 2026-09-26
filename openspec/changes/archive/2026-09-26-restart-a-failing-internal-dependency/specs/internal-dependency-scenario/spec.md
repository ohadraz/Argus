## ADDED Requirements

### Requirement: The shop depends on a pricing service the same organisation owns
The Target Service SHALL render the account page partly from a second internal
service - what the shopper's basket would cost with their current discounts - so
that the dependency sits on the request path in source rather than in a fixture.
The call SHALL be made through a seam the generator can answer without a network
round trip, because the window's metrics are produced by rendering the page many
times a minute.

The dependency SHALL be a service of the same organisation, and the catalogue
SHALL say so - which is what separates this scenario from the payment provider's,
whose entry says the opposite.

#### Scenario: A well pricing service leaves the page as it was
- **GIVEN** the pricing service is answering promptly
- **WHEN** an account page is rendered
- **THEN** the page renders successfully and the shop's latency is its baseline

#### Scenario: The catalogue names it as the organisation's own
- **WHEN** the catalogue is read for the shop
- **THEN** the pricing service is listed as a dependency the organisation owns,
  and the payment provider is listed as one it does not

### Requirement: The scenario's signature is latency alone, with nothing changed
Seeding `pricing-service-degraded` SHALL make the pricing service slow from the
scenario's onset - it answers every call, and takes an order of magnitude longer
to do it. While it is degraded, the generated telemetry SHALL report the median
and both tails above their baselines while the error rate stays at its baseline,
memory stays at its baseline, no flag moves, and the deploy history records no
change.

The shop itself SHALL be well throughout. Nothing in its own code is slow, and
the time every request spends is spent waiting.

#### Scenario: Latency moves and nothing else does
- **GIVEN** the `pricing-service-degraded` scenario has been seeded
- **WHEN** the metrics window is read
- **THEN** minutes from the onset report a p50, p95 and p99 above their
  baselines, with the error rate and memory at theirs

#### Scenario: Nothing internal to the shop accounts for it
- **GIVEN** the `pricing-service-degraded` scenario has been seeded
- **WHEN** the change events and flag history for the window are read
- **THEN** neither reports a change

### Requirement: The shop's own log lines attribute the time to the dependency
Seeding the scenario SHALL produce log lines naming the pricing service, the
host called and how long the call took, so that the incident is readable from
the caller's side alone. No telemetry of the dependency's own SHALL be required
to reach the diagnosis: the coupling is hidden precisely because nobody was
watching the dependency.

#### Scenario: The logs say where the time went
- **GIVEN** the `pricing-service-degraded` scenario has been seeded
- **WHEN** the log lines for the window are read
- **THEN** lines name the pricing service and the time the call took, and the
  time named accounts for the latency the metrics report

### Requirement: Restarting the dependency ends the scenario, and restarting the shop does not
The scenario's condition SHALL be the pricing service's state. Restarting the
pricing service SHALL clear it, and the shop's telemetry SHALL return to its
baseline in the minutes that follow. Restarting the shop, reverting a flag or
rolling the deployment back SHALL leave the telemetry exactly as it was.

This is the property that proves the address is load-bearing: every strategy that
existed before this scenario would have restarted the shop, and the fixture has
to be able to tell that apart from the correct action.

#### Scenario: Restarting the pricing service ends it
- **GIVEN** the scenario is active
- **WHEN** the pricing service is restarted through the platform
- **THEN** the minutes that follow report latency back at its baseline

#### Scenario: Restarting the shop changes nothing
- **GIVEN** the scenario is active
- **WHEN** the shop is restarted
- **THEN** the next minutes report the same raised latency

#### Scenario: A reset ends it
- **GIVEN** the scenario is active
- **WHEN** the scenario is reset through scenario control
- **THEN** no scenario is active and the service serves no telemetry, as it does
  with nothing staged

### Requirement: The pricing service has a process clock of its own
The Target Service SHALL report the pricing service's process start time
through the platform stand-in's view of that application, and SHALL move it when
the pricing service is restarted. A restart of one service SHALL NOT move the
other's.

#### Scenario: Each service reports its own start time
- **GIVEN** a shop and a pricing service that have both been serving for some
  time
- **WHEN** the pricing service is restarted
- **THEN** its process start time moves and the shop's does not

### Requirement: The cause is out of reach, and what the caller can do about it is not
The scenario SHALL leave the cause in a repository this system neither indexes
nor proposes changes to: what became slow is another service's code, and no
change to the shop makes it fast again.

The shop SHALL still have something worth proposing. It calls a dependency on
the render path with no deadline of any kind, so whatever that dependency takes,
the page takes - which is a fault in the caller however well the dependency
behaves. What Argus proposes for this mode is therefore a defence rather than a
repair, and the difference SHALL be readable: the incident's account says the
permanent fix belongs to the dependency's owner, and the proposal bounds the
wait rather than claiming to have fixed the cause.

The proposal SHALL be addressed to the module holding that call. The account
page calls a summary cache as well, belonging to another scenario, and a bound
written there would read perfectly and change nothing about this incident.

#### Scenario: What is proposed bounds the call this incident is about
- **GIVEN** the scenario mitigated by restarting the pricing service
- **WHEN** the walk looks for a permanent fix
- **THEN** what is proposed changes the module holding the unbounded pricing
  call, and not the module holding the summary cache

#### Scenario: The cause is named rather than authored
- **GIVEN** a proposal bounding the caller's wait
- **WHEN** the incident's account is read
- **THEN** it says the fix for the cause belongs to the dependency's owner,
  rather than presenting the bound as having ended the fault
