## Context

Retrieval today has two channels, both landed by `investigator-react-loop`:
metrics (symptoms - one fixed wide span, read once, locating the onset) and logs
(narrow, anchored on that onset, widening on a derived schedule). Both reach the
Investigator through `argus-read-mcp` tools, and both stop at an adapter that
maps a vendor shape onto an Argus model.

Neither answers "what changed". A cause is an *event*; a symptom is a *rate*; the
lag between them is unbounded. The loop currently compensates with an acceptance
rule - a confident answer drawn from a window with no visible start costs one
widening before it is believed - which is a guard, not a fix. Widening logs buys
noise linearly; change events stay a handful of rows however wide the window
gets, which is exactly why they deserve a channel of their own.

The fixture makes the gap concrete. `bad-deployment` moves p95 latency and says
"deploy completed, version 1.4.3" in a log line; `CauseType` has one member and
no deploy is diagnosable. The cause is recognizable as a structured event and
awkward to infer from prose.

## Goals / Non-Goals

**Goals:**
- A third retrieval channel, reachable as one MCP tool, returning vendor-neutral
  `ChangeEvent` rows for a time window.
- One real vendor shape implemented faithfully - Argo CD - so the adapter is
  pointable at a real Argo server, not only at the fixture.
- `bad-deployment` diagnosable end to end, from a structured deploy record
  rather than a log line.
- An unreachable change source that is loud, never silently "nothing changed".

**Non-Goals:**
- A second vendor adapter (GitHub Actions, Spinnaker). One source per change
  type is the rule; the port exists so the second is cheap, not so it ships now.
- Flag toggles as change events. LaunchDarkly's audit log is the intended
  source, and it is its own change - this one is deploys only.
- Removing the loop's acceptance rule. The guard stays useful for causes with no
  change record at all.
- Argo's write side. Nothing here syncs, rolls back, or triggers a deploy;
  spec §13 forbids autonomous infra action regardless.

## Decisions

### 1. The channel is an MCP tool, not a call from the Investigator

`get_change_events(window_start, window_end)` joins `get_log_lines` and
`get_metrics_summary` on `argus-read-mcp`. The Investigator gains a third
`fetch_*` seam and never learns Argo exists.

*Alternative considered:* letting the Investigator call Argo directly, which is
one less hop. Rejected - retrieval is the read server's job by §12.1, and the
autonomy tier is a property of the *server*, not of who happens to call it. A
read-only vendor integration living inside an agent is exactly the boundary
erosion the two-server split exists to prevent.

### 2. Parsing is deterministic code in the adapter, never the model

Each vendor's shape is known at build time - `status.history[].deployedAt` for
Argo, something else for the next one - so mapping it onto `ChangeEvent` is
ordinary code, unit-testable and free.

*Alternative considered:* handing the raw vendor JSON to the LLM and letting it
extract the events, which would absorb any vendor without an adapter. Rejected
on three counts: it costs a model call per retrieval, it is unreproducible
across benchmark runs, and it can hallucinate a deploy that never happened -
inventing the very evidence the verdict then rests on. The model's job is
judging whether a change explains the incident, not reading JSON.

### 3. `ChangeEvent` is vendor-neutral and carries a kind

```python
class ChangeEvent(BaseModel):
    kind: ChangeKind          # DEPLOY today; FLAG_TOGGLE, CONFIG_PUSH later
    occurred_at: str          # ISO-8601, the moment the change took effect
    reference: str            # the git SHA for a deploy; a flag key later
    summary: str              # one line, model-readable
    actor: str | None         # who triggered it, when the source says
    source: str | None        # repo/path, or the flag project
```

`occurred_at` is a wire-format string like `MetricBucket.bucket_id`, for the
same reason: it is compared against onset and quoted into a prompt, and both
want the string the rest of the system already speaks.

`kind` exists from the start even with one member, because the whole point of
the channel is that a deploy and a flag flip are *different kinds of the same
thing*, and a model told only "something changed" cannot weigh them.

### 4. The adapter filters the window client-side, because Argo cannot

`GET /api/v1/applications/{name}` returns the whole `status.history` array with
no time parameters. So the adapter asks for everything and filters on
`deployedAt` itself. This is a real property of the vendor, not a shortcut, and
it belongs in the adapter where the next vendor's server-side filtering can
replace it without anything above noticing.

