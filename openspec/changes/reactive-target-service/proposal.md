## Why

Argus can investigate but cannot yet *act*, and the Target Service is the reason.
Its scenarios are canned per-minute fixtures anchored so the scenario's **last**
minute lands at the seed instant - the incident is already over by the time
anything reads it. Nothing Argus does can change what the next read returns, so a
Mitigation agent reporting `confirmed` would be reporting a fact it never
checked. There is also nothing to revert: the flag toggle exists only as prose in
a canned log line.

Spec §15.2 already states the intended property - *"the log/metric generator
reacts to live state, not a script. It emits an anomaly matching the chosen root
cause while the underlying condition remains true, and stops once it becomes
false - regardless of who changed it or why."* That is what makes grading honest,
and it is what the write path is waiting on.

## What Changes

- **A real feature-flag provider joins the stack.** Self-hosted Unleash (§12.1,
  §14), sharing the existing Postgres server via its own database. Its admin UI
  is the console an audience watches the flag flip in.
- **The Target Service reads flag state instead of a fixture.** A checkout code
  path guarded by a live flag evaluation, containing a real defect - an average
  computed over items that shipped, which at checkout is none of them.
- **`/logs` and `/metrics` are computed at read time** from `(now, flag
  timeline)`, by running synthetic checkouts through that real code path. The
  newest metric bucket is the **in-progress minute**, aggregated over the seconds
  elapsed so far, so recovery is visible within seconds of a revert rather than
  after a whole clean minute. **BREAKING** for
  `target-service-scenario-control`: flag-scenario log content is no longer
  authored in advance, and its timestamps no longer stay stable across reads.
- **Seeding `feature-flag-toggle` enables the real flag** and backdates the
  onset, so a realistic incident exists to alert on immediately. The past is
  generated; everything after the seed instant is real.
- **A demo console** on the Target Service: scenario catalog with descriptions,
  an Apply button, and a live view of the service's own metrics and log lines -
  the operator's view, as a Grafana or Kibana user would see it.
- **`bad-deployment` and the Argo CD endpoint are untouched.** That scenario
  stays canned; it has no controllable condition until the git write path exists.

## Capabilities

### New Capabilities
- `feature-flag-provider`: a real flag provider in the stack - its database,
  seeded tokens, the flag and rollout strategy the Target Service bootstraps at
  startup, and flag evaluation over the provider's HTTP API.
- `flag-driven-telemetry`: the Target Service's checkout path, the defect behind
  the flag, and `/logs` and `/metrics` as read-time functions of live flag state
  including the partial in-progress minute.
- `target-service-demo-console`: the scenario catalog endpoint and the operator
  page that drives it.

### Modified Capabilities
- `target-service-scenario-control`: for `feature-flag-toggle`, log and metric
  content is generated at request time from live flag state rather than authored
  in advance; its timestamps advance with the clock rather than staying stable
  across reads; and seeding it mutates external state (the flag) rather than only
  in-memory state.

## Impact

- `Argus-Demo-Target-App` - `src/target_app/app.py` splits into business logic, a
  telemetry generator, the flag client, scenario control, and the console page;
  gains an `httpx` dependency and a startup bootstrap.
- `docker-compose.yml` - an Unleash service on `4242`, a Postgres init script
  creating its database, and `depends_on` ordering for the target service.
- `docs/spec-and-architecture.md` §12.1 and §14 - flag evaluation is the
  provider's Frontend API; Unleash exposes no OFREP endpoint, which the current
  wording assumes.
- `tests/e2e/` - the flag-toggle case now runs against a live flag, so the
  compose stack it needs grows a service. Test files are proposed in chat, per
  `AGENTS.md`.
- Stack bring-up lengthens by roughly 20-30s: Unleash runs migrations on first
  boot and everything downstream waits on its healthcheck.
