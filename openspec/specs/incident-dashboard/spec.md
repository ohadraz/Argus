# incident-dashboard Specification

## Purpose
Argus's own screen - what it saw about an incident, and what it did about it. Served by the Web Application (§7.7, §7.9), so a walk is legible to somebody who was not watching it happen, and a running incident can be watched beside the Target Service's own console.
## Requirements

### Requirement: Argus has a view of its own reasoning

`argus_web` SHALL serve a server-rendered page showing what Argus did about an incident. It is Argus's screen, not the shop's: the Target Service's console shows the incident from outside, and this shows it from inside.

#### Scenario: Opening an incident

- **WHEN** an incident is opened in the browser
- **THEN** its alert, its status, the candidates it ranked, and what it did about each are shown on one page

#### Scenario: No build step

- **WHEN** the page is served
- **THEN** it renders from templates and assets shipped with the module, with no compiled frontend bundle

### Requirement: The page reads through the repositories and owns no domain logic

The view SHALL obtain everything it shows by calling the repositories that own the incident tables, and SHALL NOT write SQL of its own against Postgres or Chroma. It decides how something is displayed, never what it means.

#### Scenario: No second opinion about an incident

- **WHEN** the page shows a verdict, a status or a confidence
- **THEN** the value shown is the one recorded when it was decided, not one the page derived at render time

### Requirement: The view changes nothing

Nothing the view exposes SHALL stage, mitigate, approve, undo or delete anything. Looking at what Argus did must not be able to alter it, and an irreversible action requires human approval in the code path - a button is not that.

#### Scenario: A request to the view

- **WHEN** any route the view serves is called
- **THEN** no incident, hypothesis, action or timeline row is created, modified or deleted

### Requirement: An incident that does not exist says so

A request for an incident the database does not hold SHALL be answered as not found. An empty page shaped like an incident reads as an incident that did nothing, which is a different and worse claim than "there is no such incident".

#### Scenario: An unknown incident id

- **WHEN** a page is opened for an incident id that never existed
- **THEN** the response is 404, and not an empty incident

### Requirement: A live incident updates while it runs

While an incident is still running, the page SHALL keep itself current by polling, so a walk can be watched as it happens rather than read afterwards. An incident that has finished stops updating.

#### Scenario: A candidate is refuted while being watched

- **WHEN** an action is refuted and undone during an incident the page is showing
- **THEN** the page reflects that refutation and the move to the next candidate without a manual refresh

#### Scenario: A finished incident

- **WHEN** the incident being shown has reached a terminal status
- **THEN** the page stops polling

### Requirement: The walk is shown as a walk

The page SHALL show every ranked candidate, in rank order, distinguishing one that was tried from one that was never reached, and showing for each tried candidate the action taken, the verdict, and whether it was undone. Showing only the successful attempt would present a lucky guess.

#### Scenario: An incident that was wrong before it was right

- **WHEN** an incident whose first candidate was refuted is shown
- **THEN** the refuted candidate, its action, and its undo are visible alongside the candidate that resolved the incident

#### Scenario: An escalated incident

- **WHEN** an incident that ran out of candidates is shown
- **THEN** every candidate it tried is visible, and the page says it escalated rather than showing nothing

### Requirement: Evidence is shown against the claim it supports

Log lines and metric departures SHALL be displayed with the hypothesis that cited them. A reader must not have to match evidence to a claim by reading timestamps.

#### Scenario: Inspecting why a candidate was proposed

- **WHEN** a candidate is examined on the page
- **THEN** the evidence recorded for that candidate is shown with it

### Requirement: Past incidents remain readable

The view SHALL offer a history of incidents and their outcomes, and the postmortem where one exists, reached through the view's navigation rather than as its front page - what is happening now is what somebody opening Argus during an incident came for. A demo that can only show the incident currently running cannot show what the system has learned.

#### Scenario: Opening a past incident

- **WHEN** an incident from an earlier run is opened from the history
- **THEN** its walk and its postmortem render the same way a current incident's do

#### Scenario: An incident with no postmortem

- **WHEN** an incident that has no postmortem is shown
- **THEN** the page says there is none, and does not fail

#### Scenario: Reaching the history

- **WHEN** a reader opens Argus and wants an earlier incident
- **THEN** the history is reachable through the view's navigation, without knowing a URL

### Requirement: Argus is identifiable

The page SHALL carry Argus's own identity - its favicon and name - so a browser tab showing Argus is distinguishable at a glance from one showing the shop it is watching.

#### Scenario: Two tabs open during a demo

- **WHEN** the shop's console and Argus's page are open side by side
- **THEN** the two tabs are distinguishable by their icons alone
