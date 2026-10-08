# Log sites

This is the working list for task group 6, surveyed on 2026-10-08 against `main` at `62c07d1`. Line numbers are as of that commit. Levels follow the `process-logging` spec. Re-read each site before writing its line, because a survey is a lead, not a verdict.

## How the list was applied

The sites below are the survey. Applying them, four rules took sites out:
- **DEBUG sites were not added.** Only INFO and above get a line and a test in this change.
- **One event, one INFO.** An agent INFO whose content is only its verdict or outcome is already said by the orchestrator: `walk/mitigating.py` "verdict reached", `walk/fixing.py` "fix attempted", or `walk/narrating.py` "status changed" with its reason. That covers the orchestrator's escalation branches as well (`mitigating.py` `:78`, `:333`, `:392`; `choosing.py` `:123`, `:133`), and Mitigation's and Code-Fix's INFO sites in `trying.py` and `proposing.py`.
- **A refusal before anything changed is no production change.** "No earlier revision", "already at its largest", "already held", "already pinned" and "nothing to discard" get no INFO; the walk's verdict line reports them.
- **A site whose caller already logs the event has no line.** `comparing.py:97` and `engagement.py:171`, below.

`unwinding.py:117` is covered by the worker: "incident withdrawn, unwinding" before a withdrawal's unwind, and "run failed" before a failed run's.

Lines with no test, because they are written by a `main` that has no seam: `watching.main`'s two, `catching_up.main`'s "no index kept" and "index catch-up started", and the worker's "incident could not be marked escalated" and "claim could not be renewed".

## Cross-cutting

- **INFO is dropped today** in the read and write MCP servers and in `argus_web`. Their mains never set a root level, so the root stays at WARNING. D1 fixes this for every process.
- **Every process's start, stop and death** is logged once, by the telemetry context manager (D10). No `main` logs them itself.
- **Two places cover many sites at once:**
  - `orchestrator/walk/narrating.py:110` sees every status transition;
  - `argus_core/mcp_transport.py:738` sees every failed tool call on both servers.

  Log there, rather than at each site.
- **Never log every published event** in `argus_core/events.py` `publish`. That is per poll, which breaks the INFO rule. DEBUG at most.
- **One event, one INFO.** A production change is INFO where it is made, in the write server. The orchestrator logs the decision to take it at DEBUG and the verdict on it at INFO.

## Re-levelled existing lines

- `orchestrator/worker.py:120` lease renewal failed: WARNING with `exc_info`. The walk carries on.
- `orchestrator/worker.py:294` waiting for runs: becomes `"service started"` (D10), so delete it.
- `code_index/catching_up.py:178` pass failed: WARNING with `exc_info`. It is retried on the next wake.
- `agent_communicator/slack.py:181`: WARNING when `worth_another_go`, ERROR on a permanent refusal (the line is lost).
- `agent_communicator/delivering.py:174`: per message, so DEBUG.
- `argus_core/schema.py:159`: stays INFO. `schema` is a one-shot job, not a telemetry process.
- The rest stay at their current level and are rewritten to D8's shape.

## orchestrator

- **`worker.py`**
  - `:177` INFO: run claimed.
  - `:179` INFO: already withdrawn, not walked.
  - `:182` INFO: withdrawn during the walk, unwinding.
  - `:191` INFO: run finished.
- **`entrypoint.py`**
  - `:150` INFO: walk started.
  - `:210` INFO: walk ended, with `outcome` and `duration_s`.
- **`unwinding.py`**
  - `:117` INFO: unwinding, with `actions`.
  - `:119` DEBUG: the discard owed no undo.
  - `:136`: INFO when RESTORED or LEFT_AS_FOUND, ERROR when NOT_ESTABLISHED.
- **`walk/narrating.py`**
  - `:87` INFO: withdrawal noticed.
  - `:110` INFO: status changed, with `from_status` and `to_status`.
- **`walk/choosing.py`**
  - `:88` INFO: candidate chosen.
  - `:123` WARNING: no reachable candidate, escalating.
  - `:133` INFO: re-investigating, with `round` and `max_rounds`.
  - `:145` INFO: candidates exhausted.
- **`walk/candidates.py`**
  - `:177` DEBUG: skipped, not actionable or already tried.
  - `:180` DEBUG: skipped, platform unreachable.
- **`walk/gating.py`**
  - `:159` DEBUG: admitted.
  - `:162` INFO: refused by the gate.
  - `:186` INFO: recommended, not taken.
  - `:202` INFO: no mitigation answers.
- **`walk/proposing.py`**
  - `:39` DEBUG: nothing proposed.
  - `:42` DEBUG: proposed.
