# postmortem-template Specification

## Purpose
What a postmortem says and in what order: Google's example postmortem, with
every fact computed from the incident's record by code and only the prose
written by the model, so a reader can trust each figure without checking it.
## Requirements
### Requirement: The document has one shape

A postmortem SHALL open with a header carrying the incident's full ID, its
title, and two labelled times: **Incident**, the window from onset to recovery
with the alert and the service it fired on, and **Written**, when the document
was composed. Its sections SHALL follow Google's example postmortem in this
order: Summary, Impact, Root cause and contributing factors, Hypotheses
considered, Trigger, Resolution, Detection, Action items, Lessons learned,
Timeline, What people told Argus,
Cost of the response, Supporting information, Review checklist. A section with
nothing to say SHALL say so rather than be left out, except What people told
Argus, which an incident nobody wrote in has none of.

#### Scenario: The header tells the two times apart
- **WHEN** a postmortem is shown
- **THEN** its header names the incident's ID, and labels the incident's window
  and the document's writing time separately

#### Scenario: The sections arrive in order
- **WHEN** a postmortem is shown
- **THEN** its sections appear in the order above

### Requirement: Facts are written by code, prose by the model

The system SHALL compute from the incident's record, and never ask the model
for: every figure, the timeline, detection, trigger, hypotheses considered,
resolution, the action items the record implies, every action item's number,
the links, and the review checks. The model SHALL write only the summary, the
root cause, the causal chain, the contributing factors, the action items it
proposes, and the lessons learned.

#### Scenario: A computed section is unchanged by the answer
- **GIVEN** an incident's record
- **WHEN** two different answers are submitted for it
- **THEN** both documents carry the same timeline, detection, trigger,
  hypotheses, resolution and figures

### Requirement: Impact is measured

Impact SHALL report the duration from onset to recovery, the peak error rate
and the customer loss estimate, each as the measurement already computed for
the postmortem, and each absent with its reason where it could not be measured.

#### Scenario: Impact reads the measurements
- **WHEN** a postmortem is written for an incident with a recorded onset and
  recovery
- **THEN** Impact's duration, peak error rate and loss are the measured ones

### Requirement: Detection says how long the alert took

Detection SHALL state the onset, when the alert fired, which rule fired, and
the gap between the two. Where no onset was recorded it SHALL say so and state
no gap.

#### Scenario: A measured gap
- **GIVEN** an onset at 14:03:00 and an alert at 14:05:40
- **WHEN** the postmortem is written
- **THEN** Detection states a gap of 2m 40s

#### Scenario: No onset, no gap
- **GIVEN** an incident with no recorded onset
- **WHEN** the postmortem is written
- **THEN** Detection says the onset is unknown and states no gap

### Requirement: The trigger is the change the confirmed cause blamed

Trigger SHALL name the change the confirmed candidate blamed - its subject,
the transition where one was recorded, and when the change was made where the
retrieved changes date it. Where no candidate was confirmed, Trigger SHALL say
none was established.

#### Scenario: A confirmed flag change
- **GIVEN** a confirmed candidate blaming a flag that went from off to on
- **WHEN** the postmortem is written
- **THEN** Trigger names the flag, the transition, and the time the change was
  made

#### Scenario: Nothing confirmed
- **GIVEN** an incident whose candidates were all refuted or never tried
- **WHEN** the postmortem is written
- **THEN** Trigger says no trigger was established

### Requirement: Resolution lists what was done, by whom

Resolution SHALL list every action taken, in order, with its time, the action
in the narration's words, who took it, whether it can be undone, and what it
came to, including whether it still stands. A person's resolution SHALL appear
with their name, channel, time and note, read from the record when the
document is shown, since it can arrive after the document was written.

#### Scenario: An action Argus took
- **WHEN** Argus turned a flag off and the recovery was confirmed
- **THEN** Resolution lists it as Argus's, reversible, recovered and still in
  place

#### Scenario: A person resolved it afterwards
- **GIVEN** an escalated incident whose postmortem is written
- **WHEN** a person resolves it and the postmortem is shown
- **THEN** Resolution shows the person's resolution

### Requirement: Every step of the causal chain cites evidence

The prompt SHALL label each piece of evidence it hands the model (`E1`, `E2`,
...). Each step of the causal chain SHALL cite at least one label, and every
label cited SHALL be one the prompt gave. A step that does neither SHALL be a
fault put back to the model. The document SHALL store each step with the
evidence it cited, as the evidence read.

#### Scenario: A step citing nothing
- **WHEN** the model submits a chain step citing no evidence
- **THEN** the submission is refused, naming the step

#### Scenario: A step citing a label never given
- **WHEN** the model cites `E40` and the prompt gave thirty labels
- **THEN** the submission is refused, naming the label

### Requirement: Every contributing factor is answered by an action item

Each contributing factor SHALL name at least one action item by its number,
and every number named SHALL be an action item in the document. A factor that
does neither SHALL be a fault put back to the model.

#### Scenario: A factor nothing answers
- **WHEN** the model submits a contributing factor naming no action item
- **THEN** the submission is refused, naming the factor

### Requirement: Action items are numbered by code and never edited

