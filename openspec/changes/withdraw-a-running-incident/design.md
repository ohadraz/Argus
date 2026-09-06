## Context

An incident Argus is walking cannot be stopped. The walk never reads its
incident back: status flows outward from the graph's own state through
`with_status`, and nothing flows in. The worker walks one incident at a time on
one thread (`work_forever` → `take_one_run` → `run_incident`), and the only slow
things inside it are a model call and the recovery-verification loop.

Two consequences, one for each audience:

- A human who fixes the failure themselves cannot tell Argus. It goes on to act
  on a healthy service, sees the recovery they caused, and records the
  mitigation as its own.
- The e2e suite cannot stop what it started. A case ends when its assertion
  holds - the webhook answers `202` as soon as the incident row exists - so the
  previous walk is still running when the next case resets the world and seeds
  the Anthropic double, and drains answers meant for somebody else. It is also
  why nothing is ever cleaned up: with a walk possibly still writing, the suite
  cannot safely empty a table, so incidents, hypotheses, actions, timelines,
  events, replay rows and postmortems accumulate across the whole run.

## Goals / Non-Goals

**Goals:**

- A live incident can be withdrawn, from the incident page and from a test.
- The walk notices within seconds and stops before its next act.
- What Argus changed is put back, unless somebody else has since changed it.
- The incident says what happened: withdrawn, what had been done, what each undo
  step found.
- The e2e suite uses the same door, then empties the database.

**Non-Goals:**

- Identity or authorisation. Withdrawal is anonymous; the timeline says "a
  human", not who. Argus has no identity system and inventing one here is a
  separate change.
- Resuming a withdrawn incident. Withdrawal is terminal; a failure that recurs
  raises a new alert and a new incident.
- Interrupting a model call in flight. There is no seam below the SDK, and
  inventing one buys tens of seconds at the cost of a partial conversation
  nothing can replay.
- Detecting that a human fixed the service without being told. Argus cannot
  distinguish that recovery from its own, which is exactly why the human needs
  a button.

## Decisions

### Withdrawal is a status, not a flag beside one

`IncidentStatus.WITHDRAWN`, terminal, alongside `resolved` and `escalated`. The
walk asks one question - "is this incident still live?" - and that is what a
status is for. A separate `withdrawn_at` column would make "has this ended"
two reads that can disagree, and every consumer (the history page, the live
view's polling, `is_terminal`) would need teaching about the second one.

*Alternative considered:* a boolean `cancelled` column, leaving the status as
whatever the walk last derived. Rejected: it makes a withdrawn incident display
as `mitigating` forever, and every reader has to remember to check both.

### The status derivation stays pure; the write is what respects the withdrawal

`status_after` remains a pure function of walk state and never returns
`withdrawn` - it cannot, because withdrawal is not something the walk's state
records. The check goes in `with_status`, which is already the single place a
transition is persisted and published: before writing, it re-reads the
incident's status, and where that is terminal it writes nothing and stops the
walk. This keeps `incident-status-derivation`'s central promise (nodes do not
decide status; the derivation does no I/O) intact.

*Alternative considered:* making `status_after` take the persisted status as an
input. Rejected: it puts a database fact into a pure function's signature and
every caller then has to supply one.

### The walk unwinds itself; the withdrawal only marks

The withdrawal endpoint writes the status and returns. It does **not** undo
anything. The walk, on seeing the withdrawal at its next boundary, runs the
unwind as its last act and settles its run.

This preserves the Orchestrator's single-writer rule. The alternative - the web
process undoing actions while the worker is mid-step - is two writers on one
incident, racing to write outcomes for the same action rows.

The case that needs care is an incident nobody is walking: a run still `queued`,
or one whose worker died. Neither has taken an action, or in the dead-worker
case may have. So `claim` gains one rule: a claimed run whose incident is
terminal is not walked - it is unwound (which is a no-op when no action was
taken) and settled. The dead-worker case is then covered by the existing lease
expiry, with no new mechanism.

### The check goes in two places, not everywhere

1. `with_status` - covers every node boundary, which is every place the walk
   decides to do something next.
2. The recovery-verification loop in `agent_mitigation`, which already wakes
   every ten seconds to re-read metrics. The check sits beside the recovery
   check, so withdrawal takes effect within one interval rather than at the end
   of a six-minute window.

`agent_mitigation` must not learn about the database, so it takes an injected
`still_wanted: Callable[[], bool]` defaulting to a function that always answers
`True` - the module's existing injection style, and the seam a unit test drives.

Nowhere else. A check sprinkled through the retrieval loop buys milliseconds and
costs a database read per tool call.

### The undo compares against what was written, not what was planned

`undo_descriptor` already records `was_enabled` as read at write time, returned
by the write itself. It gains the value Argus wrote, so the undo can ask "does
the flag still hold this?" before restoring. Where an old row has no such
field, the value written is `action.enabled` - the same number - so no
migration is needed.

Three outcomes per undo step, all recorded and narrated: restored; left as
found because it holds something Argus did not write; not established because
the current state could not be read. The third is not a success and must not be
reported as one.

*Alternative considered:* a provider-level compare-and-swap. Rejected: Unleash
offers no conditional write, so the comparison is a read followed by a write
either way. The gap between them is real and is the reason the undo exists at
all - it is the compensation for that gap, not a way of closing it.

### The e2e teardown withdraws, waits for the run, then truncates

In order: withdraw every non-terminal incident; wait until no run is `queued` or
`running`, bounded by a timeout that fails loudly rather than hanging; truncate
every table, asking the database which tables exist, exactly as
`tests/integration/conftest.py` already does; then reset the Target Service
scenario, the flags and the double, as today.

The wait is bounded by one in-flight step, which is seconds - not by the walk,
which is minutes. `exchange_rate` is emptied along with the rest by the
ask-the-database query; it is a cache keyed by day and re-fetching costs one
call against the Target Service's own endpoint.

*Alternative considered:* killing and restarting the worker between cases.
Rejected on two counts. It leaves the run row `RUNNING` with a lease, which
`claim` deliberately reclaims and *resumes* - so the abandoned incident returns
mid-suite. And the worker is started by nox as a sibling process of pytest
([noxfile.py](../../../noxfile.py)); the suite holds no handle on it and cannot
reconstruct the environment it was started with.

## Risks / Trade-offs

- **A withdrawal landing between the check and the flag write still changes the
  flag.** → Not closable, only compensated: the unwind puts it back, and puts it
  back conditionally so it cannot clobber a human who changed it in the
  meantime.
- **A model call in flight delays the stop by up to a call.** → Bounded and
  visible: the incident reads as withdrawn immediately; only the unwind waits.
  The e2e teardown inherits that wait, which is why its timeout must be
  generous enough not to fire on a slow call and loud enough to be read as a
  bug when it does.
- **A withdrawn incident writes no postmortem, so it reports no cost.** →
  Accepted: nothing concluded, so there is nothing to write up. The replay log
  still records what was spent.
- **One extra read per node boundary and per recovery poll.** → Negligible
  beside a model call, and it is a primary-key lookup.
- **`e2e-replay` currently proves nothing about cleanup.** → The truncation is
  itself only exercised by the suite it protects, so a case asserting on a
  previous case's row would still pass. Ordering the suite's own assertions
  against an empty history is what makes that visible.

## Open Questions

- Should withdrawal post to the Communicator (once it exists) the way a page
  does? Deferred - there is no Communicator yet, and the timeline carries it.
