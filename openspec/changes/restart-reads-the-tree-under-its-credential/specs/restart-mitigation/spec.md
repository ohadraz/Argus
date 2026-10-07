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
be confirmed by observing the service that was paged. It SHALL be read under the
same credential the restart was asked for under, and with no credential at all
where none is configured: a platform that answers nothing to a caller it cannot
identify would otherwise leave every restart unconfirmable.

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

#### Scenario: The start time is read under the platform's credential
- **GIVEN** a platform configured with a credential
- **WHEN** the restarted service's process start time is read
- **THEN** the read carries that credential, as the restart itself did
