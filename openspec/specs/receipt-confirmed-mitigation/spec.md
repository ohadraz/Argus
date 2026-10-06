# receipt-confirmed-mitigation Specification

## Purpose
Judging an action by its own answer where that answer states what the action
changed. A third way an attempt is settled, beside a level falling back and a
reading existing again - and the only one that does not wait for the service to
answer for the action. What keeps it from confirming everything is the question
asked of the window first: whether it holds a departure to have recovered from
at all, since a rule that only measures levels calls every minute of a flat
window recovered. Which of the three rules settled an attempt is recorded,
because a receipt is a weaker claim than a service getting better.
## Requirements
### Requirement: An action that reports what it changed is judged by that report

The system SHALL confirm an action from the action's own answer where that answer
states what the action changed, and SHALL NOT wait on the service's window to
confirm it.

This is a third way an action is judged, beside the two already built: levels
falling back towards a baseline, and readings existing again where the minutes were
never published. Both of those watch the service. This one reads the thing that was
changed, and it is available only where the action's answer is a statement about
the world rather than an acknowledgement of a request - a count of keys removed,
not a 202.

#### Scenario: A discard is confirmed by its count
- **GIVEN** a discard of named cache entries that returned a count
- **WHEN** the attempt is judged
- **THEN** it is confirmed from that count, with no wait on the metrics window

#### Scenario: An acknowledgement is not a receipt
- **GIVEN** an action whose answer states only that the request was accepted
- **WHEN** the attempt is judged
- **THEN** it is not confirmed from that answer

### Requirement: Whether a window holds a departure to have recovered from is asked, not assumed

The system SHALL offer a predicate answering whether a window contains a departure
for a recovery to be measured against, SHALL ask it before asking whether the service
has recovered, and SHALL share the arithmetic that decides which minutes count with
the questions already asked of the same window.

The recovery predicate holds that a window with no departure has nothing to have
recovered from, so every minute in it counts as recovered. That is right for the only
caller it has ever had - an incident reached by way of a measured onset - and its
precondition is documented, unenforced and unaskable. The defect is the unaskability:
left alone, the first action taken inside a flat window is confirmed on the first poll
whatever it was, and a restart that reached nothing closes the incident as mitigated
with every page still wrong.

This is the mechanism the module has already chosen once, for the conflation between
a service that has not come back and a service nobody watched: a separate honest
predicate asked first, sharing the index arithmetic so the two cannot disagree about
which minutes are *since*. The recovery predicate SHALL keep its signature and its
meaning, and SHALL NOT be taught the onset's provenance or the kind of action taken -
both belong to layers above a metrics rule.

#### Scenario: A flat window reports no departure to judge
- **GIVEN** a window whose minutes are all present and none of which departs
- **WHEN** the predicate is asked
- **THEN** it answers that there is no departure to have recovered from

#### Scenario: A window with a departure reports one
- **GIVEN** a window holding a departure before the moment asked about
- **WHEN** the predicate is asked
- **THEN** it answers that there is, and the recovery question is asked as it always
  was

#### Scenario: The two questions agree about which minutes count
- **GIVEN** any window and any moment
- **WHEN** both predicates are asked about it
- **THEN** both consider the same minutes, because both derive them from the same
  arithmetic

### Requirement: A flat window may not confirm an action that carries no receipt

The system SHALL treat an attempt as unconfirmed where the window holds no departure
to have recovered from and the action performed reports nothing about what it changed,
unless the alert rule that paged judges the attempt, in which case the window reaches no
verdict of its own.

#### Scenario: A restart in a flat window is not confirmed
- **GIVEN** an incident whose onset the alert stated and whose window is flat
  throughout
- **WHEN** a restart is performed and the window is read afterwards
- **THEN** the attempt is not confirmed, and the walk is free to try its next
  candidate

#### Scenario: A discard in the same window is confirmed
- **GIVEN** the same incident
- **WHEN** a discard of named entries is performed and returns a count
- **THEN** the attempt is confirmed

#### Scenario: A measured onset is judged by the levels where no rule judges it
- **GIVEN** an incident whose onset was measured from its own series, and whose alert
  names no rule that paged
- **WHEN** any action is performed
- **THEN** the levels decide, whether or not the action carries a receipt

#### Scenario: A rule that paged judges in place of the window
- **GIVEN** an incident whose alert names the rule that paged
- **WHEN** any action is performed
- **THEN** the rule decides, and the window only dates the recovery

### Requirement: Which rule judged an attempt is recorded

The system SHALL record which of the four judgements settled an attempt, so that a
reader of the incident can tell a rule that stopped firing from a level that came down,
from a reading that returned, from an action that reported its own effect.

An attempt confirmed by a receipt is a weaker claim than one confirmed by a service
getting better, and the record SHALL not let the two read alike. What a receipt
establishes is that the change was made; what makes that sufficient here is the
nature of the change, which the incident's account states rather than implies.

#### Scenario: The record says the receipt settled it
- **GIVEN** an attempt confirmed from a discard's count
- **WHEN** the attempt is read back
- **THEN** it says it was confirmed by what the action reported, and what that
  report was

#### Scenario: The record says the levels settled it
- **GIVEN** an attempt confirmed by a series falling back
- **WHEN** the attempt is read back
- **THEN** it says so

#### Scenario: The record says the rule settled it
- **GIVEN** an attempt confirmed by the rule that paged stopping firing
- **WHEN** the attempt is read back
- **THEN** it says the rule that paged stopped firing

### Requirement: A receipt confirms the change and never the cause

The system SHALL treat an attempt confirmed by a receipt as mitigating the incident
and never as resolving it.

A receipt says a change was made. It says nothing about why the change was needed,
and it cannot say that the condition which produced the divergence is gone - so an
incident ended this way has the same thing owed afterwards as every other mitigated
one.

#### Scenario: A receipt-confirmed incident is mitigated
- **GIVEN** an attempt confirmed by a receipt
- **WHEN** the incident's status is derived
- **THEN** it is `MITIGATED`

#### Scenario: What remains is said
- **GIVEN** an incident confirmed by a receipt
- **WHEN** what it is about is reported
- **THEN** it says what was changed and what was not

