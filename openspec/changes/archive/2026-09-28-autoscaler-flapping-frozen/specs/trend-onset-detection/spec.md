## ADDED Requirements

### Requirement: How long a recovery has to hold for is measured off the incident
The system SHALL require a run of clear minutes one longer than the longest lull
this incident has already come back from, and SHALL NOT require a configured
number of them.

A lull of the length the incident is known to take is the one length that proves
nothing: the service has already been exactly that well once and returned, so a
stretch of that length is a stretch the window holds a counterexample to. One
minute past it is the shortest run that has none.

**A fixed count is wrong in both directions, because the number stands in for
something it cannot see.** What it is really being asked is whether the signal
oscillates. A service that fell from a third of its requests failing to half a
percent and stayed there has recovered on its first clear minute, and holding it
to a second spends a minute of the verification window re-establishing what the
window already settles - which matters, because that window is bounded and every
minute of it is a minute the incident is still open. A service clear four minutes
in every six has recovered on none of them, and any count at or below four
confirms a mitigation in the middle of a lull. A count chosen to fit one cycle is
wrong about the next: two bad minutes to one good is answered by two, and two bad
to four good defeats it.

**Only a lull the incident returned from properly counts**, its following run of
departed minutes reaching the same persistence a relapse has to reach. A lone
departed minute is not the incident coming back - that is the allowance the
departed side of this judgement already makes - so crediting one would let a
recovery followed by a single noisy sample demand a longer clear run than the
recovery that sample interrupted, and the allowance would defeat itself.

The calm a window opens with is not a lull. It is followed by the onset, which
reaches persistence by definition, so counting it would have every window demand
one more clear minute than the calm it opened with - which is most of the window
and never available.

Both questions about recovery SHALL be answered by this one rule - Mitigation's
"has it recovered since I acted" and the postmortem's "which minute did it recover
at" - so that the two cannot come to disagree about one window and date a recovery
at a minute the other refused a mitigation on.

#### Scenario: A step incident is recovered from on one clear minute
- **GIVEN** a window in which the service departed, was acted on, and came back,
  with no lull anywhere inside the incident
- **WHEN** the service is asked whether it has recovered since the action
- **THEN** one clear minute is enough

#### Scenario: A cycle is not recovered from in the length of its own lull
- **GIVEN** a window in which the service is clear for four minutes of every six,
  each lull followed by two departed minutes
- **WHEN** the service is asked whether it has recovered, from the start of a lull
- **THEN** four clear minutes are not enough

#### Scenario: A noisy minute after a recovery does not lengthen what recovery needs
- **GIVEN** a window in which the service came back, caught one departed minute,
  and came back again
- **WHEN** the service is asked whether it has recovered since the action
- **THEN** the lone departed minute is not read as the incident returning, and the
  clear run already measured stands
