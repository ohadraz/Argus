## Context

An investigation reads the metrics summary once before it opens a conversation
with the model. `investigation.py` then takes one of three paths: an onset was
measured, so investigate from it; no onset was measured but the alert states one,
so investigate from that; or neither, so return `_nothing_to_say` - one
undetermined candidate carrying a reason, no model call, and a walk that derives
`ESCALATED` and writes a postmortem.

That third path is reached by two unlike situations. One is a rule that fired
about a series and a window showing that series never moved. The other is an
alert reporting something no series carries, which happens to carry no date.
Today the first is reported as a failure of investigation, and the second would
be too.

A fourth path already exists beside them - `_nothing_could_be_read`, for a window
nobody could retrieve - and it was split out for the same reason this change
splits the third: "no metrics were retrieved" and "the metrics say the service is
well" are opposite claims and were being reported in one sentence.

## Goals / Non-Goals

**Goals:**

- An alarm whose own claim the window contradicts ends as `DISPROVEN`, with the
  signals judged and the span judged over on the record.
- The branch that lets a finding-carrying alert be investigated without a date
  exists and is reachable, so the closure cannot swallow one.
- The split is decided by what the alert says it looked at, not by parsing its
  name and not by whether it happened to carry a date.

**Non-Goals:**

- No new failure mode, scenario, mitigation or read channel.
- Not FM-21, which is out of scope for Argus entirely: that mode is an incident
  outliving its own fix, and Argus's bound is a single walk. The dateless-finding
  branch is motivated by a data-loss mode that would be proposed separately.
- Not a change to what disproves an alarm. The departure arithmetic in
  `anomaly.py` is untouched; this change reads its answer and reports it
  differently.
- Not a judgement about the rule. Argus says the window did not contain the
  claim; whether the threshold is wrong, the window too narrow, or the condition
  genuinely transient is the rule owner's.

## Decisions

**The alert carries the kind of claim it makes, as an explicit field.**

Three alternatives were weighed.

*Infer from `stated_onset is not None`* - cheapest, and wrong in exactly the case
the second half of this change exists for: a finding that cannot be dated looks
identical to a threshold rule that said nothing. This is the hole, not a design.

*Match on `alertname`* - a string table that every new rule in the estate has to
join, and which reads `AccountPageIntegrityDrift` and `HighErrorRate` by their
spelling. A rule named after its service would be classified by its name rather
than by what it watched.

*Chosen: an annotation the rule sets, read into a typed field on `Alert`.* What
kind of claim a rule makes is something only the rule knows, so it is the rule
that says it. `argus_web.grafana` reads it alongside `onset`. Absent means a
series condition, because that is what a threshold rule is and what a monitoring
stack that says nothing about itself almost certainly has - and it keeps every
alert that exists today classified correctly with no change to any of them.

The three rules in the fixture that carry findings of their own - the spend
integrity check, the cache reconciliation, and the absence of readings - set the
annotation. Two of them also state an onset and so never reach the branch; they
set it anyway, because a rule describing itself should not depend on which other
field it happened to fill in.

**The investigation reports the disproof; the status function derives the
status.**

`Findings` gains a typed field saying the alarm was disproven, beside
`readings_cover_the_incident`, which is there for the same reason: only the
investigation holds both halves - the alert's claim and the window. The status
function reads that field. It does not read the undetermined candidate's reason
string, because a status derived from prose is a status that changes when
somebody edits a sentence.

The field defaults to false, so every state that exists today derives exactly
what it derives now.

**`DISPROVEN`, not `REFUTED`.**

`refuted` is already this system's word for a mitigation attempt the evidence
undid - `ActionOutcome.REFUTED`, and the whole vocabulary of near-misses in the
failure-mode backlog. A second meaning on the same word is a cost every later
reader pays; this repo has two such collisions already and has written both down
as mistakes.

**A postmortem is written, as for every other ending.**

The invariant is that an incident ends with exactly one document, and what was
ruled out is what the next responder needs. Here what was ruled out is the alarm.
The alternative - no document, on the ground that there was no incident - saves a
model call per spurious page and breaks the invariant, which would then have to
be special-cased everywhere a reader expects a document to exist.

**The disproof names what it was made over.**

An assertion that nothing departed is worth exactly as much as the signals and
the span behind it, and both are already in hand where the decision is made. A
disproof that recorded neither would be unreviewable, and a later reader could
not tell a sound one from one made over a window too narrow to contain the
condition.

## Risks / Trade-offs

**A real incident is closed because the window was too narrow for it** → The span
and the signals are recorded with the disproof, so the mistake is visible rather
than inferred. The arithmetic deciding departure is unchanged, so this risk is
not newly created - today the same window produces `ESCALATED` with the same
blindness, and a human is sent to look at a service for no reason.

**A rule that sets the annotation wrongly is classified wrongly** → A rule
claiming a finding when it watched a series is never disproven, so it escalates
as it does today; the failure is conservative. A rule claiming a series when it
carried a finding could be disproven wrongly, which is why the fixture's three
finding-carrying rules set it explicitly and the default is the conservative
direction for everything else.

**Nothing reaches the dateless-finding branch** → It is a seam, declared as one
in the proposal. It is covered by the Investigator's own suite rather than by a
scenario, and the first mode that needs it will find it already there instead of
finding the closure swallowing its incident.

**The status vocabulary grows** → Every consumer of `IncidentStatus` has to
account for it: the dashboard, the status derivation, the narration, the Slack
announcement. That is the cost of the ending being a status rather than a note on
an escalation, and the reason to pay it is that a dashboard showing a wall of
`escalated` cannot be read.

## Migration Plan

No data migration. `IncidentStatus` is a `StrEnum` persisted as text, so an added
member needs no schema change, and no existing row can hold the new value.

No existing e2e case changes its expectation, and the one that looked certain to
is the reason this section exists.
`test_firing_alert_with_no_cause_to_find_escalates_with_a_postmortem` stages a
`HighErrorRate` alert against an unseeded shop, which reads as a well service and
is not one: an unseeded Target Service serves no metrics, so the window is empty
rather than flat and disproves nothing. It keeps `INVESTIGATING` → `ESCALATED`,
and only its name changes, to
`test_an_alert_over_a_window_nobody_could_read_escalates_with_a_postmortem` -
which is what it was always testing.

The disproof therefore needs a case of its own, and a scenario that keeps the
shop reporting while every judged series stays flat. `silent-data-corruption` is
one by construction: nothing throws so the error rate never moves, nothing waits
so no quantile moves, the heap is flat, the shop is the right size, the cache is
answering and the process has been up for hours. Seeding it supplies the window;
the alert is the suite's own, which states no onset and says nothing about what
it watched, so it arrives as a series claim. The scenario's own weekly check is
never posted and its deliberate onset never enters the case.

Nothing else green reaches the branch: `silent-data-corruption`,
`cache-failed-over` and `monitoring-blind-spot` all have flat or absent windows
and all state an onset, so all three take the branch that already exists for a
stated onset.

## Open Questions

- Whether the dashboard should list a disproven incident with the live ones or
  apart from them. It is an ending, so it belongs with the endings; whether a
  reader scanning for real incidents wants it in the same list is a question
  about the page rather than about the walk.
- Whether a run of disproven alarms on the same rule is worth reporting as
  something in its own right. It is the most useful thing this status makes
  possible and it needs no part of this change, so it is noted rather than built.
