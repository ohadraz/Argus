## Why

Argus can locate *when* an incident started (metrics) and read *what the service
said* around that minute (logs), but it has no way to ask **what changed**. A
cause is a point-in-time event - a deploy, a flag flip, a config push - and the
lag between that event and the symptoms it produces is unbounded: a flag toggled
at 09:00 may only break under the 14:00 traffic peak. Today such an event reaches
the Investigator only if it happens to appear as a line inside the log window, so
no lookback is the right one - too short misses the cause, too long buries the
model in noise it pays for by the token.

This is the gap the ReAct loop already works around rather than solves. Its
acceptance rule (a confident answer from a window with no visible start costs one
widening) exists precisely because the loop cannot see past its log window. A
change-event channel removes the blind spot instead of guarding it, and it is
also the only practical way `bad-deployment` becomes detectable: a deploy is
trivially recognizable as a structured event and hard to infer from log prose.

## What Changes

- A **third retrieval channel**: change events, queried over a much wider span
  than logs, because changes are sparse - a day of deploys is a handful of rows
  where a day of logs is millions of lines.
- A new read-only MCP tool **`get_change_events(window_start, window_end)`** on
  `argus-read-mcp`, alongside `get_log_lines` and `get_metrics_summary`.
- A **port and an Argo CD adapter** behind that tool. The adapter speaks Argo's
  real API - `GET {base}/api/v1/applications/{application}`, bearer auth,
  `status.history[]` - and maps it onto Argus's own `ChangeEvent` model. Parsing
  is deterministic code, never an LLM: a hallucinated deploy is a fabricated
  cause, which is the failure this system exists to avoid.
- The **Investigator gains a third seam**, `fetch_change_events`, and includes
  the retrieved events in the `Evidence` it shows the model. It never learns that
  Argo exists.
- **`CauseType.BAD_DEPLOYMENT`** joins the enum, making the taxonomy's second
  member real and the `bad-deployment` fixture scenario diagnosable end to end.
- The **Target Service** grows a `/argo` endpoint answering in Argo's response
  shape, echoing the application name it was asked for - the same stand-in role
  it already plays for `/logs` and `/metrics`.
- New settings: `argo_base_url`, `argo_application_path`, `argo_auth_token`,
  `change_lookback_minutes`.
- An unreachable change source **fails loudly**. "The deploy API was down" must
  never reach the model as "nothing changed" - that is the confident-about-
  nothing bug in a new place.

## Capabilities

### New Capabilities
- `change-event-retrieval`: retrieving what changed on a service in a time
  window - the tool, its window semantics, the vendor-neutral `ChangeEvent`
  model, and the rule that an unreachable source is an error rather than an
  empty answer.
- `argo-deploy-adapter`: the Argo CD-shaped adapter behind the port - the real
  request it makes, the authentication it carries, the response fields it reads,
  and the client-side window filtering Argo's API forces.

### Modified Capabilities
- `investigator-react-loop`: the loop retrieves change events as a third input
  and shows them to the model as evidence.
- `investigator-cause-detection`: `bad-deployment` becomes a determinable cause,
  identified from a change event rather than from log prose.
- `target-service-scenario-control`: the fixture serves deploy history, and the
  two scenarios differ in whether they carry one.
- `read-mcp-server`: a third read-only tool joins the server's surface.

## Impact

- **`argus_core`**: new `models/change_event.py`; `Evidence` gains a
  `change_events` field; `CauseType` gains `BAD_DEPLOYMENT`; `Settings` gains
  four fields; the hypothesis prompt gains a change-events section.
- **`read_mcp_server`**: new `get_change_events` tool, a change-source port, and
  the Argo adapter behind it.
- **`read_mcp_client`**: the typed client function for the new tool.
- **`agent_investigator`**: a third `fetch_*` seam and the evidence it feeds.
- **`Argus-Demo-Target-App`**: a `/argo` endpoint and deploy data on the
  `bad-deployment` scenario.
- **Tests**: unit tests for the adapter's mapping and window filtering, MCP-level
  tests for the tool, loop tests for the new seam, and an e2e case that
  diagnoses `bad-deployment`.
- **No production dependency on Argo itself** - the adapter is plain HTTP, and
  the demo Target Service stands in for a real Argo server.
