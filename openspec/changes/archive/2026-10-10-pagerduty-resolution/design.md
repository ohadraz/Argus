## Context

Change (b) gave a person one way to report an incident resolved, the Argus UI:
`resolve_incident(id, Report(by, channel, note), connections, publisher)`. This
change adds a second channel, the on-call platform, and PagerDuty is the first.

What Argus has today:

- **Intake** (`argus_web/grafana.py` → `argus_incidents.intake.start_incident`)
  stores the normalised `Alert` as JSONB. It keeps no id from the tool that sent
  it, and it never reads `groupKey`. The demo's monitoring sends no `groupKey`;
  the e2e builder does.
- **Engagement** (`oncall_source.pagerduty_adapter.reported_incident`) passes
  **Argus's own UUID** to PagerDuty as the incident id. Only the demo's
  stand-in, which answers any id, makes that work.
- **A signed webhook precedent:** `argus_web/pushes.py` verifies GitHub's
  `X-Hub-Signature-256` over the raw body and answers `401` on a mismatch.
- **Nothing pages PagerDuty** in the demo or in the e2e stack.

The spike (2026-10-09, a real developer account; raw deliveries in
`.claude/local/pd-spike/`) established:

1. A webhook's `data.incident_key` is **null** for an incident opened through
   the Events API. The sender's `dedup_key` exists only as the alert's
   `alert_key`, and `GET /incidents?incident_key=<key>` finds the incident by it.
2. `event.agent` says who acted:
   - a person in the UI is a `user_reference` (`summary` = their name);
   - the Events API (monitoring clearing the alert) is an
     `inbound_integration_reference`.
3. A resolution note is not on the resolve. PagerDuty writes a separate note,
   `content` = `"Resolution Note: <text>"`, about a second earlier, and fires
   `incident.annotated` for it.
4. The signature is `v1=<hex HMAC-SHA256(raw body, secret)>` and verified on
   every delivery.

Two further spikes established:

