Tests are human-owned (`AGENTS.md`): every task below that needs a test means
*propose it in chat, confirm it is red, then implement*. Tasks marked
**(test)** are proposal tasks, not implementation ones. `tests/`,
`modules/argus_testkit/` and `modules/anthropic_double/` are hook-blocked -
propose the **entire file**, never a fragment.

## 1. The domain model and configuration

- [x] 1.1 **(test)** Propose tests for `ChangeEvent`: a deploy event carries its kind, the moment it took effect and the revision it referred to; an event with no actor is still valid
- [x] 1.2 Add `argus_core/models/change_event.py` - `ChangeEvent` and a `ChangeKind` enum whose only member today is the deploy, beside `metrics.py` and `cause.py`
- [x] 1.3 Add `CauseType.BAD_DEPLOYMENT` to the cause enum
- [x] 1.4 **(test)** Propose the `test_config.py` cases: a non-positive `change_lookback_minutes` is rejected, and the change lookback must exceed `log_max_window_minutes` (a change window no wider than the logs' cannot surface anything the logs did not)
- [x] 1.5 Add `argo_base_url`, `argo_application_path`, `argo_auth_token` and `change_lookback_minutes` (default 1440) to `Settings`, with the cross-field invariant in the existing `model_validator`
- [x] 1.6 Document `ARGO_AUTH_TOKEN` in `.env.example` beside `ANTHROPIC_API_KEY`

## 2. The Target Service's Argo stand-in

*(`Argus-Demo-Target-App` - a separate repo, fixture-quality, not hook-blocked)*

- [x] 2.1 Give `ScenarioMinute` (or the scenario registry) a way to carry a deploy: revision, and the offset minute it was deployed at
- [x] 2.2 Add the deploy to `bad-deployment` at its offset 0; leave `feature-flag-toggle` with none
- [x] 2.3 Add `GET /argo` (path configurable on the Argus side) returning Argo's application shape: `metadata.name` echoing the requested application, `status.history[]` with `id`, `revision`, `deployedAt`, `deployStartedAt` and `source`
- [x] 2.4 Anchor `deployedAt` to the scenario's seed instant, exactly as `_bucket_id` does, so the deploy lands before the latency departure it caused
- [x] 2.5 Verify by hand: seed `bad-deployment`, request the endpoint, confirm the deploy's minute precedes the first anomalous bucket

## 3. The change-source port and the Argo adapter

- [x] 3.1 **(test)** Propose the adapter's mapping tests: a revision history entry becomes a deploy event; an entry with no `deployStartedAt` still maps; entries outside the window are discarded; an empty history yields no events
- [x] 3.2 **(test)** Propose the adapter's transport tests: a configured token is sent as a bearer credential, no token means no authorization header, and an unreachable or erroring source raises rather than returning an empty list
- [x] 3.3 Define the change-source port in `read_mcp_server` - the seam a second vendor adapter would implement
- [x] 3.4 Implement the Argo adapter behind it: request the configured path (formatting `{application}` when the template carries it), read `status.history[]`, map to `ChangeEvent`, filter to the window on `deployedAt`
- [x] 3.5 Make the failure mode explicit - a named error type for "the change source could not be reached", never an empty result

## 4. The MCP tool and its typed client

- [x] 4.1 **(test)** Propose the tool tests: `get_change_events` returns the events inside its window, an empty window is not an error, and an unreachable source surfaces as a failure
- [x] 4.2 Implement `get_change_events(service, window_start, window_end)` on `argus-read-mcp`, delegating to the port
- [x] 4.3 Add the typed `get_change_events` function to `read_mcp_client`
- [x] 4.4 **(test)** Propose the client-level integration test, in the style of the existing `read_mcp_client` suite against a fake Target Service

## 5. The Investigator

- [x] 5.1 Add `change_events` to `Evidence`, beside `metric_buckets` and `log_lines`
- [x] 5.2 Extend the hypothesis prompt with a change-events section - and state that a change is a candidate to be judged, not proof of causation
- [x] 5.3 **(test)** Propose the loop tests: change events reach the model as evidence; they are fetched once across a widening investigation; an unreachable change source fails the investigation rather than degrading it to logs-only
- [x] 5.4 Add `fetch_change_events` as a third default-argument seam in `agent_investigator.retrieval`, and wire it into `investigate()` before the loop
- [x] 5.5 Check whether the loop's structural acceptance rule still earns its place now that a cause can be seen beyond the log window - keep it, and say why in the docstring, or remove it deliberately

## 6. Evidence that it works

- [x] 6.1 **(test)** Propose the eval case: fixed evidence carrying a deploy before a latency departure yields `CauseType.BAD_DEPLOYMENT`
- [x] 6.2 **(test)** Propose the eval case that guards over-attribution: evidence with a change that does not explain the symptoms yields no determined cause
- [x] 6.3 Record the double's fixtures for the new cases, so integration and contract suites stay keyless
- [x] 6.4 **(test)** Propose the e2e case: the `bad-deployment` scenario is diagnosed as a bad deployment and the incident resolves
- [x] 6.5 `uv run python -m nox -s lint`, `typecheck`, `test_all`, `guard_e2e_boundary` all green
- [x] 6.6 `uv run python -m nox -s e2e` green, both scenarios
- [x] 6.7 Update `docs/spec-and-architecture.md` §9 and §16 - retrieval is three channels now, and the diagram shows two

## 7. Follow-ups to raise, not to do here

- [x] 7.1 Raise the flag-toggle change source (LaunchDarkly's audit log) as the next change - `feature-flag-toggle` is still diagnosed from log prose
- [x] 7.2 Raise `REPLAY_LOG` (§4 principle 6) again - still uncaptured, and now there is a third retrieval channel it would record
