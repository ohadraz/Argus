## Why

The change channel has one source. Deploys reach the Investigator as change events;
feature flags do not, even though a flag flip is the change Argus is best equipped to
act on - it is the one cause with a reversible action behind it.

Today a toggle is only found when the service happens to log it. `feature-flag-toggle`
is a `CauseType` and the mitigation walk is built to undo one, so an investigation whose
cause is a flag is relying on the Target Service having said so in a log line Argus's
window happened to cover. That is a cause found by luck, and the luck runs out on the
first service whose logging is quieter.

## What Changes

- `ChangeKind` gains `FLAG_TOGGLE` beside `DEPLOY`, so the model can weigh one against
  the other rather than reading "something changed".
- `fetch_change_events` reads two histories and merges them into one time-ordered list:
  deploys from `argus-read-mcp`, flag toggles from the flag provider's audit log.
- The audit log is read through `write_mcp_client.get_recent_flag_changes`, the
  read-only call the write tier already offers - see `design.md` for why it is not in
  the read server.
- `agent_investigator` gains a workspace dependency on `argus-write_mcp_client`.

## Impact

- **Affected specs**: `change-event-retrieval`
- **Affected code**: `argus_core.models.change_event`, `agent_investigator.retrieval`,
  `modules/agent_investigator/pyproject.toml`
- **Not affected**: the read tier's own change source, the dispatcher, the tool schema.
  The channel's window, defaults and failure rule are unchanged - a second source
  answers the same question over the same window.
