## Context

The Target Service (spec §15) serves three retrieval channels from a registry of
canned scenarios. Each scenario is a tuple of `ScenarioMinute` fixtures, and
`_bucket_id` anchors the scenario's **last** minute at the seed instant - so the
whole incident sits in the past the moment it is seeded. That anchoring was
correct for what it was built for: a reader windows its retrieval to end at
"now", and anchoring the *first* minute at the seed instant would put the rest of
the incident in the future where a correct reader cannot see it.

It is also why nothing Argus does can affect what the next read returns. The
write path (`argus-write-mcp`, the Mitigation agent, the tier gate) is blocked on
that: spec §7.3 has Mitigation re-query the same metrics and return
`confirmed`/`refuted`, and against a frozen fixture both answers are fiction.

Spec §15.2 already prescribes the shape of the fix - a generator that reacts to
live state and stops when the seeded condition becomes false, *"regardless of who
changed it or why"*. This change builds that for one scenario.

Constraints:

- `Argus-Demo-Target-App` is a fixture, held to a lower bar than Argus itself
  (`CLAUDE.md`). Shortcuts are fine here and expected.
- The existing Argo CD channel, the `bad-deployment` scenario, and the wire
  shapes of `/logs`, `/metrics` and `/argocd` must not move. Three Argus-side
  adapters and two e2e cases read them.
- `tests/` is hook-blocked; every test is proposed whole in chat first.

## Goals / Non-Goals

**Goals:**

- Turning the flag off changes what the *next* read returns, without a restart,
  a re-seed, or Argus telling the Target Service anything.
- The condition is held in a real, external flag provider with its own UI, so the
  revert is a real API call against a real system and an audience can watch it.
- Recovery is observable within seconds of the revert, not after a whole minute.
- A real defect behind the flag, so Code-Fix later inherits a bug whose
  regression test can genuinely fail first (spec §15.1).
- One screen for the operator's view of the service: pick a scenario, apply it,
  watch the numbers move.

**Non-Goals:**

- `bad-deployment` stays canned. It has no controllable condition until the git
  write path exists, and inventing one now would be a second mechanism with no
  consumer.
- No Mitigation agent, no `argus-write-mcp`, no tier gate - that is the next
  change. Nothing here writes to the flag except the Target Service's own
  scenario control.
- No flag-toggle **change event**. The flag toggle stays diagnosed from log
  prose; reading the provider's audit log into `ChangeKind.FLAG_TOGGLE` is its
  own change.
- No background traffic generator, ticker, or self-directed request loop.
- No incident feed in `argus_web`. Separate change.

## Decisions

### Telemetry is a pure function of `(now, flag timeline)`, evaluated on read

The Target Service keeps one piece of per-run state: a **flag timeline** -
`flag_on_from` and `flag_off_at | None`. `/logs` and `/metrics` compute their
answer from it on every request. Nothing runs between requests.

For each minute in the requested span the generator draws a fixed **sample** of
synthetic checkouts (N=50) and runs them through the real checkout code path with
the flag value that minute had. `request_volume` is reported at a realistic
figure independent of the sample size; `error_rate` is measured from the sample.
Running the reported volume for real would mean ~430k calls per `/metrics`
request over the 360-minute metrics window, which is why the sample exists.

*Alternative rejected - a ticker with a rolling buffer of real outcomes.* It
makes the app stateful in wall-clock time, needs seeding-in-the-past to backfill
anything, and produces different numbers on every read for no gain. The
user-facing property that matters is "reacts to live state", and read-time
evaluation has it exactly.

*Alternative rejected - the app issuing HTTP requests to itself.* Same reaction
property, plus a thread, a port dependency, and log noise from the traffic
generator itself.

### Per-minute determinism, seeded by the minute

The sample's RNG is seeded from the minute's own identity, so re-reading a past
minute returns the same numbers it returned before. Past minutes are stable
across reads; only the in-progress minute moves, because it has more elapsed
seconds each time.

This preserves the useful half of the existing "stable timestamps" requirement -
a debugger comparing two reads is comparing like with like - while dropping the
half that made recovery impossible.

### The newest bucket is the in-progress minute, aggregated over elapsed seconds

Real monitoring reports partial buckets, and it is what makes recovery visible
quickly. If the flag goes off at `:10`, the in-progress minute holds 10 seconds
of failures against a growing tail of successes, so its error rate falls
continuously from the moment of the revert rather than stepping down at the next
minute boundary:

```
flip off at :10
:20   newest bucket ~0.25
:35   newest bucket ~0.11
:50   newest bucket ~0.06
```

*Alternative rejected - whole minutes only.* Strictest reading, but it adds
60-120s to the demo and to both e2e suites, for a number that is not more true.

### `flag_off_at` is learned lazily on read

