# anthropic-test-double Specification

## Purpose
Covers the record/replay stand-in for the Anthropic Messages API that lets the
real adapter be tested with no key and no spend, the control seam that decides
what it returns next, and the contract and benchmark tests that keep it honest.
## Requirements
### Requirement: A test double serves the Anthropic Messages API
The system SHALL provide a server that accepts requests in the Anthropic
Messages API's request shape and answers in its response shape, so that the
production LLM adapter can be exercised against it without modification. The
adapter SHALL reach the double by configuration alone - the client's base URL -
and SHALL contain no branch that distinguishes the double from the real API.

#### Scenario: The real adapter runs unmodified against the double
- **GIVEN** the LLM client configured with the double's base URL
- **WHEN** the adapter requests a hypothesis
- **THEN** it receives a valid hypothesis, having used the same code path it
  uses against the real API

### Requirement: The double replays recorded real responses
The system SHALL serve responses recorded from the real Anthropic API rather
than responses composed by hand, so that what the double returns is something
the real service actually returned.

#### Scenario: A recorded response is served back
- **GIVEN** a response previously recorded from the real API
- **WHEN** the adapter makes the request that recording belongs to
- **THEN** the double serves that recorded response

### Requirement: The double's next response can be seeded
The system SHALL expose a control interface, separate from the Messages API
route it serves, that determines what the double returns next - including a
chosen hypothesis, a refusal, a rate-limit error, a server error, and a
response that does not satisfy the requested schema.

#### Scenario: A seeded hypothesis is returned
- **GIVEN** the double seeded with a particular hypothesis
- **WHEN** the adapter requests a hypothesis
- **THEN** that hypothesis is what the adapter returns to its caller

#### Scenario: A malformed response is seeded
- **GIVEN** the double seeded to return a response that violates the requested
  schema
- **WHEN** the adapter requests a hypothesis
- **THEN** the adapter fails in a defined way rather than returning a
  partially-populated hypothesis

#### Scenario: A rate-limit response is seeded
- **GIVEN** the double seeded to return a rate-limit error
- **WHEN** the adapter requests a hypothesis
- **THEN** the adapter surfaces that as a rate-limit failure, not as an
  undetermined cause

### Requirement: Contract tests verify the double still matches the real API
The system SHALL provide tests that issue equivalent requests to both the
double and the real Anthropic API and compare their structure: that both
produce a response parsing into the same hypothesis type, and that both answer
an equivalent malformed request with an equivalent error. These tests SHALL
compare structure and not generated content, since the real model's wording
varies between calls.

#### Scenario: Both produce a parseable hypothesis
- **WHEN** the same evidence is sent to the double and to the real API
- **THEN** both responses parse into a valid hypothesis

#### Scenario: Both reject an equivalent malformed request
- **WHEN** an equivalently malformed request is sent to the double and to the
  real API
- **THEN** both answer with an equivalent error

#### Scenario: A stale recording is reported
- **GIVEN** a recorded response whose structure no longer matches what the real
  API returns
- **WHEN** the contract tests run
- **THEN** they fail, identifying the recording as stale

### Requirement: Benchmark tests check the model's answer against known ground truth
The system SHALL provide tests, separately marked so they do not run on every
commit, that send fixed evidence to the real API and assert the determined
cause type matches the cause that evidence represents. These tests exercise the
prompt rather than the surrounding code.

#### Scenario: A feature flag toggle is identified from its evidence
- **GIVEN** evidence in which a feature flag was toggled shortly before the
  error rate rose
- **WHEN** a hypothesis is requested from the real API
- **THEN** the determined cause type is the feature-flag-toggle cause

#### Scenario: Evidence with no cause in it yields no determined cause
- **GIVEN** evidence containing no change event
- **WHEN** a hypothesis is requested from the real API
- **THEN** no cause type is determined

### Requirement: The double holds a call when a test says so

The double SHALL, after `POST /double-control/hold`, keep the next call to
arrive waiting until `POST /double-control/release`, whatever is queued and
whether or not it is recording. A seed SHALL NOT end a hold. On release the
held call SHALL be answered as a call arriving then would be: by the next
seed, or upstream while recording, or refused. Calls other than the held one
SHALL be answered as without a hold. A release before any call has arrived
SHALL end the hold, so the next call is answered as without one. `reset` SHALL
end a hold, refusing a call held.

#### Scenario: A held call takes the next seed on release

- **GIVEN** a double with responses queued, told to hold
- **WHEN** a call arrives, a response is seeded, and the test releases
- **THEN** the call waits through the seed, and is answered on release with
  the response at the head of the queue

#### Scenario: A hold is honoured while recording

- **GIVEN** a double recording, told to hold
- **WHEN** a call arrives, and the test releases
- **THEN** the call waits, and goes upstream on release

#### Scenario: A released call with nothing queued is refused

- **GIVEN** a call waiting on a hold, with nothing queued and no recording
- **WHEN** the test releases it
- **THEN** the call is refused, as a call with nothing queued is

#### Scenario: A hold released before any call arrives

- **GIVEN** a double told to hold, with a response queued
- **WHEN** the test releases, and then a call arrives
- **THEN** the call is answered at once with the queued response

#### Scenario: No hold

- **GIVEN** a double with nothing queued and no hold
- **WHEN** a call arrives
- **THEN** it is refused at once

