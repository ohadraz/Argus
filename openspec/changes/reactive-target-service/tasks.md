**`Argus-Demo-Target-App` gets tests, but not TDD.** They are a regression net -
written after the code, to catch something breaking while the rest of the change
moves - rather than a design tool. Argus's own modules keep full TDD. Demo-app
tests are covered in group 8, at the end, not interleaved.

## 1. Unleash in the stack

- [x] 1.1 Pin an Unleash image tag and verify against that tag: the init-token
      environment variable names, the admin toggle path
      (`/api/admin/projects/{project}/features/{flag}/environments/{env}/on|off`),
      the Frontend API evaluation path, and the flag-creation and
      add-strategy admin paths. Record the verified values in `design.md`.
      *Done: spiked `8.1.0` against a real container; see design.md's verified
      table. Three findings - the missing-strategy trap confirmed, an off flag is
      absent rather than `enabled:false`, and adding a strategy appends rather
      than upserts. Propagation is sub-second but not instant.*
- [x] 1.2 Give `Argus-Demo-Target-App` its own `docker-compose.yml` - the
      service, Unleash, and Unleash's own Postgres - so the Target Environment
      runs standalone. The flag provider belongs to the environment Argus
      operates on, not to Argus.
- [x] 1.3 Add the `unleash` service on `4242` with seeded admin and frontend
      tokens and a healthcheck.
- [x] 1.4 Make `target-service` wait on `unleash` being healthy, and confirm
      `docker compose up` reaches a healthy stack from empty volumes with no
      manual console visit. *Confirmed: both databases up, both seeded tokens
      answer, healthy in seconds.*
- [x] 1.5 Wire the Target Environment's stack into `nox -s e2e`, so one command
      still brings up everything. *Compose `include:`, not a second `-f`: with
      `-f`, relative paths resolve against the project directory and the build
      context lands in the wrong repo. Argus's compose re-declares the three
      included services with nothing but `profiles: ["e2e"]`, so a plain
      `docker compose up` still brings up Postgres alone.*

## 2. Target Service: flag client and bootstrap

- [x] 2.1 Add `httpx` to `Argus-Demo-Target-App` and a settings object for the
      provider's base URL, project, environment, flag name, and the two tokens.
- [x] 2.2 Write the flag client: evaluate over the Frontend API; enable/disable
      over the admin API; raise on an unreachable provider rather than
      defaulting to false.
- [x] 2.3 Write the startup bootstrap: create the flag if absent **and** attach a
      100%-rollout strategy; leave an existing flag alone; retry while the
      provider is still coming up.
- [x] 2.4 Verify by hand that an enabled flag actually evaluates true through the
      Frontend API - this is the step the missing-strategy trap breaks.
      *Verified against the running provider: bootstrap idempotent across three
      calls, enable/disable round-trips, unreachable provider raises. Flushed
      out that a toggle is not instantly visible - `enable`/`disable` now return
      only once evaluation agrees.*

## 3. Target Service: the checkout path and its defect

- [x] 3.2 Write `Cart` and `average_item_price_v2` with the branch that divides
      by the count of shipped items.
- [x] 3.3 Write the checkout entry point that routes a fixed minority of requests
      to the v2 branch when the flag is on, and catches the raised error at the
      boundary into a log line carrying the real exception text.

## 4. Target Service: the read-time generator

- [x] 4.2 Write the generator as a pure function of `(now, flag timeline)`,
      seeded per minute so completed minutes are stable, sampling N synthetic
      checkouts per minute through the real checkout path and reporting
      `request_volume` independently of the sample size. *Sample size raised
      from 50 to 200 after measuring: at 50 the error rate only resolves to 2%,
      which makes a calm baseline read as a jagged 0-4%. A 90-minute window
      still generates in ~70ms.*
- [x] 4.3 Add the in-progress minute as the newest bucket, aggregated over the
      seconds elapsed so far.
- [x] 4.4 Bound the log lines emitted per minute to a couple of representative
      failures plus one aggregate line.

## 5. Target Service: scenario control over live state

- [x] 5.1 Split `app.py`: business logic, generator, flag client, scenario
      control, console. Keep every existing route's path and response shape.
