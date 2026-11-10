## ADDED Requirements

### Requirement: The synopsis is a step after the postmortem, and changes nothing of it
The system SHALL write the executive synopsis in a walk step of its own, after the
postmortem step, from the stored postmortem and what the step reads itself. The
postmortem's prompt and output SHALL be the same with the step as without it.
Its document and row carry one field only the synopsis reads - whether a page
went out - which no page, PDF or request of the postmortem's shows.

#### Scenario: The postmortem's exchanges replay unchanged
- **GIVEN** a case whose postmortem was recorded before this change
- **WHEN** it is replayed with the synopsis step in place
- **THEN** every postmortem request matches its recording, and the synopsis's
  exchange comes after them

#### Scenario: The figure check is reached without changing it
- **GIVEN** the public function running the postmortem's four figure rules
- **WHEN** the postmortem's own checks run
- **THEN** they call the rules exactly as before, and the function returns each
  rule's faults under that rule's name

#### Scenario: The stored postmortem is the same
- **GIVEN** one incident written up with the synopsis step and without it
- **WHEN** the two `postmortem` rows are compared
- **THEN** they hold the same values

### Requirement: Written whatever is configured
The system SHALL write the synopsis on every ending that writes a postmortem,
whether or not any destination is configured.

#### Scenario: Nothing configured
- **GIVEN** no Slack id configured
- **WHEN** an incident ends with a postmortem
- **THEN** its synopsis is written and stored, and nothing is posted

### Requirement: Pay is shown only where the synopsis is posted
The system SHALL NOT show the responder cost's midpoint, minimum or maximum,
per title or in total, anywhere but the synopsis's Slack messages to the
configured members and channels: not in `argus_web`, an event, the
timeline, the war room, an incident's thread, the postmortem channel, or a
request to the model.

#### Scenario: No route serves pay
- **WHEN** every `argus_web` route is requested for an incident with a synopsis
- **THEN** no response carries a responder cost figure

#### Scenario: The war room hears no pay
- **WHEN** an incident's synopsis is posted to Slack
- **THEN** nothing posted to the war room, the incident's thread or the
  postmortem channel carries a responder cost figure

### Requirement: The synopsis's parts, in order
The synopsis SHALL hold, in this order: an overview; when the incident began and
ended and how long it lasted; the impact; the resolution; the human cost; and
the full postmortem's address. It SHALL be written on every ending that writes a
postmortem, a disproven alarm included.

#### Scenario: A resolved incident's synopsis
- **GIVEN** an incident that ended resolved
- **WHEN** its synopsis is written
- **THEN** it holds every part in order

### Requirement: Every time is said in UTC
The system SHALL state every time in the synopsis in UTC, naming the zone, and
SHALL NOT convert it to any reader's zone.

#### Scenario: The window is dated in UTC
- **WHEN** a synopsis is shown
- **THEN** each time carries its date and time, labelled UTC

#### Scenario: When says how long
- **GIVEN** an incident with a measured stretch
- **WHEN** its synopsis is shown
- **THEN** When gives its from and to, and how long it lasted as the duration's
  tile says it - "at least" on a floor, and nothing for a disproven alarm

### Requirement: A disproven alarm is reported as one
For a disproven alarm the synopsis SHALL state when the alert came and when Argus
closed it as disproven, and no duration, harm or loss - as the postmortem does
for one. Its human cost SHALL be shown as for any incident.

#### Scenario: No stretch for an alarm with nothing behind it
- **GIVEN** an alarm Argus closed as disproven, which people responded to
- **WHEN** its synopsis is shown
- **THEN** it gives the alert and the close, no duration and no loss, and the
  human cost

### Requirement: The impact is said as the postmortem page says it
The synopsis's impact tiles SHALL be the postmortem page's own impact figures,
worded by the same code.

#### Scenario: One figure, one wording
- **GIVEN** an incident whose postmortem page shows a duration and a loss
- **WHEN** its synopsis is shown
- **THEN** both read exactly as on the postmortem page

