## Context

Every incident Argus has handled arrives the same way: a rule fires on a series,
the Investigator retrieves a window anchored on the alert, `find_onset` measures
the minute the service departed its own baseline, and everything downstream -
the change channels it reads, the candidates it ranks, the recovery it waits for
- hangs off that minute.

Silent data corruption breaks the first link. Nothing fails and nothing slows, so
no rule fires; and if one is made to fire, the window it anchors is flat, so
[investigation.py:303-307](../../../modules/agent_investigator/src/agent_investigator/investigation.py#L303-L307)
returns `_nothing_to_say` before a model is asked. It also breaks the last link:
the only thing that could confirm a mitigation is the next run of a check that
runs weekly, and the verification window is minutes.

So this change is two structural questions with a scenario attached, rather than
a scenario with some plumbing attached.

## Goals / Non-Goals

**Goals:**

- An incident can be detected by something other than a health series, and dated
  by something other than a measurement.
- An action Argus is confident in but cannot confirm is named and not taken, by a
  rule rather than by this scenario's special case.
- Every existing recording stays valid.

**Non-Goals:**

- Repairing the data. The repair is proposed as a script and never executed.
- The deploy-caused sibling. A week-old deployment cannot be rolled back, so that
  version has no action to recommend at all and only a fix rolled forward; it is
  the next scenario, not a branch of this one.
- Re-asking the integrity check. Argus reads what the alert carried, once.
- Slack inbound, a human answering, or any other new way for evidence to arrive.

## Decisions

### The finding travels in the alert, not in a sixth retrieval channel

A tool would be the ordinary answer - five channels exist and a sixth is a
well-worn path. It is refused here for a reason that is about the recordings
rather than about taste. The Investigator's tool list is part of every request
the model sees; the double replays by scenario name and call index and would go
on replaying happily, but each stored answer would be an answer from a model that
never had the new tool. That is a corpus that lies, and the honest response is a
full re-record: eleven scenarios at roughly five dollars each.

What the tool would buy is the ability to ask again. Argus is never going to act
here, so it never needs to confirm anything, so it never needs to ask twice. The
one reading the alert carries is the whole channel.

*Alternative considered:* a tool, and re-record everything. Rejected on cost
against a benefit this mode does not use.

### The onset is accepted from the alert when the alert states one

`find_onset` stays exactly as it is, and stays first. Where it finds a minute,
that minute wins - a measured onset is evidence and a stated one is testimony.
Where it finds none **and the alert states one**, the stated minute is used, and
the opening message says plainly that no series corroborates it, in the same
place and manner the existing "opens already elevated" sentence says a window may
not contain the cause.

Where it finds none and the alert states none, `_nothing_to_say` is reached as it
is today. That is the branch every existing scenario relies on and it is
unchanged.

*Alternative considered:* a separate walk for alerts that carry their own onset.
Rejected - it forks the pipeline on a difference that is one field wide, and the
Investigator's whole job downstream of the onset is identical either way.

### The gate declines the action; Mitigation is untouched

Naming an action and taking one are already two steps, split by
[gating.py](../../../modules/orchestrator/src/orchestrator/walk/gating.py). So
Mitigation chooses the flag revert it would choose for any flag-caused incident,
and the gate refuses it with a sixth `Refusal`.

The refusal differs from the five that exist in where it goes. Those reach for
the next candidate, because what they reject is *this* action. This one rejects
the whole possibility of confirming any action on this incident, so a second
candidate is no better placed than the first: it stops, and the incident ends at
`RECOMMENDED` carrying the action nobody took.

*Alternative considered:* a node before Mitigation that decides the incident is
unactionable. Rejected - it would have to guess what action was coming in order
to name one, which is Mitigation's job, and the incident would end recommending
nothing.

### `RECOMMENDED` is its own status, not a kind of escalation

`ESCALATED`'s own definition is Argus running out of moves. Here there is a move
and Argus is declining it, and the difference is the only thing a reader of the
outcome actually needs: one says nobody knows what to do, the other says somebody
should go and do this. A shared status would erase it, which is the argument
`WITHDRAWN` was already given against sharing one with escalation.

Terminal, and past tense, matching the other four.

### Verification is what decides autonomy, stated as a rule

Written as a general requirement - an action whose confirmation cannot arrive
inside the verification window is recommended and not taken - rather than as a
mode-to-status mapping. A mapping would be a table saying *this mode is special*;
the rule says why, and it is the same reason a person would give.

### The check is the shop's, and its interval is the shop's

Argus does not run the check, cannot trigger it, and does not get to choose how
often it runs. The demo stages weekly because that is the interval that makes the
mode what it is, but the design holds for any interval: whatever Argus is handed,
the alert carries a finding and a date, and Argus reads them.

## Risks / Trade-offs

- **The onset change is on a path all ten existing scenarios walk.** → The
  `None`-and-no-stated-onset branch is left byte-identical, so the existing path
  is the untouched one; `e2e_replay` covers every scenario for free and runs
  before anything is recorded.

- **We do not yet know the mode is investigable.** The model gets an alert, a
  flat window and a change history around a minute a week back. The tools for the
  rest exist - flag history, deploy history, the diff from GitHub - and the
  alert's date narrows a week of changes to an hour's worth, but whether that is
  enough to name a cause is unknown until a paid run. → Prove the whole walk
  under the double first, with the scenario's answers hand-authored, so the paid
  run is spent only on whether the model reads it.

- **`RECOMMENDED` has never happened, so its first recording is also its first
  evidence.** If the model proposes and the gate takes the action anyway, that is
  a paid run to discover. → The gate's refusal is deterministic and not the
  model's to make; it is provable under the double before recording.

- **`IncidentStatus` reaches 69 files.** About ten are source and the rest are
  suites, each a TDD cycle the user pastes. → Mechanical, but it is the bulk of
  the elapsed time and should be sequenced early, not discovered late.

- **The scenario's telemetry must be genuinely flat.** A scenario that moves any
  judged series by accident is a scenario that gets found the ordinary way, and
  the whole point evaporates. → Assert flatness directly: every judged series at
  its baseline across the window, as the existing scenarios assert their shapes.
