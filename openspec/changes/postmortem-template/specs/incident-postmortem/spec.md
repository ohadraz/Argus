## MODIFIED Requirements

### Requirement: Published prose may not name a figure the system did not compute
The system SHALL check every prose field of the answer - the summary, the root
cause, each chain step, each contributing factor, each proposed action item,
each lesson and each lead's effect - for figures it writes itself, and SHALL
treat each as a fault however it is written: in digits, in a run of number
words, or in one word that measures something ("twenty minutes", "tripled", "a
third"). Every figure the model is shown SHALL carry a name in braces after it,
and the prose SHALL state a figure by naming it, code writing the figure in as
the run measured it. A figure the incident never gave as one SHALL be named as
a working of two it did (`{recovered - began}`), which code SHALL work out from
the two figures as the model was shown them, by their kinds. A working of kinds
that do not combine, one coming out below nothing, one dividing by nothing, and
a name the incident never gave SHALL be faults. A size said with no number in
it, a count of things, and a word mixing letters and digits SHALL NOT be. Prose
is published as written, so a written figure - repeated, rounded, or invented,
which the sentence cannot tell apart - would otherwise reach the reader least
able to check it.

#### Scenario: A summary writing an amount is challenged
- **GIVEN** an answer whose executive summary says the outage cost $1,200,000
- **WHEN** the document is assembled
- **THEN** the model is asked once more, and the amount is named as the reason

#### Scenario: A figure said in one word is challenged
- **WHEN** a summary says the service was broken for twenty minutes
- **THEN** the model is asked once more, and "twenty minutes" is named as the
  reason

#### Scenario: A figure named is written in as the run measured it
- **WHEN** a summary says the service was broken for `{duration}`
- **THEN** it is accepted without a further call, and the published summary
  states the duration this run measured

#### Scenario: A working is worked out from the figures as shown
- **GIVEN** error rates shown as 1.2% before and 33.9% while broken
- **WHEN** a summary says they rose by `{errors_while_broken - errors_before}`
- **THEN** the published summary says they rose by 32.7 percentage points

#### Scenario: A working that makes no sense is challenged
- **WHEN** a summary asks for `{began + closed}`
- **THEN** the model is asked once more, naming the working and why two
  instants add to nothing

### Requirement: The document is checked once and then handed off regardless
The system SHALL check its own document for missing required fields, for chain
steps that cite no evidence or a label never given, for contributing factors no
action item answers, and for figures the prose may not name. Where any of these
are found it SHALL ask the model once more, naming them. Whatever comes back
SHALL be written, with the review checklist recording what it fell short of.
There SHALL be no further attempt. The document SHALL then be handed to the
Communicator for delivery: the Postmortem agent SHALL produce the document and
SHALL NOT send it anywhere, so that what a postmortem says and where it is read
stay separate concerns.

#### Scenario: A complete document is written without a second call
- **WHEN** the first answer carries every required field and passes every check
- **THEN** the document is written with the review checks met, with no second
  model call

#### Scenario: A second faulty answer is still written
- **GIVEN** a first answer with a chain step citing nothing
- **WHEN** the second answer still has one
- **THEN** the document is written with what is present, and the review
  checklist shows the root-cause analysis as not complete

#### Scenario: The written document is handed over for delivery
- **GIVEN** a written postmortem
- **WHEN** the incident ends
- **THEN** the Communicator delivers that document, and the Postmortem agent
  makes no call to any destination
