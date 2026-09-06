## Context

`undo_change` asks one question before it writes: is this flag still holding what
Argus wrote? It answers it by reading the flag's current value from
`read_mcp_client.get_enabled_flags`, which is the provider's `/api/frontend`
evaluation endpoint - a cache the provider refreshes on its own interval. So the
answer is not "has anybody changed this", it is "had the cache caught up".

Mitigation already reads the provider's event log for a different question. It
imports `get_recent_flag_changes` from `write_mcp_client` to learn which flag an
incident is about and which way it moved, because current state cannot answer
that: a flag switched off into an incident evaluates exactly like one that has
been off for a year. The same log answers this question too, and answers it
authoritatively - it is the provider's audit record, not a projection of it.

`argus_core.attribution.changes_not_made_by` already separates changes Argus made
from everybody else's, using the actor the provider records.

## Goals / Non-Goals

**Goals:**

- An undo leaves a flag alone whenever somebody has changed it since Argus wrote
  it, with no dependence on when a cache refreshes.
- The three outcomes stay exactly three - restored, left as found, not
  established - and an unreadable history is `NOT_ESTABLISHED` rather than a
  guess from the cached value.
- A change made and reverted by a human (off, then on again) reads as somebody
  having been in there, which value comparison cannot see.

**Non-Goals:**

- Changing what `get_enabled_flags` is for, or who else calls it. Reading what
  the service currently sees stays a read-tier question.
- Changing which changes get undone or in what order - that is
  `orchestrator.unwinding`, and it is unaffected.
- Attribution where the deployment gives Argus and its operators one credential.
  `changes_not_made_by` already documents that it filters nothing there, and this
  inherits that: an undo that cannot tell Argus's writes from a person's leaves
  the flag alone rather than overwriting a change it cannot account for.

## Decisions

**The condition becomes a question about the log, not the value.** "Has this flag
changed since Argus wrote it, by anybody but Argus" is the question the
requirement was always describing; the value comparison was a proxy for it that
holds only while nobody else is writing and the cache is fresh.

**The write tier serves it.** The log needs an admin credential and the read tier
holds none by design (§13). `write_mcp_client.get_recent_flag_changes` is already
in Mitigation's imports for the investigation-side question, so this grants
nothing new and adds no dependency - the seam moves from `EnabledFlags` to a
`RecentFlagChanges` one alongside it.

**The descriptor carries the moment Argus wrote.** `get_recent_flag_changes`
takes a `since`, and the undo has nothing to give it today: the descriptor
records what the flag *was*, not when it was set. `set_feature_flag` builds the
descriptor at write time and is the one place that knows the answer, so it adds
the write's own timestamp to it. This is not a second copy of the state - it is
the one fact the descriptor is missing, and the alternative (the action row's
`created_at`) is the time the row was written rather than the time the provider
recorded the change.

**A descriptor with no timestamp is `NOT_ESTABLISHED`.** Rows written before this
change carry no `written_at`, and an unwind that met one and guessed would be the
present bug with a different cause. Saying it cannot be established is honest and
is already one of the three answers.

**Where the log is unreachable, nothing is written.** `get_recent_flag_changes`
raises rather than reporting an empty history, which is what makes this safe: an
outage becomes `NOT_ESTABLISHED`, never "nobody has touched it".

## Risks / Trade-offs

**The log is now on the undo path.** A provider whose event API is down blocks
every undo, where today a stale-but-available evaluation would have let one
through. That is the trade being made deliberately: a blocked undo is reported
and visible, and an undo that overwrites a human's deliberate change is neither.

**Clock skew between Argus and the provider.** `since` is the provider's own
timestamp for Argus's write, taken from the write's response rather than from
Argus's clock, so the comparison stays inside one clock.

**A human whose change the provider attributes to Argus is still invisible.**
Shared credentials defeat attribution, here as everywhere else in this system;
`changes_not_made_by` reports it the same way and this does not make it worse.
The e2e suite writes under the shop's own admin token precisely so the case being
tested is a change Argus can tell apart.
