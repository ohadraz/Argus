Under TDD: every task below is implemented against a test proposed in chat and
added by the user first, except where it says otherwise.

## 1. The moment Argus wrote

- [x] 1.1 `write_mcp_server.flag_state` records the provider's own timestamp for
      the write into the undo descriptor it returns - the provider's, not
      Argus's clock, so `since` and the events it filters share one
- [x] 1.2 `write_mcp_client.set_feature_flag` passes it through unchanged; the
      descriptor is the tier's answer, not something the client re-shapes
- [x] 1.3 Confirm the descriptor still validates where the gate node reads it
      (§13), and that a descriptor is still what the gate requires

## 2. The question the undo asks

- [x] 2.1 A `RecentFlagChanges` seam on `agent_mitigation`, beside the existing
      `FlagSetter`, defaulting to `write_mcp_client.get_recent_flag_changes`
- [x] 2.2 `undo_change` asks it for the changes since the descriptor's moment,
      drops Argus's own with `argus_core.attribution.changes_not_made_by`, and
      restores only where nothing is left
- [x] 2.3 A flag changed and changed back reads as changed - the history says
      somebody was in there, and the value comparison could not
- [x] 2.4 A descriptor carrying no moment answers `NOT_ESTABLISHED`; a history
      that cannot be read answers the same, and neither writes
- [x] 2.5 Where the provider attributes nothing, the flag is left as found rather
      than restored on an attribution nobody has
- [x] 2.6 `undo_change` stops taking `enabled_flags`; every other caller of
      `read_mcp_client.get_enabled_flags` keeps it

## 3. The suites

- [x] 3.1 `agent_mitigation`'s unit tests cover the five answers above through
      the new seam
- [x] 3.2 The e2e case `test_a_flag_changed_from_outside_is_left_alone_when_the_incident_is_withdrawn`
      passes without waiting on the provider's evaluation cache - it is the case
      that found this, and it stops being a race
- [x] 3.3 `e2e_replay` green, and CI green - `main` is red on this exact case
      until it is

## 4. Settling up

- [x] 4.1 `docs/spec-and-architecture.md`: the undo's condition, written as
      though it were always the intent - what is asked, of which tier, and why
      the evaluation API cannot answer it
- [x] 4.2 A full sweep, green
