# engagement-source

## Purpose

Covers the adapter behind the Postmortem's engagement port: what it counts as
human attention on an incident, the titles it reports the responders by, and
that the on-call provider's vocabulary and credential stop at it.

## Requirements

### Requirement: On-call is read through the provider's own SDK
The system SHALL read responder engagement through the on-call provider's
published client library, aimed by configuration at whichever host is to answer
it. A deployment SHALL be able to point that library at a stand-in without any
code path differing from the one a real account takes.

#### Scenario: The same code path serves a stand-in and a real account
- **WHEN** the engagement adapter is configured with a base address
- **THEN** the provider's own client library is used against that address, and
  no request is built by hand

#### Scenario: No credential is invented
- **GIVEN** a deployment with no on-call credential configured
- **WHEN** engagement is read
- **THEN** the source reports that it could not answer, and no request is sent
  under a fabricated credential

### Requirement: Engagement is person-minutes, from when each person took it
The system SHALL report engagement as the sum, over the people who
acknowledged the incident, of the time from each one's own acknowledgement
until the incident ended. It SHALL NOT report the incident's whole length as
engagement, and SHALL NOT report one span for several responders. A responder
who acknowledged more than once SHALL be counted from their earliest
acknowledgement.

#### Scenario: The wait before a responder acknowledged is not their engagement
- **GIVEN** an incident acknowledged some time after it began
- **WHEN** engagement is read
- **THEN** the minutes reported start at the acknowledgement, not at the
  incident's start

#### Scenario: Two responders spent two people's time
- **GIVEN** an incident two people acknowledged, at different moments
- **WHEN** engagement is read
- **THEN** the minutes reported are both of their spans added together

#### Scenario: Distinct acknowledgers are counted once each
- **GIVEN** an incident acknowledged by two people, one of them twice
- **WHEN** engagement is read
- **THEN** two responders are reported

### Requirement: An unattended incident is answered, not left unanswered
The system SHALL answer an incident nobody acknowledged as no engagement - no
minutes and no responders - and SHALL reserve "could not say" for a provider
that could not be read. An incident that resolved with nobody looking at it is
a measurement.

#### Scenario: Nobody acknowledged
- **GIVEN** an incident with no acknowledgement
- **WHEN** engagement is read
- **THEN** the answer reports no minutes and no responders

#### Scenario: The provider could not be reached
- **GIVEN** an on-call provider that cannot be reached
- **WHEN** engagement is read
- **THEN** the source reports that it could not say, distinguishably from
  nobody having engaged

### Requirement: The title a responder held is read from the provider
The system SHALL obtain the job title the on-call provider holds for each
distinct responder and SHALL carry those titles on the answer. A responder
whose title cannot be read SHALL NOT invalidate the answer: the minutes and the
count stand, and that title is absent.

#### Scenario: Titles accompany the count
- **GIVEN** an incident acknowledged by a person whose provider record names a
  job title
- **WHEN** engagement is read
- **THEN** the answer carries that title

#### Scenario: A title that cannot be read is absent, not fatal
- **GIVEN** an incident acknowledged by a person whose record cannot be read
- **WHEN** engagement is read
- **THEN** the minutes and the responder count are still reported, without that
  title

### Requirement: The provider's vocabulary stops at the adapter
The system SHALL NOT let the on-call provider's names, object shapes or
credentials appear above the engagement port. Nothing that consumes engagement
SHALL be able to tell which provider answered, and no responder SHALL be
identified by name or address above the port.

#### Scenario: The consumer sees minutes, a count and titles only
- **WHEN** the postmortem reads engagement
- **THEN** what it receives is minutes, a number of responders and their
  titles, carrying no provider identifier, object type, credential, or
  responder's name or address
