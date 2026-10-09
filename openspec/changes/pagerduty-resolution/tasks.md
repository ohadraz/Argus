Every behaviour task is TDD: propose the failing test in chat (the user applies
it), see it red for the right reason, then implement. Bottom-up: spikes, kernel,
incident record, the adapter, the web, engagement, the double, e2e.

## 0. Free spikes (confirm facts, decide nothing)

- [x] 0.1 A real Grafana container with a PagerDuty contact point: the PagerDuty
      alert's `alert_key` equals `sha256(groupKey)` from Grafana's webhook to
      Argus
- [x] 0.2 Merge two PagerDuty incidents in the UI: what the merged one's
      `incident.resolved` carries (`resolve_reason`, the target's id), and its
      `agent`

## 1. Kernel

- [x] 1.1 `Reference(source, kind, value)` in `argus_core.models`;
      `Alert.references: tuple[Reference, ...] = ()`, and an alert without them
      carries none
- [x] 1.2 `ReportChannel.PAGERDUTY`
- [x] 1.3 Settings: `pagerduty_webhook_secret` (default empty) - its test is
      4.2's empty-secret case

## 2. Incident record

- [x] 2.1 `incident_reference` table in revision `001`, `UNIQUE (source, kind,
      value)`
- [x] 2.2 `references.add`: idempotent, and a value already held by another
      incident stays there (real Postgres)
- [x] 2.3 `references.get_incident_by_values(kind, values)`: found by any value,
      `None` when none matches (real Postgres)
- [x] 2.4 `start_incident` records the alert's references, for a new incident
      and for an alert joining an open one

## 3. Intake

- [x] 3.1 The Grafana parser records `Reference("grafana", "notification_key",
      sha256(groupKey))`; without a `groupKey`, no reference

## 4. The port and the PagerDuty adapter (`oncall_source`)

- [x] 4.1 `OnCallPlatform` Protocol, the `Delivery` union and
      `DeliveryUnverified`, all in Argus's words
- [x] 4.2 `read_delivery`: signature verified over the raw body, rotation
      (comma-separated) accepted, constant-time; a mismatch or empty secret
      raises
- [x] 4.3 `read_delivery` maps `incident.resolved` per D5, in D5's order (merge
      before user, because a merge credits the person who merged; then user,
      integration, null or timeout), `incident.reopened`, and everything else
      as irrelevant. Each branch carries its reason as a comment
- [x] 4.4 `keys_of`: each alert's `alert_key`
- [x] 4.5 `resolution_note`: the note whose content starts "Resolution Note: ",
      with the prefix stripped; none means `None`. The docstring carries D4's
      reasoning and both sources
- [x] 4.6 `incident_for(keys)` via `?incident_key=`; `reported_incident` takes
      the platform's id
- [x] 4.7 The adapter declares `channel = ReportChannel.PAGERDUTY`; no
      credential means no adapter is built

## 5. Resolving from the platform

- [x] 5.1 The matching flow (D3): stored platform reference first, else keys,
      then match; records the platform id; reads the note; calls
      `resolve_incident` with `Report(by, PAGERDUTY, note)`. No match is
      logged. A merge, a reopen and a non-person resolution are logged and
      change nothing
- [x] 5.2 Narration: "from PagerDuty"

## 6. Web

- [x] 6.1 `POST /webhooks/oncall`: `404` unconfigured, `401` unverified, `503`
      on a platform read failure, `202` otherwise
- [x] 6.2 Layering contract: `argus_web` may import `oncall_source`

## 7. Engagement

- [x] 7.1 `_who_responded` finds the platform incident (stored reference, else
      `incident_for`, recorded once found); no incident → `NotPaged`
- [x] 7.2 The postmortem states `NotPaged` as "no on-call incident was linked",
      with no figure

## 8. `pagerduty_double`

- [x] 8.1 Module scaffold (new-module skill), TLS with a self-signed
      certificate, `EXCLUDED_FROM_TESTS`, noxfile stand-in and env,
      `.env.example`
- [x] 8.2 Reads: `/incidents/{id}`, `/incidents?incident_key=`,
      `/incidents/{id}/alerts`, `/incidents/{id}/notes`, `/users/{id}`;
      control: `/health`, `/double-control/reset`,
      `/double-control/incident`
- [x] 8.3 Point `PAGERDUTY_BASE_URL` at the double everywhere it pointed at the
      demo
- [x] 8.4 `Argus-Demo-Target-App`: remove the `/pagerduty` routes and
      `oncall.py` (a separate commit there)

## 9. Spec and docs

- [x] 9.1 `docs/spec-and-architecture.md`:
      - the on-call platform as an optional port;
      - `incident_reference`;
      - the webhook and why only a person's resolve counts;
      - engagement on the platform's incident;
      - the public URL the webhook needs

## 10. Verification

- [x] 10.1 e2e case (user writes it): feature-flag-toggle, resolved from
      PagerDuty after the flag is off (D9)
- [x] 10.2 `test_incident_response.py` stages its acknowledgements in the double
      (user edits)
- [x] 10.3 Cleanup: Check comments, docstrings, jargon, logs and docs are
      aligned, and that no test is missing, redundant or weak; verify no
      missing logs, or wrong log level
- [x] 10.4 Module suites, typecheck, lint, guard_layering green
- [x] 10.5 `e2e_replay(mode='both')` green, in the background
- [ ] 10.6 Specs synced on archive
