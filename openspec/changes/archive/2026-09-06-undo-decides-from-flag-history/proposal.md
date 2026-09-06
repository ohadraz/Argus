## Why

Undoing a change asks whether the flag still holds what Argus wrote, and it asks
the provider's *evaluation* API - a cache the provider refreshes on its own
interval. A human who changes a flag after Argus acted is therefore invisible for
as long as that cache is stale, and Argus overwrites them. It is the one thing
the conditional undo exists to prevent, and the check as written cannot prevent
it: nobody in production waits for a cache.

It surfaced in CI rather than in reasoning. `test_a_flag_changed_from_outside_is_left_alone_when_the_incident_is_withdrawn`
changed a flag from outside and withdrew the incident; the undo read the stale
evaluation, found what Argus had written, and restored over the change. The same
race is in the ordinary refuted-action undo, where nothing is being withdrawn and
nobody is watching.

## What Changes

- The conditional undo decides from the flag's **change history** - has this flag
  been changed since Argus wrote it, by anybody but Argus - instead of comparing
  the flag's current value against the value Argus wrote.
- The history is read through the write tier's existing flag-change reader, which
  holds the admin credential and reads the provider's event log. Mitigation
  already calls it to answer "who changed this flag"; nothing new is granted.
- The value comparison stops being the authority. Where the history cannot be
  read at all, the undo reports that the state could not be established, as it
  does today - it does not fall back to the cached value and guess.
- A human who toggles a flag off and back on again is now seen. The value
  comparison read that as untouched, because the value came back to what Argus
  had written; the history says plainly that somebody was in there.

## Capabilities

### New Capabilities

None. This changes how an existing decision is made, not what Argus can do.

### Modified Capabilities

- `conditional-action-undo`: the condition is a change-history question rather
  than a value comparison, and the requirement that named the comparison
  ("the comparison is against the value written, not the value planned") is
  replaced by one naming the authority it asks.
- `flag-revert-mitigation`: the refuted-action undo inherits the same rule, so
  its scenario for a flag changed from outside is judged on the history.

## Impact

- `agent_mitigation`: `undo_change` and the seam it reads the world through -
  today `enabled_flags` from the read tier, replaced by the write tier's
  `get_recent_flag_changes`.
- `orchestrator.unwinding` is unaffected: it owns which changes are undone and in
  what order, not how one is judged.
- The read tier's `get_enabled_flags` keeps every other caller it has; only the
  undo stops asking it.
- The e2e case above stops being a race and starts asserting the behaviour.