### Requirement: The model writes the overview, naming figures
The system SHALL ask the model for the overview in the step's own call, giving
it the stored postmortem's figures by name, the cause in plain words, the
resolution list, and what a reader saw. Pay SHALL reach the model by name
only, never as a value: the request is sent to the model's provider and its
recording is committed. The overview SHALL refer to each figure by name, and the
system SHALL write each figure in as prose says the figure its tile shows: a
duration in words, with the tile's "at least" where the tile says it, and the
responders' minutes with what they count - from each responder taking the page
until the page was closed. An overview that writes out a figure itself SHALL be
refused, by the same rules the postmortem's prose is held to, run by the same
code.

#### Scenario: A named figure is written as prose says its tile's figure
- **GIVEN** an overview naming `{duration}`, whose tile shows "7m 12s"
- **WHEN** the synopsis is shown
- **THEN** the overview says "7 minutes 12 seconds"

#### Scenario: A floor stays a floor
- **GIVEN** an overview naming `{duration}`, whose tile shows "at least 7d 0h 0m"
- **WHEN** the synopsis is shown
- **THEN** the overview says "at least 7 days"

#### Scenario: A floor the overview already says is said once
- **GIVEN** an overview saying "at least {duration}", whose tile shows "at least 7d 0h 0m"
- **WHEN** the synopsis is shown
- **THEN** the overview says "at least 7 days", once, in the overview's own capitals

#### Scenario: A floor after the overview's own "at"
- **GIVEN** an overview saying "the lost takings at {customer_loss}", whose tile
  shows "at least 4,954.52 USD"
- **WHEN** the synopsis is shown
- **THEN** the overview says "the lost takings at no less than 4,954.52 USD",
  keeping its own "at"

#### Scenario: The responders' minutes say what they count
- **GIVEN** an overview naming `{engineer_minutes}`, where two responders took
  the page
- **WHEN** the synopsis is shown
- **THEN** the minutes are said with what they count, from each responder taking
  the page until the page was closed - and where nobody took a page, as none,
  with no page said

#### Scenario: A figure written out is refused
- **GIVEN** an overview saying "twenty minutes"
- **WHEN** it is checked
- **THEN** it is refused, and the model is told which words were refused

#### Scenario: The request carries no pay
- **GIVEN** a priced response
- **WHEN** the overview's request is built
- **THEN** it names `{responder_cost}` and carries no amount of pay

### Requirement: The overview names the figures the record holds
The system SHALL refuse an overview that leaves out a required figure the record
holds: the duration, the customer loss and the responder cost. A figure the
record does not hold SHALL be neither required nor offered.

#### Scenario: A missing duration is refused
- **GIVEN** an incident with a measured duration
- **WHEN** an overview naming no `{duration}` is checked
- **THEN** it is refused for leaving the duration out

#### Scenario: A figure the record lacks is not required
- **GIVEN** a disproven alarm, which has no loss
- **WHEN** an overview naming no loss is checked
- **THEN** it is not refused for that

