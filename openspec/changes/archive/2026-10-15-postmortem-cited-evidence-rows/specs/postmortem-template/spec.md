## MODIFIED Requirements

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

## ADDED Requirements

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
