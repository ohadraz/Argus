Argus's own modules are TDD: the test is proposed in chat, the user adds it, then
the implementation follows. `tests/`, `modules/argus_testkit/` and
`modules/anthropic_double/` cannot be written by Claude.

## 1. Shared anomaly judgement

- [x] 1.1 Move the anomaly classification (`find_onset`,
      `earliest_bucket_is_anomalous`, and the departure threshold behind them)
      from `agent_investigator.anomaly` into `argus_core`, and have
      `agent_investigator` import it from there. A move, not a rewrite - the
      Investigator's existing tests are what prove it.
- [x] 1.2 Add the recovery-side question the same rule answers: whether the
      minutes after a given moment still depart from the window's baseline.
      Propose the test first.
- [x] 1.3 `nox -s test_all` green, with the Investigator's own anomaly tests
      unchanged.

## 2. The read tier learns to report flag state

- [x] 2.1 Add a flag-evaluation adapter to `read_mcp_server`: which flags are
      enabled in the configured environment, read over the provider's evaluation
      API with the evaluation credential only.
- [x] 2.2 Expose it as an `@mcp.tool()` and as a typed function on
      `read_mcp_client`.
- [x] 2.3 Confirm by hand against the running provider that enabling and
      disabling a flag changes what the tool reports.

## 3. `argus-write-mcp`

- [x] 3.1 Scaffold `modules/write_mcp_server/` and `modules/write_mcp_client/`
      (see the `new-module` skill), reusing `argus_core.mcp_transport`.
- [x] 3.2 Settings for the provider's admin credential, held by the write server
      alone - and confirm the read server's configuration carries no credential
      able to change state. Add every new variable to `.env.example` with the
      comment saying what it is for, beside the existing secrets; `.env` itself
      stays gitignored and no real value goes anywhere else.
- [x] 3.3 The flag-state tool: set a named flag on or off in the configured
      environment, return only once evaluation agrees, and fail loudly rather
      than reporting an unchanged flag as changed. One tool for both directions -
      an agent that can only turn flags off cannot mitigate a flag that was
      turned off.
- [x] 3.4 Return the undo descriptor with the result - the prior state, not the
      inverse call - carrying whichever state the flag was actually in.
- [x] 3.5 The typed client function, so no caller names a tool as a string.
- [x] 3.6 Bring the process up in the nox stack helper, beside
      `argus-read-mcp`. *Compose needs nothing: neither MCP server is
      containerised - both run as local processes, per the previous change's
      design decision.*
- [x] 3.7 The flag-change read: which flags the provider recorded as toggled in
      the environment since a given moment, and in which direction. On the write
      server, because the provider issues no credential that reads its history
      without also being able to change a flag. Fail loudly rather than
      reporting an empty history, and expose it through the typed client too.

## 4. The Mitigation agent

- [x] 4.1 `propose_action(hypothesis, flag_changes)` - pure, no I/O, no model:
      `cause_type` to a reversible action carrying its undo descriptor, or
      `None`. The action names the state to set, in whichever direction undoes
      the change.
- [x] 4.2 Resolve the flag to revert from the flag-change read - the latest
      change per flag; none or more than one flag takes no action. Not from
      current state: a flag switched off into an incident looks exactly like one
      that was always off.
- [x] 4.3 `take_action(action)` - perform it through `write_mcp_client`, then
      verify: poll until a metric bucket exists whose minute began after the
      action, and judge it with the shared anomaly rule.
- [x] 4.4 A configured verification timeout, whose expiry is `refuted` rather
      than an error.
- [x] 4.5 Undo a refuted action: restore the state named in its undo descriptor
      before the incident proceeds, and escalate carrying both facts if the
      restore itself fails. A confirmed action stays in place.
- [x] 4.6 Replace `mitigate()`'s summary-string signature with the whole
      `Hypothesis`.

## 5. The Orchestrator

- [x] 5.1 Add the tier-gate node between the proposed action and the call that
      performs it, rejecting an action whose undo descriptor is absent or empty.
- [x] 5.2 Route a gated or unproposed action to `escalated`; keep `confirmed` to
      `resolved` and `refuted` to `fixing`.
- [x] 5.3 Persist the undo descriptor on the `action` row - the column already
      exists.
- [x] 5.4 Update the mitigation node and its tests for the new signature.

## 6. End to end

- [x] 6.1 Propose in chat the e2e edit asserting the world changed: after the
      flag-toggle incident resolves, the flag is off in the provider and the
      Target Service's recent minutes are at baseline.
- [x] 6.2 A case where mitigation cannot act - two flags changed - escalates
      rather than reverting one of them.
- [x] 6.3 A case where the action does not help: the flag goes off, the symptom
      persists, and the flag is found back on afterwards with the incident in
      `fixing`.
- [x] 6.8 The other direction end to end: a scenario in the demo Target Service
      whose fault is a flag being switched *off*, and an incident that mitigates
      it by switching the flag back on.
- [x] 6.4 `nox -s lint typecheck test_all guard_e2e_boundary integration
      contract` green.
- [x] 6.5 `nox -s e2e_replay` green - the double replays by recording name, so
      this proves the pipeline, not the verdict.
- [x] 6.6 `nox -s e2e` green (paid - ask first).
- [x] 6.7 Watch it once in the browser: apply the scenario from the console,
      trigger the alert, and see the error rate fall without touching Unleash.

## 7. Commit

- [x] 7.1 One approved single-line message.