Every `/logs` or `/metrics` request evaluates the flag through the provider. If
it now reads off while the timeline still says on, the request stamps
`flag_off_at = now` before generating. Argus reads metrics immediately after
reverting, so the stamp lands within a second or two of the real flip - and any
other reader (a human clicking in the provider's own UI) triggers the same
stamping, which is what §15.2's *"regardless of who changed it or why"* asks for.

*Alternative rejected - polling the provider on a timer.* A ticker, for
sub-second precision nothing needs.

### Applying the scenario backdates the onset

Apply enables the real flag **now** but records `flag_on_from = now -
onset_backdate` (default 5 minutes). A realistic incident therefore exists to
alert on immediately, instead of an audience watching a flat graph for five
minutes.

The past is generated; everything after the seed instant is real. That is the
honest half of the trade and it is the half mitigation depends on - the generated
past cannot recover, and the real present can.

Five minutes rather than three: the investigation's initial log window reaches
ten minutes ahead of the onset it locates, and `find_onset` needs enough
anomalous minutes to be reading a departure rather than a single outlier.

### Unleash as the flag provider

Named by spec §12.1 and §14, and the larger open-source project. Admin UI ships
in the same container, which is the point - the audience watches the flag flip in
a real provider's console, not in a page we wrote.

- Port `4242`. No collision with anything in either stack.
- **It lives in the Target Environment's compose file, not Argus's.** The flag
  provider is part of the environment Argus operates *on* (spec §2, §15), not
  part of Argus. `Argus-Demo-Target-App` gains a `docker-compose.yml` bringing
  up the service, the provider, and the provider's database, standalone - a
  fixture that cannot run without Argus's database is not a fixture. Argus
  reaches all of it over HTTP, exactly as it would reach a real environment.
- Postgres is mandatory for Unleash, and it gets its own small container inside
  that stack rather than borrowing Argus's. One extra container is the price of
  the target environment being self-contained, and it is worth paying.
- **Read** goes through the Frontend API (`/api/frontend`, frontend token), plain
  HTTP per request, no SDK and no background poller. Unleash exposes **no OFREP
  endpoint**, so spec §12.1's "OFREP flag evaluation" and §14's "OFREP evaluation
  token" get rewritten to name the Frontend API - the spec presently pairs
  Unleash with a protocol Unleash does not speak.
- **Write** is the admin API. Only scenario control uses it in this change;
  `argus-write-mcp` takes it over next.
- The Target Service bootstraps the flag at startup if absent - **and a
  100%-rollout strategy with it**, because a flag with no strategy evaluates
  false even when its environment is enabled, which would leave mitigation with
  nothing that toggling could actually change.

#### Verified against `unleashorg/unleash-server:8.1.0`

Spiked against a real container on a shared Postgres before anything was built on
it. Everything below was observed, not read:

| Thing | Verified value |
|---|---|
| Image | `unleashorg/unleash-server:8.1.0` (pinned) |
| Database | `DATABASE_URL: postgres://unleash:unleash@unleash-db:5432/unleash`, `DATABASE_SSL: "false"`; its own `postgres:16` container in the Target Environment's stack, not published to the host |
| Health | `GET /health` → `{"health":"GOOD"}`; healthy ~3s after Postgres is healthy, not the 20-30s assumed |
| Admin token | `INIT_ADMIN_API_TOKENS: "*:*.<secret>"` - **exists and works**, though it appears in neither the compose sample nor the configuration page |
| Frontend token | `INIT_FRONTEND_API_TOKENS: "default:development.<secret>"` (`INIT_BACKEND_API_TOKENS` same form; `INIT_CLIENT_API_TOKENS` is the deprecated one) |
| Auth | the whole token string, `Authorization: <token>`, no `Bearer` |
| Defaults | project `default`; environments `development` and `production`, both present |
| Create flag | `POST /api/admin/projects/default/features` `{"name","type":"release","description"}` → 201 |
| Add strategy | `POST /api/admin/projects/default/features/{flag}/environments/{env}/strategies` `{"name":"flexibleRollout","parameters":{"rollout":"100","stickiness":"default","groupId":"{flag}"}}` |
| Toggle | `POST /api/admin/projects/default/features/{flag}/environments/{env}/on\|off` → 200 |
| Read back | `GET /api/admin/projects/default/features/{flag}` → `environments[].enabled` and `environments[].strategies` |
| Evaluate | `GET /api/frontend` with the frontend token |
| Audit log | `GET /api/admin/events/{flag}` → `feature-environment-enabled` / `-disabled` / `feature-strategy-add` / `feature-created`, each with `createdAt`, `createdBy`, `featureName`, `environment`, `project` |

Three findings that change the implementation:

- **The missing-strategy trap is real.** Flag created and environment enabled,
  but with no strategy `GET /api/frontend` returned `{"toggles":[]}` - the flag
  reads as off. The bootstrap must add the strategy or mitigation has nothing to
  revert.
- **An off flag is *absent* from the evaluation response, not `enabled:false`.**
  The flag client reads "off" as "not in `toggles`", never as a field it can
  compare.
- **Adding a strategy is not idempotent - it appends.** Two identical
  `flexibleRollout` strategies after two calls. The bootstrap checks for an
  existing strategy before adding one, or every restart piles up another.

And one that is smaller than feared but not nothing: **propagation is
sub-second, but it is not instant.** Measured over three on/off round trips, an
admin toggle reached `GET /api/frontend` in 0.18-0.97s. There is no evaluation
cache worth designing around and no meaningful lower bound under mitigation's
verification - but a caller that toggles and immediately evaluates does get the
old answer, which is both wrong and intermittently wrong.

So `enable()` and `disable()` return only once evaluation agrees, polling to a
bounded allowance. The wait belongs in the client rather than in each caller:
there is one correct response to the lag, no caller can do anything useful
during it, and a caller that forgets produces a flake rather than an error.

*Alternative rejected - Flipt.* Speaks OFREP and needs no Postgres, but is the
less common tool, is not the one the spec names, wants port 8080 (held by the
Target Service), and in v2 stores flag state as git commits - so the audit
history the flag-change channel will want would mean parsing commits rather than
reading an event log with `createdBy` on it.

*Alternative rejected - a flag endpoint inside the Target Service.* Zero
infrastructure, but then the "external system" Argus writes to is the fixture
itself, and the write path proves nothing.

### The defect is real code

```python
def average_item_price(cart: Cart) -> int:
    # v2: spread the order total across the items that actually shipped
    shipped_items = [item for item in cart.items if item.shipped]
    return cart.total_cents // len(shipped_items)
```

Nothing has shipped at checkout, so the divisor is always zero. The fix is one
identifier. The names carry the reasoning without spelling it out, and the
failure is a genuine `ZeroDivisionError` caught at the request boundary - so the
error log lines are real exception text rather than authored prose.

The 40% canary split lives in the generator, not in an Unleash gradual-rollout
strategy: the error rate stays deterministic and the flag stays a plain boolean.
Every canary request fails, so a flag-on minute reads at ~0.40 error rate with
sampling noise, and latency stays flat - which is the signature that distinguishes
this scenario from `bad-deployment` and must not blur.

### Log volume is bounded per minute

A sampled minute produces up to 20 failures; returning all of them across a
360-minute window would swamp every window the read MCP asks for. The generator
emits a bounded set per minute - a couple of representative failure lines plus
one aggregate line naming the minute's error rate - which is what a sampled log
pipeline looks like and matches the density of the fixture it replaces.

### Scenario control keeps its `/scenario/*` prefix

Spec §15.1 asks for control routes under a prefix structurally separate from
business logic, and gives `/demo-control/*` as an example. `/scenario/*` already
satisfies that, and renaming it would churn an e2e test file for no behavioural
gain. New control endpoints (the scenario catalog) join the existing prefix.

### The console is a server-rendered page on the Target Service

One page, no build step, no framework: the scenario catalog with descriptions, an
Apply button, and a table of the service's own `/metrics` and `/logs`, refreshed
by polling. It is the **operator's** view - what a Grafana or Kibana user would
see. Argus's own narration is a separate screen in `argus_web`, in a later
change, because that is Argus's story and this page is the service's.

The page posts the Grafana-shaped alert webhook to Argus **from the browser**, so
the Target Service's server never learns Argus exists.

## Risks / Trade-offs

- **A generated past sits beside a real present.** → Stated plainly in the
  module's docstring and here. It is the same trade the current fixture makes,
  narrowed: only minutes before the seed instant are synthesised, and the
  property under test - that recovery follows the flag - lives entirely in the
  real half.
- **Two mechanisms in one app**: `feature-flag-toggle` live, `bad-deployment`
  canned. → Each scenario's seeding is already its own function; the generator
  is selected per scenario. Revisit when the git write path makes a live deploy
  scenario possible.
- **Unleash lengthens stack bring-up**, and everything downstream waits on its
  healthcheck. → Measured at ~3s past Postgres on `8.1.0`, far less than feared,
  but still a healthcheck plus `depends_on: service_healthy`, and a bootstrap
  that retries rather than crashing on a provider that is not up yet.
- **Unleash's init-token environment variables have been renamed across
  versions**, and a wrong one makes the container refuse to start. → Pinned to
  `8.1.0` and verified against that tag; see the table above. Re-verify on any
  bump.
- **The flag is global state shared by every reader.** Two e2e tests running
  concurrently would fight over it. → The suite is serial today; if that changes,
  the flag name becomes per-run rather than the tests becoming careful.
- **An abandoned run leaves the flag on**, and the next reader sees an incident
  nobody started. → `POST /scenario/reset` turns it off, the e2e suite already
  calls it in a `finally`, and the console shows current flag state so a stale
  one is visible rather than mysterious.