- **`walk/mitigating.py`**
  - `:78` ERROR: broken invariant.
  - `:84` DEBUG: claim already held.
  - `:107` DEBUG: taking the action.
  - `:152` INFO: verdict.
  - `:200` WARNING: platform unreachable.
  - `:333` WARNING: earlier outcome unreadable, escalating.
  - `:343` DEBUG: reusing the earlier verdict.
  - `:389` DEBUG: the claim never landed, retaking.
  - `:392` WARNING: landed but unmeasured, escalating.
- **`walk/investigating.py`**
  - `:113` INFO: alarm disproven.
  - `:161` DEBUG: memory recalled.
  - `:190` DEBUG: memory reordered.
  - `:224` INFO: round result.
  - `:296` WARNING `exc_info`: flag history unreadable.
  - `:343` WARNING `exc_info`: deployment history unreadable.
- **`walk/fixing.py`**
  - `:47` INFO: out of budget.
  - `:61` INFO: model declined.
  - `:75` WARNING `exc_info`: fix not proposed.
  - `:94` INFO: no fix warranted.
  - `:104` INFO: draft PR opened.
- **`walk/remembering.py`**
  - `:53` DEBUG: nothing worth remembering.
  - `:58` WARNING `exc_info`: the store refused.
  - `:72` INFO: remembered.
- **Elsewhere in the orchestrator**
  - `walk/assembling.py:182` INFO: memory disabled (startup).
  - `rates.py:68` WARNING: rate provider down, falling back.
  - `sources.py:168` WARNING: engagement unavailable.
  - `sources.py:194` WARNING: pay bands unavailable.

## agent_mitigation

- **`trying.py`**
  - `:218` INFO: exhausted.
  - `:246` WARNING: platform unreachable.
  - `:282` WARNING `exc_info`: could not perform, escalated.
  - `:304` DEBUG: confirmed. The orchestrator's verdict is the INFO.
  - `:327` WARNING: nothing measured, change left in place.
  - `:343` INFO: withdrawn mid-wait.
  - `:358` DEBUG: refuted, undoing.
  - `:741` WARNING: metrics read failed.
  - `:826` WARNING: rule read failed.
  - `:1075` WARNING: platform stopped applying the change.
  - `:1085` WARNING: change late.
  - `:1249` DEBUG: nothing to put back.
  - `:1268` ERROR: undo not established, production left changed.
  - `:1274` INFO: left as found.
  - `:1280` INFO: restored.
- **`undoing.py`**
  - `:107`, `:164`, `:229`, `:286`, `:363` WARNING `exc_info`: the restore raised and became NOT_ESTABLISHED. The ERROR is `trying.py:1268` or `unwinding.py:136`.
  - `:135`, `:192`, `:257`, `:310` WARNING: partial restore.
  - `:328` WARNING: no `written_at`.
  - `:341` WARNING: outside change undecidable.
  - `:351` INFO: flag left as found.
- **`tools.py`**
  - `:783` and `:820` WARNING `exc_info`: flag history unreadable.

## agent_investigator

- **`investigation.py`**
  - `:332` WARNING `exc_info`: first metrics read failed.
  - `:403` DEBUG: alarm disproven. The orchestrator's line is the INFO.
  - `:421`, `:429`, `:433` DEBUG: how the onset was found.
  - `:514` WARNING: answer truncated.
  - `:534` WARNING: model refused.
  - `:551` DEBUG: candidates formed.
  - `:564` INFO: budget bound reached.
  - `:597` WARNING: placement unreadable.
  - `:633` WARNING: malformed answer, asked again.
- **`tools/dispatch.py`**
  - `:167` WARNING: channel unanswered.
  - `:240` WARNING: unknown tool called.

## agent_codefix

- `opening.py:190` WARNING `exc_info`: repository listing failed.
- **`proposing.py`**
  - `:270` INFO: no patch.
  - `:283` DEBUG: branch written and PR opened. The write server's line and `fixing.py:104` are the INFO.
  - `:324` INFO: declined.
  - `:328` WARNING: truncated.
  - `:353` WARNING: non-source patch, asked again.
  - `:367` WARNING: empty patch, asked again.
  - `:401` INFO: budget exhausted.
- `tools.py:176` WARNING `exc_info`: tool call failed.

## agent_postmortem

- `conversation.py:51` WARNING: faults in the answer, asked again.
- `writing.py:100` WARNING: written incomplete.
- `measuring.py:232`, `:235`, `:324` DEBUG: figures omitted. Each source logs its own WARNING.