### Requirement: The overview claims no more about the resolution than the list
The prompt SHALL give the model the resolution list and forbid it to say that
anything worked beyond what the list says, or to size a figure in words ("a
brief outage", "a minor loss"). Judging each recorded overview SHALL check both.

#### Scenario: A draft fix is not said to correct anything
- **GIVEN** an incident whose resolution list says a draft fix awaits review
- **WHEN** the model is asked for the overview
- **THEN** the prompt says nothing has run the fix and forbids saying it
  corrects anything

### Requirement: The overview speaks of Argus by name
The prompt SHALL ask the model to speak of Argus by name, and the system SHALL
refuse an overview saying "we", "our" or "us": Argus is the system that
responded, and "we" credits a team with what it did or speaks for a company
that said nothing.

#### Scenario: "We" is refused
- **GIVEN** an overview saying "We estimate the shop lost {customer_loss}"
- **WHEN** it is checked
- **THEN** it is refused, quoting "We"

### Requirement: The overview says who was affected as the cause does
The prompt SHALL ask the model to say which people were affected, as the cause
in plain words says it, or that some were where it does not say which - never
how many, and never all of them where the cause does not say all - and to keep "likely" on what the cause says is likely, and
only there.

### Requirement: Nobody responding is said, not counted
Where nobody responded, the request SHALL offer no figure for the people who
responded or their minutes, and SHALL say among the figures why: that nobody
was paged, or that somebody was paged and nobody acknowledged the page - read
off the postmortem's record of whether a page went out, since the count is
nobody both ways. The Human cost SHALL say the same. Where the on-call source
could not be read, the request SHALL offer neither and say nothing of paging.

#### Scenario: Nobody paged
- **GIVEN** an incident nobody was paged for
- **WHEN** the overview's request is built
- **THEN** it names no `{responders}` and no `{engineer_minutes}`, and says
  "Nobody was paged: no on-call incident was linked to this one." - the
  record's reason, so the overview gives no other

#### Scenario: A page nobody acknowledged
- **GIVEN** an incident whose page went out and was never acknowledged
- **WHEN** the overview's request is built and the synopsis is shown
- **THEN** both say somebody was paged and nobody acknowledged the page, and
  neither says nobody was paged

### Requirement: A disproven alarm is said where its duration would be
Where Argus disproved the alarm, the request SHALL say first among the figures
that nothing broke and so there was no failure to time - read off the
postmortem's disproof - since an overview asked how long the incident lasted
and handed no duration would otherwise say the record does not say.

#### Scenario: A disproven alarm
- **GIVEN** an incident Argus closed as disproven
- **WHEN** the overview's request is built
- **THEN** its figures open by saying nothing broke, the alarm was disproven,
  so there was no failure to time

### Requirement: No loss is an amount in prose
Where the estimated loss is zero, the overview SHALL have it written in as the
amount, "0.00" in its currency, with "so far" where the tile says it is a floor -
never the tile's "none", which reads wrongly in an amount's place.

#### Scenario: The ask carries both
- **WHEN** the overview's request is built
- **THEN** it asks for who was affected by which ones, and for "likely" only
  where the cause says it

### Requirement: The overview names the record's pull request
Any pull request the overview names SHALL be written as the one the record
holds, by its name, as the postmortem's prose is held to it; where the record
holds none, it SHALL be left as written.

#### Scenario: A replay names another run's draft
- **GIVEN** a recorded overview naming the recording run's pull request
- **WHEN** it is replayed for an incident whose draft has another number
- **THEN** the overview names this incident's draft

### Requirement: The overview is asked again once, then given up
The system SHALL send a refused overview back once, through the call's own tool
result, and SHALL give up after a second refusal, any model error, or a request
the model's API rejects - logging the rejection as an error. A synopsis
given up SHALL be stored without an overview, and the system SHALL publish on
the incident's timeline that the executive synopsis was withheld and why. That
event SHALL carry no figure.

#### Scenario: Two refusals withhold the synopsis
- **GIVEN** a model whose overview is refused twice
- **WHEN** the synopsis is written
- **THEN** it has no overview, and the timeline says it was withheld and why

#### Scenario: A rejected request withholds the synopsis, and the walk goes on
- **GIVEN** a model API that rejects the overview's request
- **WHEN** the synopsis is written
- **THEN** it has no overview, its reason is the API's own words, and the walk
  ends as it would have

### Requirement: Code writes the resolution
The system SHALL write the synopsis's resolution as a list, each line opening
with who acted: a person's resolution first, where a person ended the incident,
naming them; then each action in the words the postmortem's Resolution section
uses for it and what it came to; then any draft fix left for review; then any
recommendation not taken. A refusal that recommends what it refused SHALL be one
line naming the recommendation, with no outcome of its own. An action stopped
before its verdict SHALL say the verdict was Argus's, and where a person's
resolution stopped it, that they resolved it first. No line SHALL carry a
candidate's label, which only the postmortem defines.

#### Scenario: The resolution agrees with the postmortem
- **GIVEN** an incident whose postmortem lists one action and what it came to
- **WHEN** the synopsis is shown
- **THEN** its resolution says who took that action, and the action and outcome
  in the same words

#### Scenario: A person ended it
- **GIVEN** an incident a person reported resolved
- **WHEN** the synopsis is shown
- **THEN** its resolution opens with that person, where they reported it from,
  and their words

#### Scenario: No candidate's label
- **GIVEN** an action taken for a candidate the postmortem labels C1
- **WHEN** the synopsis is shown
- **THEN** no resolution line says C1

### Requirement: The human cost is shown per title, with its range and basis
The synopsis SHALL show, for each title responders held, how many held it, their
minutes, and their cost at the band's midpoint with the range from the band's
minimum to its maximum; responders with no recorded title as a row of their
own; and, beneath two rows or more, a total row - beneath one row it would say
the row again. The total shown SHALL be the stored postmortem's, to the
cent, everywhere the synopsis states it - the overview included. Each row SHALL
be rounded to the cent so that the rows shown add up to the total shown, the
cents a plain rounding leaves over going to the rows with the largest
remainders. Beneath it the synopsis SHALL state the basis: the working year the
bands were divided by, and that each title is priced at its band's midpoint.

#### Scenario: Two titles, two rows and a total
- **GIVEN** responders holding two titles, both priced
- **WHEN** the synopsis is shown
- **THEN** each title has a row with people, minutes, midpoint and range, the
  total row is the stored total to the cent, the rows add up to it, and the
  basis is stated

#### Scenario: Rounding that would miss by a cent
- **GIVEN** three rows whose amounts each round down
- **WHEN** the synopsis is shown
- **THEN** the rows shown still add up to the total shown

#### Scenario: A responder with no title has a row
- **GIVEN** one responder with a title and one with none
- **WHEN** the synopsis is shown
- **THEN** the second has a row of its own, and the rows' people and minutes
  add up to the total's

#### Scenario: An unpriced title shows minutes and no cost
- **GIVEN** a responder whose title has no band
- **WHEN** the synopsis is shown
- **THEN** people and minutes are shown, no cost is shown, and the synopsis names
  the title nothing could price

### Requirement: The breakdown agrees with the postmortem or is not shown
The step SHALL read each responder's minutes and their titles' bands itself,
through the postmortem's own reads, and SHALL check that the rows' people,
minutes, midpoint, minimum and maximum sum to the stored postmortem's - the
amounts compared to the cent - and that their currency is the stored one. Where
any differs, the synopsis SHALL show the postmortem's totals with no per-title
rows, and say the breakdown could not be matched.

#### Scenario: Summation order is not a mismatch
- **GIVEN** rows whose amounts sum to the stored total within a fraction of a cent
- **WHEN** they are checked
- **THEN** they match

#### Scenario: A band that moved
- **GIVEN** a band whose maximum changed since the postmortem was written
- **WHEN** the synopsis is written
- **THEN** it shows the postmortem's totals and no rows

#### Scenario: A source that changed since the postmortem
- **GIVEN** an on-call source answering differently than when the postmortem
  was written
- **WHEN** the synopsis is written
- **THEN** it shows the postmortem's totals, no rows, and says why

### Requirement: A response shared with other incidents is said to be
Where the on-call page also covered other incidents, the synopsis SHALL say beside
the human cost that the same response is counted in each of them, as the
postmortem says beside its minutes.

#### Scenario: A shared page
- **GIVEN** an incident whose on-call page covered another incident too
- **WHEN** its synopsis is shown
- **THEN** the human cost says the response is counted in each

### Requirement: The business and the people are never one figure
The synopsis SHALL NOT add the customer loss to the responder cost.

#### Scenario: Two money figures, no total
- **GIVEN** a customer loss and a responder cost in one currency
- **WHEN** the synopsis is shown
- **THEN** each is shown on its own and no figure adds them

### Requirement: The synopsis links to the full postmortem only
The synopsis SHALL carry the full postmortem's address, built from the configured
base address, and no other address of Argus's. With no base address configured,
it SHALL carry no link.

#### Scenario: One address
- **GIVEN** a configured base address
- **WHEN** a synopsis is shown
- **THEN** it carries the postmortem's full address and no other of Argus's

#### Scenario: No base address
- **GIVEN** no base address configured
- **WHEN** a synopsis is shown
- **THEN** it carries no link
