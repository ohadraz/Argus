## Why

A person who ends an incident usually does it in the on-call tool that paged
them, not in Argus. Change (b) taught Argus to accept a resolution from its own
UI. This change, the third of three, accepts the same report from the on-call
platform, starting with PagerDuty. It also fixes a standing lie: engagement
asks PagerDuty about Argus's own incident id, which only the demo's stand-in
answers.

The on-call platform is optional. A customer may run Grafana alone, or
PagerDuty without Grafana. Argus must work unchanged without one, and adding a
second platform later must mean writing one adapter, not reshaping Argus.

## What Changes

- **A seam for the on-call platform.** A port named for the role
  (`OnCallPlatform`, a `Protocol`) with PagerDuty as its first adapter, named
  for the vendor. Above the port nothing knows PagerDuty's routes, headers,
  object shapes or event names.
- **Argus records what each tool calls the incident.** A new
  `incident_reference` table holds `(incident, source, kind, value)` rows. Intake
  records the key Grafana stamps on every notification it sends a paging tool
  (`sha256(groupKey)`). A new tool adds rows, never columns.
- **A signed webhook from the on-call platform.** `POST /webhooks/oncall`
  verifies the delivery's signature and lets the adapter read it. When a
  **person** resolved the platform's incident, Argus finds its own incident
  through the platform incident's alert keys and resolves it as change (b) does,
  crediting that person by name, through that channel, with their resolution
  note.
- **Only a person's resolution counts.** These "resolved" events are recorded
  and ignored, each with its reason written into the spec, the design and the
  code:
  - monitoring cleared the alert, because Argus reads recovery itself;
  - a timeout or automation, because nobody decided anything;
  - a reopen after Argus marked the incident resolved.

  A merge moves the incident rather than ending it, even though PagerDuty
  credits it to the person who merged. The merged alerts move onto the target,
  so a person resolving the target still counts.
- **Engagement reads the platform's own incident.** The postmortem's engagement
  read finds the platform incident through `incident_reference` instead of
  passing Argus's UUID. When no platform incident is linked, it says so rather
  than inventing an answer.
- **A `pagerduty_double` module.** It stands in for PagerDuty's REST reads
  (incidents, alerts, notes, users) over TLS, because the SDK refuses a plain
  `http://` base URL. Tests stage its contents through `/double-control/*`. The
  demo app's `/pagerduty` stand-in moves into it.
- **No platform configured, no change.** Without an on-call platform the
  webhook answers `404`, nothing reads PagerDuty, and engagement answers as it
  does today without a credential.

## Capabilities

### New Capabilities

- `oncall-platform-resolution`: a person resolves the incident in the on-call
  platform, and Argus resolves its own. Covers which resolutions count and why,
  signature verification, matching, the resolution note, and an unconfigured
  platform.
- `incident-references`: Argus records what each external tool calls an
  incident, and finds an incident by any of those names.
- `pagerduty-test-double`: a stand-in for PagerDuty's REST reads, staged by the
  test that needs it.

### Modified Capabilities

- `engagement-source`: engagement is read on the platform's own incident, found
  through the incident's references. When no platform incident is linked, the
  answer says so, distinguishably from "nobody engaged" and from "could not
  say".

## Impact

- `argus_core`:
  - `ReportChannel.PAGERDUTY`;
  - a `Reference` value;
  - `Alert` carries the references its source gave it;
  - settings for the webhook secret.
- `argus_core` migrations: `incident_reference` is added to revision `001`
  (still the whole chain).
- `argus_incidents`: a `references` repository. Intake records the alert's
  references, including on an alert that joins an open incident.
- `argus_web`:
  - the Grafana parser reads `groupKey`;
  - `POST /webhooks/oncall`;
  - the layering contract lets `argus_web` reach `oncall_source`.
- `oncall_source`: the `OnCallPlatform` port, and the PagerDuty adapter grown
  from today's engagement adapter.
- `argus_narration`: "from PagerDuty".
- `orchestrator`: engagement wiring passes the incident's references.
- New module `pagerduty_double`, added to `EXCLUDED_FROM_TESTS`, the noxfile's
  stand-ins and `.env.example`. It is off-limits to Claude after it is first
  written.
- `Argus-Demo-Target-App`: the `/pagerduty` routes and `oncall.py` are removed
  (a separate commit there).
- e2e:
  - one new case: resolved from PagerDuty after the flag is off;
  - `test_incident_response.py` stages its acknowledgements in the double
    (user hand-edits).

  No new recording.
- Spikes, done:
  - Grafana's `sha256(groupKey)` was confirmed against a real Grafana;
  - a merge's webhook shape was observed.