`deployedAt` is the anchor because Argo guarantees it (no `omitempty`);
`deployStartedAt` is a pointer and may be absent, so it is read when present and
never depended on.

### 5. Changes are fetched once, over a wide lookback ending at the onset

`change_lookback_minutes` (default 1440 - a day), fetched once before the loop,
exactly like the metrics summary. Changes are sparse, so width is nearly free,
and re-reading per iteration would return the same rows.

The window is `[onset - change_lookback, onset]` - anchored on the **onset**,
not on the alert. Onset is when the incident actually began; the alert is
whenever somebody's threshold happened to trip, which may be many minutes
later. Ending at the onset is the stronger half of that: a change made *after*
the incident started did not start it, and offering it to the model as a
candidate invites exactly the post-hoc attribution the prompt warns against.
The onset is already known before the loop, so nothing has to be re-ordered to
get it.

*Alternative considered, and initially written:* anchoring on the alert time.
Rejected once the onset was available at the same point in the flow - it is
strictly more precise, and it makes the "ends before the symptoms" property
expressible at all, which an alert-anchored window cannot be.

*Alternative considered:* widening the change window on the same schedule as
logs. Rejected - the schedule exists because log volume grows with the window,
which is not true here. A day of deploys is a handful of rows; paying for a
narrow first look buys nothing and risks missing the cause on iteration one.

### 6. The application name is the service name

Argo has no notion of "service" - the Application *is* the deployable unit - so
`Alert.service` is used as the application name directly. The demo Target
Service ignores which name it is given and answers from the seeded scenario,
echoing the requested name back in `metadata.name` the way a real Argo would.

*Known limit:* a real deployment whose Argo application names differ from its
alerting service names needs a mapping. That is configuration, not architecture,
and is left until something needs it.

### 7. An unreachable source is an error, not an empty list

A failed change-source call raises rather than returning `[]`. Silence and
"nothing changed" are opposite facts, and collapsing them would let a network
outage read as evidence of absence - the confident-about-nothing failure, one
layer down.

*Consequence, deliberately accepted:* an Argo outage fails the investigation
rather than degrading it to logs-only. That is the honest behaviour while the
channel is the primary way a deploy is seen; if it proves too brittle in
practice, the fix is an explicit "channel unavailable" fact carried into the
evidence, not a silent empty list.

### 8. Auth is a bearer token from configuration

`argo_auth_token`, empty in the demo (which requires none), sent as
`Authorization: Bearer ...` when set. Real Argo issues these from
`POST /api/v1/session` or `argocd account generate-token`; obtaining one is an
operator task, not Argus's.

## Risks / Trade-offs

- **[The model may now over-attribute to whatever change it is shown.]** A deploy
  in the window is not proof it caused anything. → The prompt must ask the same
  question it asks of logs - does this evidence *explain* the symptoms - and
  "undetermined" stays a first-class answer. The eval suite gains a case where a
  deploy precedes an unrelated incident.
- **[`bad-deployment` becomes diagnosable via two routes]** - the deploy event
  and the p95 departure. A model could reach the right answer for the wrong
  reason. → The eval asserts on `cause_type`, and the fixture keeps the deploy
  as the only *change* in the window, so the reasoning has one honest path.
- **[Argo returns unbounded history.]** A long-lived application could return
  thousands of revisions on every call. → Filtering is client-side by
  construction; if volume becomes real, the adapter caps what it reads and says
  so, rather than the tool silently truncating.
- **[Four new settings, one of them a secret.]** → `argo_auth_token` follows
  `anthropic_api_key`: documented in `.env.example`, empty by default, never
  invented. The demo path works with it unset.
- **[The channel widens the prompt.]** More evidence per call is more tokens. →
  Change events are rows, not lines; a day of them is a fraction of a single
  log window.

## Open Questions

- Does `bad-deployment` need its own recorded double fixture for the integration
  suite, or does the existing recording mechanism cover it once the scenario
  carries a deploy? Expected to be the latter, confirmed when recording.
- Should the `ChangeEvent` list reaching the prompt be capped, and if so by
  count or by window? Deferred until a fixture produces enough rows to matter.
