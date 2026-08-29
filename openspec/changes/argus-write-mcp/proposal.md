## Why

Argus can diagnose an incident and cannot do anything about it. `mitigate()` is a
stub that returns `"confirmed"` without taking an action or checking one, so the
`mitigating -> resolved` transition the FSM already drives is a formality: the
incident is marked resolved while the flag is still on and the shop is still
failing.

Until now that stub could not have been replaced honestly. The Target Service's
telemetry was a canned fixture, so an agent that "reverted" something and
re-queried the metrics would have read back the same authored minutes either way
- confirmed and refuted were both fiction. Telemetry is now a read-time function
of live flag state, which means a revert genuinely changes what the next read
returns, and a verdict can be earned rather than asserted.

## What Changes

- **A write-tier MCP server joins the stack.** `argus-write-mcp` is a separate
  process from `argus-read-mcp` (§12.1), holding the flag provider's admin
  credential - which the read server is issued none of - so the autonomy tier is
  a property of which process is running, not a convention the caller observes.
- **One tool on it: revert a feature flag.** Turning the flag off in the
  provider, with the flag's prior state carried back as an undo descriptor.
  `push_revert_commit`, `open_pull_request`, Slack and email are named in §12.1
  and are **not** in this change - each needs its own vendor integration, and
  none is unblocked by live telemetry the way the flag is.
- **A typed client package**, `write_mcp_client`, mirroring `read_mcp_client`:
  each tool a real typed function, not `call_tool(name, **kwargs)`.
- **The Mitigation agent becomes real.** It maps the hypothesis's `cause_type` to
  a reversible action **in code, with no model call** - the Investigator already
  made the judgement, and a model between a verdict and a write can only
  hallucinate an action or pick one that exists anyway. It then takes the action
  and re-queries the same metrics channel the Investigator read, returning
  `confirmed` or `refuted` according to what the error rate actually did.
- **The Orchestrator gains its gate node** (§13): an action reaches its mutating
  call only with a populated undo descriptor, and the descriptor is persisted on
  the `action` row that records it.
- A hypothesis whose `cause_type` has no mapped reversible action escalates
  rather than resolving - "nothing I can safely do" is an outcome, not a failure.

## Capabilities

### New Capabilities
- `write-mcp-server`: the write-tier MCP server and its typed client - what the
  process is capable of, which credentials it holds, the flag-revert tool, and
  the undo descriptor every action carries.
- `flag-revert-mitigation`: the Mitigation agent - choosing a reversible action
  from a cause, taking it, and earning a confirmed/refuted verdict from
  re-queried metrics rather than asserting one.

### Modified Capabilities
- `incident-lifecycle`: the mitigation node's outcome now comes from a verified
  action rather than a stub, the gate node stands between an action and its
  call, and an action row carries its undo descriptor.

## Impact

- New modules `modules/write_mcp_server/` and `modules/write_mcp_client/`, both
  auto-discovered by `noxfile.py`.
- `modules/agent_mitigation/` gains a real implementation and a dependency on
  `write_mcp_client` and `read_mcp_client`; `mitigate()`'s signature changes from
  a summary string to the whole `Hypothesis` (§7.3 needs `cause_type`).
- `modules/orchestrator/`: a gate node in the graph, and `actions.record` gains
  the undo descriptor the `action` table already has a column for.
- `argus_core.config`: the flag provider's admin credential and base URL, held by
  the write server alone. Spec §14 places secrets in Vault; this change keeps
  them in settings like every other credential here today, and does not
  introduce Vault.
- `docker-compose.yml` and `noxfile.py`: a second MCP process to bring up.
- `tests/e2e/`: the flag-toggle case can assert that the flag is off and the
  shop recovered, rather than only that Argus said so.
