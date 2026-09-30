## ADDED Requirements

### Requirement: A window with nothing at or after the minute asked about is its own state

When judging whether an incident has subsided, the system SHALL distinguish a
window that carries no minute at or after the moment in question from one that
carries minutes still at the incident's own level.

Both say the service has not been shown to have recovered, and they say it for
opposite reasons. One is *nothing has been seen*: no reading covers the minutes
since the action, so there is no measurement either way. The other is *what was
seen is still wrong*: the minutes are there and they have not come back. Collapsed
into one answer, a service nobody can see reads as a service that is still
failing, which is the same conflation `could_not_be_read` exists to prevent one
layer up.

#### Scenario: No minute at or after the moment is nothing seen
- **GIVEN** a window whose minutes stop before the moment recovery is judged from
- **WHEN** recovery is judged
- **THEN** the answer says nothing was seen, distinctly from the service not
  having recovered

#### Scenario: Minutes still at the incident's level are a service not recovered
- **GIVEN** a window carrying minutes at and after that moment, still at the
  incident's level
- **WHEN** recovery is judged
- **THEN** the answer says the service has not recovered

### Requirement: Where an incident is that the service could not be read, the recovery is the read returning

The system SHALL judge a mitigation of an incident whose minutes are absent rather
than elevated by whether the minutes at and after the action are present, and
SHALL NOT infer that recovery from the absence of a departure in the window.

The absence of a departure is not evidence here, and treating it as evidence is
the same mistake at two altitudes. A model is told not to read a window with no
rows as a healthy service; a verdict formed on *no series departed* reads exactly
that, over exactly that window, and confirms a mitigation on it. The sight
returning is what the action was for, and it is a fact about the window rather
than about the levels in it.

#### Scenario: The minutes returning confirms the mitigation
- **GIVEN** an incident whose minutes were absent, and an action after which they
  are present
- **WHEN** the verdict is formed
- **THEN** it is `confirmed`, on the minutes being there rather than on their
  levels

#### Scenario: Minutes still absent at the deadline refutes it
- **GIVEN** an incident whose minutes were absent, and an action after which no
  minute at or after it is present when the allowed time runs out
- **WHEN** the verdict is formed
- **THEN** it is `refuted`

#### Scenario: Minutes that return departed are still a recovery of what was mitigated
- **GIVEN** an incident whose minutes were absent, and an action after which they
  are present and depart from the service's baseline
- **WHEN** the verdict is formed
- **THEN** it is `confirmed`, and the departure is reported rather than swallowed -
  what was mitigated has ended, and a service that cannot be seen is not thereby
  a service that is well

### Requirement: A confirmed recovery of the sight is not a claim about the service

Where a returned window departs from the service's baseline, the system SHALL
report that departure as a finding of its own, and SHALL NOT let it change the
verdict.

Neither other verdict is available, and one of them would be a bug rather than a
wording. `refuted` is acted on: the change is undone and the candidate struck off -
so a shop whose telemetry Argus had just restored would be blinded again, the
correct cause removed from the list, and the walk sent looking for another
explanation with nothing left to look at. `escalated` means Argus cannot say, and
Argus can: it measured the sight returning.

The incident then closes as `mitigated`, because a confirmed outcome derives that
status ahead of every other question. That is true of the sight and silent about
the shop, and the asymmetry is worth stating rather than leaving to be found: a
departure a returned window reveals is by construction the first anybody has seen
of those minutes, since there was nothing to read before, so the only walk that can
surface it is the one closing as mitigated.

**What becomes of that departure is outside this capability.** Acting on it is a
new intake or a new candidate, and growing either from a rule about recovery would
put a second decision inside a verdict that has just been narrowed to one. It is
left as a gap this change knows it leaves.

#### Scenario: The departure is reported without displacing the verdict
- **GIVEN** a confirmed recovery whose returned minutes depart from the baseline
- **WHEN** the incident is reported
- **THEN** the departure is stated as a finding, and the verdict is still
  `confirmed`

#### Scenario: The status describes the sight
- **GIVEN** the same incident
- **WHEN** its status is derived
- **THEN** it is `mitigated`, on the sight having been restored, and nothing in it
  asserts the service is well

### Requirement: What returning restores is the sight, never the minutes that were missed

The system SHALL treat a confirmed recovery of this kind as the readings resuming
from the action onwards, and SHALL NOT report the window as whole.

The minutes that were never published are not recoverable by anything: no reading
of them was taken, nothing retained them, and putting the cause back cannot
produce them after the fact. So this mode shares with silent data corruption the
property that ends an incident without undoing what it cost - and a verdict of
`confirmed` here means *we can see again*, not *we can see what happened*. An
incident record that let the first be read as the second would claim evidence for
a stretch of time nobody has any.

#### Scenario: A confirmed recovery does not claim the missing minutes
- **GIVEN** an incident whose minutes were absent and whose mitigation is confirmed
- **WHEN** the incident is reported
- **THEN** the minutes between the onset and the action are still said to carry no
  readings, and nothing describes the window as complete

### Requirement: The rule is decided from the window in hand, never from the failure mode

The system SHALL decide which judgement applies from the readings the verification
itself took, and SHALL NOT carry a failure mode, a hypothesis or any claim from
another agent into that decision.

A mapping from a mode to a recovery rule would be a table saying one mode is
special, and the rule is not about a mode: any incident whose minutes are absent
is one whose recovery is a reading that has minutes in it. The verification
re-reads the same channel every pass, so the fact is in front of it already, and
a value threaded from the Investigator would be a claim about a window rather than
the window.

#### Scenario: An absent window is judged this way whatever the mode is
- **GIVEN** an incident whose minutes are absent and whose named mode is not about
  monitoring
- **WHEN** the verdict is formed
- **THEN** it is judged on the minutes returning, exactly as any other absent
  window is

### Requirement: A read that could not be taken keeps the meaning it has

The system SHALL go on treating a metrics read that failed as a read nobody took,
distinctly from a read that answered with no minutes in the span asked about.

A channel that raised and a channel that answered thinly are two facts, and the
first already has its answer: no verdict was reached, and a person is asked rather
than an explanation struck off on a measurement nobody made. Nothing in this
capability reaches that case, which is what keeps this rule additive.

#### Scenario: A failing read still reaches no verdict
- **GIVEN** a verification whose every metrics read raises until the allowed time
  runs out
- **WHEN** the verdict is formed
- **THEN** it is escalated rather than refuted, unchanged