5. Grafana's PagerDuty `dedup_key` is `sha256(groupKey)`, the same `groupKey`
   its webhook to Argus carries. This was observed on Grafana 13.2.3 and
   matches its source (`Key.Hash()`, "as integrations may have maximum length
   requirements"). Raw payloads are in `.claude/local/grafana-spike/`.
6. A merge resolves the merged incident with the merging person as `agent`, and
   moves its alerts onto the target (D5).

## Goals / Non-Goals

**Goals:**
- A person who resolves the incident in PagerDuty resolves Argus's incident,
  credited by name, through PagerDuty, with their note.
- The on-call platform sits behind a port. PagerDuty is one adapter, and a
  second platform is one more adapter.
- Without an on-call platform, Argus behaves exactly as it does today.
- Engagement is read on the platform's own incident.
- Every "resolved" that does not resolve Argus's incident says why: in the
  spec, in this design, and in the code.

**Non-Goals:**
- Argus opening or paging a platform incident. Monitoring pages; Argus only
  links.
- Acting on mid-incident notes (`incident.annotated`). That would be the
  two-way conversation dropped with Slack inbound.
- Making the demo's monitoring page PagerDuty or send a `groupKey`. The demo
  never paged anyone. The e2e case plays both Grafana and PagerDuty.
- Exposing Argus publicly. PagerDuty needs a public URL, and providing one (an
  ingress, or a tunnel for a demo) is the deployment's job. The e2e test posts
  the webhook itself.
- A second adapter, or a generic intake for unknown alert sources (spec §25).

## Decisions

### D1. The port: `OnCallPlatform`, in `oncall_source`

A `Protocol` named for the role, in the module that already owns the on-call
vocabulary boundary. `PagerDuty` implements it, and is the only class that
imports `pagerduty` or names a route, header, event type or field. Its methods:

- `read_delivery(body: bytes, headers: Mapping[str, str]) -> Delivery`: verify
  the signature (raises `DeliveryUnverified`) and say what happened, in Argus's
  words.
- `keys_of(platform_incident) -> list[str]`: the keys the incident's senders
  stamped on it (PagerDuty: each alert's `alert_key`).
- `incident_for(keys) -> str | None`: the platform incident carrying any of
  those keys (D6).
- `resolution_note(platform_incident) -> str | None` (D4).
- `reported_incident(platform_incident)`: today's engagement read, now taking
  the platform's id (D6).

The adapter also declares its `channel: ReportChannel` (`PAGERDUTY`), so the
web layer never names the vendor.

`Delivery` is a small closed union of Argus's own values:

- `ResolvedByAPerson(platform_incident, by)`;
- `ResolvedWithoutAPerson(platform_incident, why)`;
- `Merged(platform_incident, into)`;
- `Reopened(platform_incident)`;
- `Irrelevant(event)`.

*Alternatives:*
- A new `oncall_platform` module, which would put a second module between
  Argus and one vendor, for engagement and resolution alike.
- Renaming `oncall_source`: churn, for a word ("source") that still describes
  it, since every call reads the platform.

Composition roots build the adapter: `argus_web`'s lifespan and
`orchestrator.sources`. With no API key configured, no adapter is built
(`None`), and that `None` is how "no platform" travels.

### D2. Linking: `incident_reference`, keyed by what each tool calls the incident

- **Table** (added to revision `001`):
  `incident_reference(incident_id FK, source TEXT, kind TEXT, value TEXT, recorded_at)`,
  with `UNIQUE (source, kind, value)`. It follows `slack_thread`'s precedent: a
  new tool adds rows, never columns on `incident`.
- **Values:** `argus_core.models.Reference(source, kind, value)`, and
  `Alert.references: list[Reference] = []`.
- **Intake:** the Grafana parser records
  `Reference("grafana", "notification_key", sha256(groupKey))`, the key Grafana
  stamps on every notification it sends a paging tool. It stores that, not the
  raw `groupKey`, because the hash is what any paging tool will hand back.
  `start_incident` writes the alert's references with `ON CONFLICT DO NOTHING`,
  for a new incident and also for an alert that joins an open one.
- **Repository** (`argus_incidents.references`): `add(conn, incident_id,
  references)` and `get_incident_by_value(conn, kind, values)`. That is a
  relational lookup, so it has a descriptive name rather than `get`.

### D3. Matching at the resolve webhook, not at intake (Q19)

On `ResolvedByAPerson(platform_incident, by)`:

1. `keys_of(platform_incident)` fetches the alert keys.
2. `get_incident_by_value("notification_key", keys)` finds the Argus incident.
3. Argus records `Reference(<channel>, "incident", platform_incident)`, so
   later reads (engagement) skip the lookup.
4. `resolution_note(platform_incident)` (D4).
5. `resolve_incident(id, Report(by, channel, note), ...)`.

Before step 1, a stored `Reference(<channel>, "incident", ...)` is consulted,
which spares the read when the incident was linked earlier (by engagement).
A merge target needs no stored reference, because the merged alerts move onto
it (D5).

*Why not at intake:* Grafana pages PagerDuty and Argus at the same moment, so
when Argus asks, PagerDuty's incident may not exist yet. At the resolve, it
certainly exists.

*Costs accepted:* REST reads inside PagerDuty's 5-second window, and lookups
for platform incidents Argus never had (one read each, then `2xx`).

### D4. The resolution note is found by PagerDuty's own prefix (Q20)

The adapter reads `GET /incidents/{id}/notes`, takes the note whose `content`
starts with `"Resolution Note: "`, and strips the prefix. With none, there is no
note.

*Why:* PagerDuty has no field linking a resolve to its note:

- the resolve log entry carries no note;
- the note is a separate entry, like any mid-incident note;
- the webhook carries neither.

PagerDuty's community manager recommends this prefix (May 2025) and says the
missing field is a logged bug with no timeline (Feb 2026).

*Rejected: "the latest note"*, the accepted answer in that thread. For an
incident resolved without a note, it presents an older mid-incident note as the
resolution.

*Risk:* the prefix is undocumented wording. If PagerDuty changes it, Argus
records no note, never a wrong one.

This text goes into the adapter's docstring with both sources.

### D5. Only a person's resolution counts (Q9, Q11)

The adapter maps an `incident.resolved` delivery as follows, checking the rows
**in this order**:

| What resolved it | Delivery | What Argus does, and why |
|---|---|---|
| `resolve_reason` is a merge | `Merged(into)` | Logs and ignores it. The incident moved, it did not end. |
| `agent` is a user | `ResolvedByAPerson` | Resolves. A person has the world in hand and is owed the account (§16). |
| `agent` is an integration | `ResolvedWithoutAPerson` | Logs and ignores it. Monitoring cleared the alert, which is a metrics signal, and Argus reads recovery from the metrics itself. |
| `agent` is null, or the resolve is a timeout | `ResolvedWithoutAPerson` | Logs and ignores it. Nobody decided anything. |

The merge spike settled two facts.

**The merge row comes first.** A merged incident's `incident.resolved` carries
the *person who merged* as `agent`, so read in any other order a merge would
resolve Argus's incident.

**A merge needs no reference.** PagerDuty moves the merged incident's alerts to
the target, so the target carries the original alert keys, and resolving the
target later is matched by D3 with nothing stored. `resolve_reason` is an
object (`merge_resolve_reason`, with the target's `incident`) in both the
webhook and REST.

Only `incident.resolved` and `incident.reopened` are read; every other event is
`Irrelevant`. A reopen after Argus marked the incident resolved is logged and
does nothing (Q11).

Every row of this table becomes a comment beside the branch that implements it,
and a sentence in the spec.

### D6. Engagement reads the platform's incident

`orchestrator.sources._who_responded(incident_id)` finds the platform incident:

1. the stored `(channel, "incident")` reference;
2. otherwise, the adapter's `incident_for(keys)`
   (`GET /incidents?incident_key=<key>`, which PagerDuty matches against
   `alert_key`), stored once found.

Engagement then reads that incident. If no platform incident can be found, the
answer is a third state, `NotPaged`, distinct from `None` ("could not say") and
from zero minutes ("nobody engaged"). The postmortem says that no on-call
incident was linked, and invents no figure.

### D7. The webhook: `POST /webhooks/oncall`

- `async`, reading the raw body, as `/webhooks/github/push` does.
- No platform configured → `404`.
- `DeliveryUnverified` → `401`. PagerDuty drops other `4xx` and does not retry.
- A REST failure while matching → `503`. PagerDuty retries for 48 hours, so a
  transient outage loses nothing.
- Otherwise `202`, whatever the delivery turned out to be. That includes "no
  Argus incident matches", which is logged.
- Redelivery is harmless. `resolve_incident` is a guarded UPDATE that publishes
  only when the row moved, so `X-Webhook-Id` needs no table.
- Settings: `pagerduty_webhook_secret`. An empty secret refuses every delivery,
  as `github_webhook_secret` does.
- Layering: `argus_web` may import `oncall_source` (contract updated).
  `oncall_source` gains no new dependency beyond `argus_core`.

### D8. `pagerduty_double`

- A new dev-only module, shaped like `slack_double`: FastAPI with `/health`,
  `POST /double-control/reset`, and `POST /double-control/incident`, which
  stages one incident whole (alert keys, acknowledgements, users, notes).
- It serves PagerDuty's REST reads:
  - `/incidents/{id}`;
  - `/incidents?incident_key=`;
  - `/incidents/{id}/alerts`;
  - `/incidents/{id}/notes`;
  - `/users/{id}`.
- TLS with a self-signed certificate it mints at start, because the SDK refuses
  `http://`. `pagerduty_verify_tls=false` is kept for it.
- The double knows PagerDuty's behaviour, never a scenario
  (double-seeding-style). Today's demo stand-in derives acknowledgements from
  the scenario's metrics, which is exactly what moves out: the engagement e2e
  case stages its own acknowledgements.
- Started by the noxfile beside the other doubles. It is in
  `EXCLUDED_FROM_TESTS` and `root_packages` is untouched (doubles aren't
  listed). It is off-limits to Claude after first being written, as
  `github_double` was.

### D9. e2e

- **New case** (Q18 ii): feature-flag-toggle, seeding answers with
  `less_code_fix=True`.
  - The test posts the Grafana alert, with its `groupKey`.
  - It stages a PagerDuty incident whose alert key is `sha256(groupKey)`, with a
    resolution note and a user.
  - It waits for the flag to go off.
  - It posts a signed `incident.resolved` from that user.
  - It asserts: `resolved`, the flag still off, a postmortem, and an account
    naming the PagerDuty user, "PagerDuty" and the note.
- `test_incident_response.py` stages its two acknowledgements in the double
  (the user edits it).

## Risks / Trade-offs

- [A stored platform id goes stale after a merge] → the stored id is the merged
  source, which no longer holds alerts. Engagement would then read the source's
  acknowledgements only. This is accepted; the resolve path is unaffected,
  because it matches the target by its keys.
- [The note's prefix is undocumented] → D4: a changed prefix loses the note and
  never invents one.
- [REST reads inside the 5-second window] → at most three small reads, and a
  timeout answers `503`, so PagerDuty retries rather than drops.
- [Argus has no public URL] → out of scope (Non-Goals). The spec states that
  the webhook needs one.
- [Unknown platform incidents cost a read each] → bounded by the webhook
  subscription's scope, which the operator filters to the services Argus
  watches.

## Migration Plan

`incident_reference` is added to revision `001`, which is still the whole
chain, so `nox -s schema` drops and recreates. No data migration. Incidents
from before the change have no references, so they cannot be resolved from
PagerDuty and read engagement as `NotPaged`.

## Open Questions

None.
