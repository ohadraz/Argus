## ADDED Requirements

### Requirement: What the platform restarts is derived from the service being restarted
The system SHALL derive the resource the platform is asked to restart from the
service the action addresses, and SHALL NOT hold one resource name configured
for the whole estate. A restart addressed to a service other than the one the
alert names SHALL reach that service's resource, not the alerting service's.

A configured single name was correct while the environment held one service, and
is the shape that would silently restart the wrong thing the moment it held two.

#### Scenario: Two services restart their own resources
- **GIVEN** an estate of two services
- **WHEN** each is restarted in turn
- **THEN** each call names that service's own resource

## MODIFIED Requirements

### Requirement: A restart is verified by the reclaim, not only by recovery
The system SHALL confirm a restart took effect by reading back a change in the
process start time **of the service that was restarted**, and SHALL judge
whether it helped by whether the alerting service's symptoms eased - its
resource use, its latency, and whatever else the incident departed on. The two
are separate questions asked of two services when those differ: a restart that
did not happen and a restart that happened and did not help are different
outcomes, and a system that read only the symptoms would report the first as the
second.

The start time SHALL be read per service, so that restarting a dependency cannot
be confirmed by observing the service that was paged.

#### Scenario: A restart that never landed is distinguished from one that did not help
- **GIVEN** a restart whose call returned without error
- **WHEN** the metrics after it are read and the restarted service's process
  start time is unchanged
- **THEN** the outcome recorded is that the restart did not take effect, not
  that it failed to help

#### Scenario: A restart that reclaimed memory and eased the symptoms is confirmed
- **GIVEN** a restart after which the restarted service's process start time
  changed, memory returned to its baseline and latency eased
- **WHEN** the verdict is measured
- **THEN** the mitigation is confirmed

#### Scenario: A dependency's restart is confirmed against that dependency
- **GIVEN** a restart addressed to a service other than the one the alert names
- **WHEN** the restart is confirmed
- **THEN** the process start time read is the restarted service's, and an
  unmoved start time on the alerting service does not report the restart as
  having failed