- [x] 5.2 Make `feature-flag-toggle` a generated scenario - seeding enables the
      flag and records `flag_on_from = now - onset_backdate` (default 5 minutes);
      reset disables it.
- [x] 5.3 Stamp `flag_off_at` lazily on each `/logs` and `/metrics` read when the
      provider reports the flag off while the timeline still says on.
- [x] 5.4 Route `/logs` and `/metrics` per scenario: generated for
      `feature-flag-toggle`, the existing canned path for `bad-deployment`.
      Leave `/argocd` untouched. *Regression-checked by hand: `bad-deployment`
      serves its four authored minutes and its Argo CD history unchanged, and a
      generated scenario reports an empty history.*
- [x] 5.5 Add the scenario catalog endpoint under `/scenario/`, carrying each
      scenario's id, description, and which is active.

## 6. The operator console

- [x] 6.1 Serve a single page: scenario catalog with descriptions, an Apply
      control, current flag state, and tables of `/metrics` and `/logs`, polled
      rather than manually reloaded.
- [x] 6.2 Add the browser-side "trigger the alert" action posting the
      Grafana-shaped payload to Argus, with Argus's URL entered in the page - no
      reference to Argus anywhere in the Target Service's Python.
- [x] 6.3 Confirm by hand in a browser: apply the scenario, watch the error rate
      rise, turn the flag off in Unleash's own console at `:4242`, watch it fall.
      *Confirmed in a browser. The same loop over HTTP: seeding served 39%
      errors, an externally toggled flag took the next bucket to 0.00 and stamped
      the recovery minute, with nothing telling the service.*

## 7. Argus-side follow-through

- [x] 7.1 Rewrite `docs/spec-and-architecture.md` §12.1 and §14 so flag
      evaluation names the provider's Frontend API rather than OFREP - as
      specification, not as a changelog note. *Also §12, §15.1, §19's diagram
      and §24's decision table, all of which asserted OFREP.*
- [x] 7.2 Propose in chat any edit the existing e2e flag case needs now that
      seeding mutates a real flag, and confirm `bad-deployment` is untouched.
      *No edit needed - all three e2e cases pass unchanged against the live
      flag, which is the outcome worth having: the suite asserts on what Argus
      concluded, not on how the fixture produced it.*
- [x] 7.3 Run `uv run python -m nox -s lint typecheck test_all guard_e2e_boundary`.
      *All green: lint, typecheck (88 files), test_all (34 passed),
      guard_e2e_boundary. `typecheck` was broken on this machine by Smart App
      Control blocking mypy's compiled modules - a pre-existing fault, unrelated
      to this change, fixed by `no-binary-package = ["mypy"]` in the root
      `pyproject.toml` and written up in `CLAUDE.md`.*
- [x] 7.4 Run `uv run python -m nox -s e2e_replay` green. *3 passed against the
      merged stack.*
- [ ] 7.5 Run `uv run python -m nox -s e2e` (paid, ~$0.12 - ask first).

## 8. The demo app's regression net

Written after the code, once the shape has settled - a guard against breaking
something later, not a driver of the design.

- [x] 8.1 Flag client: an absent toggle reads as off, a transport error raises
      rather than reading as off, bootstrap skips an existing flag and an
      existing strategy, enable/disable wait for evaluation to agree.
- [x] 8.2 Checkout: the stable path prices a cart, v2 raises on a cart with
      nothing shipped, and the failure reaches the caller.
- [x] 8.3 Generator: a flag-on minute is degraded and a flag-off minute healthy;
      latency stays flat while the error rate moves; a completed minute is
      identical on re-read; the in-progress minute scales with elapsed seconds;
      log lines are bounded per minute; logs and metrics agree.
- [x] 8.4 Scenario control: seeding backdates the onset, reset clears the
      condition, and an externally reverted flag ends the incident.
- [x] 8.5 `uv run pytest` green in `Argus-Demo-Target-App`. *39 passed.*

## 9. Commit

- [ ] 9.1 Commit `Argus-Demo-Target-App` and `Argus` separately, one approved
      single-line message each.