## argus_incidents

- **`intake.py`**
  - `:51` INFO: joined an open incident.
  - `:64` INFO: incident opened.
- **`withdrawal.py`**
  - `:100` INFO: withdrawn.
  - `:117` DEBUG: already ended.

## argus_web

- **`app.py`**
  - `:158` DEBUG: resolutions only. WARNING for an empty `alerts` list (`grafana.py:94`).
  - `:161` WARNING: payload rejected. This is bad input, never ERROR.
  - `:194` WARNING: push signature rejected.
  - `:197` INFO: push recorded.
  - `:239` INFO: withdrawal refused.
- `pushes.py:115`, `:120` DEBUG: push ignored (grep mode, other branch).
- `pushes.py:123` WARNING: push for another repository.
- `grafana.py:138` WARNING: unknown `claim` annotation.

## incident_memory

- `store.py:98` DEBUG: no collection yet.

## code_index

- **`catching_up.py`**
  - `:157` INFO: index brought to a sha.
  - `:210` INFO: full build.
  - `:213` WARNING: comparison truncated, full pass.
- `building.py:96` DEBUG: counts.
- `chunking.py:96` WARNING: unparseable file, cut by lines.

## deployment_platform, repository_source, metrics_source

- `argocd.py:263` WARNING: pod skipped from placements.
- `argocd.py:359` WARNING: no pod start time.
- `comparing.py:97`: no line. `catching_up` is its only caller and logs the incomplete comparison itself.
- **`prometheus_adapter.py`**
  - `:140` DEBUG: minutes dropped (per read).
  - `:158` WARNING: rule series refused.
  - `:161` WARNING: rule matched several series.

## oncall_source, revenue_source

- `oncall_source/engagement.py:171`: no line. `orchestrator/sources.py` already logs "engagement could not be read" for the same event.
- `oncall_source/pagerduty_adapter.py:147` WARNING: job title unreadable.
- `revenue_source/takings.py:127` WARNING: provider unreadable.

## read_mcp_server

- `server.py:471` INFO: search by meaning not offered (startup).
- **`alert_rules.py`**
  - `:179` WARNING: rule unhealthy.
  - `:230` WARNING: definition unreadable.
  - `:235` and `:247`–`:289` DEBUG: series not followed, and why.
- `repository.py:140` WARNING: listing truncated.
- `meaning.py:215` WARNING: index behind the deployed ref.
- `retrieval.py:139` DEBUG: log window clamped.
- `deployments.py:106`, `:117` DEBUG.

## write_mcp_server

Every change to production is INFO. Every restore is INFO when complete and WARNING when partial.

- **`flag_state.py`**
  - `:160` INFO: flag set.
  - `:184`, `:189` WARNING: no `written_at`.
  - `:206` WARNING: accepted but not evaluating.
- **`restarting.py`**
  - `:123` INFO: restarted.
  - `:160` WARNING: not confirmed in time.
- **`rolling_back.py`**
  - `:116` INFO: refused, no earlier revision.
  - `:127` DEBUG: sync suspended.
  - `:146` WARNING: refused after suspend.
  - `:153` INFO: rolled back.
  - `:186` INFO or WARNING: restore.
  - `:197` ERROR `exc_info`: the restore raised.
- **`scaling.py`**
  - `:151` INFO: at its largest.
  - `:181` WARNING: refused after suspend.
  - `:188` INFO: scaled.
  - `:225` INFO or WARNING: restore.
  - `:241` ERROR `exc_info`.
- **`pinning.py`**
  - `:137` INFO: already held.
  - `:169` WARNING: refused after suspend.
  - `:176` INFO: floor raised.
  - `:214` INFO or WARNING: restore.
  - `:245` ERROR `exc_info`.
- **`accelerators.py`**
  - `:104` INFO: already pinned.
  - `:134` WARNING: refused after suspend.
  - `:140` INFO: pinned.
  - `:169` INFO or WARNING: restore.
  - `:180` ERROR `exc_info`.
- **`discarding.py`**
  - `:188` WARNING: no keys.
  - `:205` INFO: nothing to discard.
  - `:213` INFO: discarded.
- `branching.py:119` INFO: branch written.
- `pull_requests.py:126` INFO: PR opened.

## agent_communicator, argus_core transport

- `delivering.py:167` ERROR: the line will never be delivered.
- `relaying.py:147` WARNING: paused on a throttle.
- **`mcp_transport.py`**
  - `:566` WARNING: session could not be opened.
  - `:624` WARNING `exc_info`: retrying on a new session.
  - `:738` WARNING: tool call failed, server side.
