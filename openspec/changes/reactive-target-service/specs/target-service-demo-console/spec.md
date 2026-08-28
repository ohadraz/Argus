## ADDED Requirements

### Requirement: The scenario catalog is available over the control API
The Target Service SHALL expose, under its scenario-control route prefix, a
catalog of the scenarios it can run - each with its id and a human-readable
description of the incident it stages - so that a UI can offer them without
hardcoding the registry.

#### Scenario: The catalog lists every scenario
- **WHEN** the scenario catalog is requested
- **THEN** it returns every scenario in the registry, each with its id and a
  description

#### Scenario: The catalog reports which scenario is active
- **GIVEN** a scenario is active
- **WHEN** the scenario catalog is requested
- **THEN** the response identifies which scenario is currently active

### Requirement: The Target Service serves an operator console
The Target Service SHALL serve a page showing the scenario catalog, a control to
apply a chosen scenario, and the service's own current metric buckets and log
lines. The page SHALL refresh what it displays without a manual reload, so an
incident can be watched as it develops and recovers.

#### Scenario: A scenario can be applied from the page
- **GIVEN** the console is open and no scenario is active
- **WHEN** a scenario is chosen and applied
- **THEN** that scenario becomes active, as the scenario status reports

#### Scenario: The page shows the incident developing
- **GIVEN** the `feature-flag-toggle` scenario has been applied from the console
- **WHEN** the page refreshes its data
- **THEN** the displayed metrics show the elevated error rate and the displayed
  log lines show the failures

#### Scenario: The page shows recovery
- **GIVEN** an incident is being displayed and the flag is then turned off
- **WHEN** the page refreshes its data
- **THEN** the displayed error rate falls, without the page being reloaded

#### Scenario: Current flag state is visible
- **WHEN** the console is open
- **THEN** it shows whether the flag is currently on, so a scenario left running
  from an earlier session is visible rather than mysterious

### Requirement: The Target Service does not depend on Argus
The Target Service's server SHALL contain no reference to Argus and no
configuration naming it. Where the console triggers an alert to Argus, the
request SHALL be made by the page in the browser, not by the Target Service.

#### Scenario: Alerting Argus is a browser-side action
- **GIVEN** the console offers to trigger an alert for the applied scenario
- **WHEN** that alert is triggered
- **THEN** the request to Argus originates from the browser, and the Target
  Service makes no request to Argus