Action items SHALL be numbered `AI-1`, `AI-2`, ... in this order: the items
the record implies - each action that brought recovery (mitigate, done, owned
by Argus), the proposed fix (prevent, open, tracked by its pull request), the
action Argus recommended and did not take (mitigate, open) - then the model's
proposals. Each SHALL carry a type from mitigate, prevent, detect and process.
An open item SHALL have no owner and no due date. Nothing in Argus edits an
action item after the document is written.

#### Scenario: The record's items come first
- **GIVEN** an incident with a confirmed flag revert, a draft pull request and
  two proposed items
- **WHEN** the postmortem is written
- **THEN** `AI-1` is the revert, done, owned by Argus; `AI-2` is reviewing the
  pull request, open; `AI-3` and `AI-4` are the proposals, open and unowned

### Requirement: Hypotheses considered come from the record

Hypotheses considered SHALL list every candidate the Investigator ranked, with
its confidence and whether it was confirmed, refuted or never tried, from the
record.

#### Scenario: A refuted candidate is listed
- **GIVEN** an incident with one confirmed and two refuted candidates
- **WHEN** the postmortem is written
- **THEN** all three are listed, each with its result

### Requirement: Lessons are learned in three lists

Lessons learned SHALL be three lists written by the model: what went well,
what went wrong, and where the incident got lucky. Each MAY be empty; each
SHALL be present.

#### Scenario: Nothing lucky
- **WHEN** the model submits an empty list for where the incident got lucky
- **THEN** the submission is accepted

### Requirement: The timeline is the narration with four markers

Timeline SHALL be the incident's narration, in order, in UTC, with four
markers placed by code: IMPACT BEGINS at the onset, DETECTED at the alert,
MITIGATED at the first action whose recovery was confirmed, and IMPACT ENDS at
the recovery. A marker whose time is unknown SHALL be left out.

#### Scenario: All four markers
- **WHEN** a postmortem is written for an incident Argus mitigated
- **THEN** its timeline carries the four markers at those times

#### Scenario: An escalated incident has no MITIGATED
- **WHEN** a postmortem is written for an incident nothing mitigated
- **THEN** its timeline carries no MITIGATED marker

### Requirement: Supporting information holds the links and the evidence

Supporting information SHALL be the document's last section before the review
checklist. It SHALL hold every link Argus records for the incident - its page,
its walk, the proposed fix - each with its full address; a count of the
evidence read; every change to production and every log message the model was
shown, each under the label it was shown by; and the assumptions.

#### Scenario: A proposed fix is linked
- **GIVEN** an incident with a draft pull request
- **WHEN** the postmortem is shown
- **THEN** Supporting information links it with its full address

#### Scenario: The changes and log messages read are listed
- **GIVEN** an incident whose walk read two changes to production and one log
  message
- **WHEN** the postmortem is shown
- **THEN** Supporting information lists `P1` and `P2` with what each change
  was, and the log message under its `G` label

### Requirement: Every label the prose may cite has a row

The document SHALL have a row for every label the model is shown and may
cite - a line of the narration, a change to production, a log message, a
candidate, an action, an action item and a lead - so that a citation of it in
the prose leads to that row, on the page and in the PDF.

#### Scenario: A change cited in the root cause
- **GIVEN** a postmortem whose root cause says "the deploy P2"
- **WHEN** the postmortem is shown
- **THEN** `P2` is a link to the row in Supporting information saying what
  that change was

#### Scenario: A lead cited in the lessons
- **GIVEN** a postmortem whose lessons cite `L1`
- **WHEN** the postmortem is shown
- **THEN** `L1` is a link to the first lead under What people told Argus

### Requirement: The review checklist separates what Argus checks from what people do

The review checklist SHALL hold Google's five review criteria. Three SHALL be
checked by code and shown as met or not: key incident data collected (a
timeline, and evidence cited at every chain step), impact assessed (duration
and loss, each measured or explained), and the root-cause analysis complete
(a chain of more than one step, every factor answered, a cause an action
confirmed, and the answer saying its chain reaches a cause beyond the change
that set the incident off). Two - every action item owned and dated, and
reviewed and shared - SHALL be shown as left for a person, never as met or
failed.

#### Scenario: A complete answer
- **WHEN** the answer passed every check, says its chain reaches a cause beyond
  the change that set the incident off, an action confirmed a cause, and every
  figure was measured
- **THEN** the three checks are met and the two are shown as left for a person

#### Scenario: A chain that stops at the change
- **WHEN** the answer says its chain does not reach beyond the change that set
  the incident off
- **THEN** the root-cause analysis is shown as not complete

### Requirement: Money is shown to two decimal places

Every amount SHALL be shown to two decimal places with its currency, and SHALL
be stored at the precision it was computed to.

#### Scenario: A long decimal is rounded for show
- **GIVEN** a loss of 1736.68485900091116011163646 USD
- **WHEN** the postmortem is shown
- **THEN** it reads 1,736.68 USD

### Requirement: No pay-band figure appears in the document

No figure from which a pay band can be read SHALL appear in the document:
neither a band's endpoints nor the response cost's range. The assumptions SHALL
say the cost was priced at the midpoint of each title's band, without its
figures.

#### Scenario: A priced response
- **GIVEN** a responder priced at a band of 190000 to 250000 USD a year
- **WHEN** the postmortem is written and shown
- **THEN** neither endpoint, nor the range of the cost, appears in it

