## ADDED Requirements

### Requirement: The front door is what is happening now

`argus_web` SHALL serve, as its front page, the incident currently running - not a list of past ones. Somebody who opens Argus during an incident is looking for the incident, and a list is one click of indirection in front of the only thing they came for.

#### Scenario: Nothing is happening

- **WHEN** the front page is opened and no incident is running
- **THEN** it says so plainly, and waits

#### Scenario: An alert arrives while the page is open

- **WHEN** an incident opens while somebody is looking at the front page
- **THEN** the incident appears without a manual refresh

### Requirement: A running incident is headed by what it is and how long it has been going

The live view SHALL show the alert, the service it fired on, when it started, the incident's current status and the time elapsed since it opened. While the incident is running the status SHALL be visibly live rather than static, and it SHALL stop being so once the incident finishes.

#### Scenario: An incident that has just opened

- **WHEN** an incident is shown moments after its alert arrived
- **THEN** the header names the alert and service, shows the status as acknowledged, and counts the elapsed time upward

#### Scenario: An incident that has finished

- **WHEN** the incident shown has reached a terminal status
- **THEN** the header stops indicating activity and the elapsed time stops advancing

### Requirement: The view narrates what Argus did, in the order it did it

The live view SHALL render the incident's recorded events as an ordered narration, each line carrying the time it happened and what happened - the alert acknowledged, an agent invoked, a retrieval made over a named window, an onset detected, a hypothesis formed, an action taken and its verdict.

#### Scenario: An investigation in progress

- **WHEN** an incident is shown while the Investigator is working
- **THEN** the narration names each retrieval it has made and the window each covered, in order, ending at the most recent

#### Scenario: The narration and the walk agree

- **WHEN** a hypothesis appears in the narration
- **THEN** it is the hypothesis that was recorded, not one restated or re-derived by the view

### Requirement: Retrieved evidence is shown as it was retrieved

Where an event carries evidence Argus read - metric buckets, log lines, recorded flag changes, production changes - the view SHALL render that evidence as the values that were recorded, never re-fetched at render time. The evidence SHALL be gathered into a table per channel below the narration, each row shown once however many retrievals returned it. Metrics SHALL be shown as the table of buckets they are, with anomalous values marked; log lines SHALL be shown with their level distinguished.

#### Scenario: A metrics retrieval

- **WHEN** a metrics retrieval has been made
- **THEN** the buckets it returned are shown as a table, and the ones that departed from the baseline are marked

#### Scenario: A log retrieval

- **WHEN** a log retrieval has been made
- **THEN** its lines are shown with warnings and errors distinguishable from ordinary lines at a glance

#### Scenario: An investigation that widened

- **WHEN** two retrievals on the same channel returned overlapping windows
- **THEN** each minute and each log line appears once, not once per retrieval

### Requirement: A narration line points at the evidence it names

Where a narration line is about one row of the evidence, the view SHALL link to that row. Where what a line refers to cannot be identified without guessing, the view SHALL offer no link rather than a link to a row it inferred.

#### Scenario: The onset

- **WHEN** the narration says where the incident started
- **THEN** the line links to that minute's row in the metrics table

#### Scenario: A claim that names no row that exists

- **WHEN** a recorded claim cites a time that nothing on the page holds evidence for
- **THEN** the claim is shown with no link

### Requirement: The view is navigable

The view SHALL offer navigation between what is happening now, the history of past incidents, and any incident's detail. A reader SHALL be able to reach the history without knowing a URL.

#### Scenario: Reaching the history

- **WHEN** a reader on the live page wants an older incident
- **THEN** navigation on the page takes them to the history, and an incident there opens its detail

### Requirement: The live view changes nothing

Nothing the live view exposes SHALL stage, mitigate, approve, undo or delete anything, and it SHALL hold no incident-domain logic - it renders recorded events and never decides what they mean.

#### Scenario: A request to the live view

- **WHEN** any route the live view serves is called
- **THEN** no incident, hypothesis, action, timeline or event row is created, modified or deleted
