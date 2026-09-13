# slack-test-double Specification

## Purpose

Covers the stand-in for the Slack Web API that lets the real Slack adapter be
tested with no workspace and no token, the control seam that empties its
recording and decides what it answers next, and the nightly contract test that
keeps its answers the answers Slack gives.

## Requirements

### Requirement: A test double serves the Slack API Argus writes to
The system SHALL provide a server accepting the Slack Web API methods the
Communicator calls, in Slack's request shape, answering in Slack's response
shape, so that the production Slack adapter can be exercised against it
unmodified. The adapter SHALL reach the double by configuration alone - the
client's base URL - and SHALL contain no branch distinguishing the double from
Slack.

#### Scenario: The real adapter runs unmodified against the double
- **GIVEN** the Slack client configured with the double's base URL
- **WHEN** the Communicator opens an incident's war room
- **THEN** the call succeeds and returns a message reference, having used the
  same code path it uses against Slack

### Requirement: The double records what it was asked to post
The system SHALL make every message it accepted readable - its channel, its
text, and the thread it was a reply to - so that a test can assert what a
human would have seen rather than that a call was made.

#### Scenario: A posted message can be read back
- **GIVEN** an incident walked against the double
- **WHEN** the double is asked what was posted
- **THEN** the opening message, the thread replies against it, and the closing
  message are all readable, each with its channel

#### Scenario: A reply is recorded against its parent
- **GIVEN** a war-room message and an update replying to it
- **WHEN** the double is asked what was posted
- **THEN** the update is recorded as a reply to that message, not as a channel
  message

### Requirement: The double's next answer can be seeded
The system SHALL expose a control interface, separate from the API routes it
serves, that empties what it has recorded and determines what it answers next -
including a refusal, a rate limit, and a channel it does not know.

#### Scenario: A seeded refusal is returned
- **GIVEN** the double seeded to refuse the next post
- **WHEN** the Communicator posts
- **THEN** it receives Slack's refusal shape, not a transport error

#### Scenario: The recording is emptied between tests
- **GIVEN** a double holding messages from an earlier test
- **WHEN** the control interface is asked to reset
- **THEN** it records nothing from before that point

### Requirement: The double is dev-only and keyless
The double SHALL be a development dependency, SHALL NOT be depended on by any
module that ships, and SHALL require no Slack credential to run. Every
push-triggered job SHALL exercise the adapter against it rather than against
Slack.

#### Scenario: No token is needed to run the suites
- **GIVEN** an environment holding no Slack credential
- **WHEN** the replayed end-to-end suite runs
- **THEN** it passes, having posted every message to the double

### Requirement: A contract test keeps the double honest
The system SHALL verify against the real Slack workspace that a call answered
by the double is answered the same way by Slack - the success shape, and the
refusals the double is seeded to produce.

That verification SHALL run nightly rather than on a push, and SHALL NOT gate a
push. Slack costs nothing to call, so the reason the Anthropic contract test is
manual does not apply here; what does apply is that a check standing on a third
party fails when the third party does, and a push held up by somebody else's
outage is a push held up for nothing about the code. A day is soon enough to
learn that a recorded answer no longer matches the service that gave it.

It SHALL be selectable on its own, without running the contract tests that
spend money. One session that ran both would make the free check unrunnable on
a timer and the paid one unavoidable.

Where the workspace credential is absent the verification SHALL report that it
could not be made rather than pass. A contract test that quietly skips is a
contract nobody is checking, reported as one that holds.

#### Scenario: The double's success shape is Slack's
- **WHEN** the same post is made against Slack and against the double
- **THEN** both answers carry the fields the adapter reads, in the same shapes

#### Scenario: The double's refusal is Slack's refusal
- **GIVEN** a channel Slack does not know
- **WHEN** the post is made against Slack and against the double seeded to
  refuse it
- **THEN** both refuse in the same shape, and the adapter treats them alike
