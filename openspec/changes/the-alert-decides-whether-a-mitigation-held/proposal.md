## Why

The backlog's one known defect: a flap with no rhythm is reported mitigated. Mitigation
confirms on the first clear minute because nothing in the metrics window says how long an
irregular flap pauses, and no statistic over that window can say it without naming a
fitted number. The alert that opened the incident already encodes what "acceptable" means
for the service, so whether a mitigation held is the alert rule's call, as it would be an
SRE's.

## What Changes

- For an alert about a series (`claim = series-condition`), Mitigation's verdict comes from
  the alert rule's state when the alert names its rule: back to normal over a range that
  followed the change means the action is confirmed; still firing at the deadline means it
  is refuted, and the walk tries the next candidate. Argus's own metrics reach no verdict
  on such an action: one unlucky minute must not undo a fix that worked.
- The deadline is read off the rule, not configured: the change being in force, plus the
  rule's query range, plus one evaluation interval, plus its keep-firing-for period, plus
  the existing reporting lag.
- Argus polls the rule's state through the read tier rather than waiting for a resolved
  webhook, which Grafana batches by `group_interval` and which can be lost.
- The alert protocol gains a vendor-neutral rule reference, and reading a rule's definition
  and state becomes a port; Grafana is its adapter, filling the reference from the rule's
  uid in `generatorURL`, the one place Grafana's webhook names the rule that fired.
- A firing of the same rule while its incident is open is merged into that incident, and a
  `resolved` webhook never opens one. **BREAKING** for intake: today every webhook opens an
  incident.
- Alerts reporting a finding of their own (`claim = own-finding`) keep today's
  confirmation: the store's receipt, or readings returning.
- The demo app grows simulated Grafana alert rules: evaluated over its own generated
  metrics when read, served through Grafana's rule-definition and rule-state APIs, and named
  by every alert it sends. Existing scenarios get rules that resolve inside the three clean
  minutes the fixture shows after a fix.
- A new demo scenario reproduces the defect: a flag revert after which the shop flaps with
  irregular gaps and the alert never resolves.
- The recovered minute the postmortem measures from is still read off the metrics
  (`find_recovery`); only the verdict moves to the alert.

## Capabilities

### New Capabilities
- `alert-decided-verification`: how Mitigation judges an action on a series-condition alert
  from the rule's state, and how its deadline is read off the rule.
- `target-service-alert-rules`: the demo app's simulated Grafana alerting - rule
  evaluation, firing webhooks that link to their rule, rule definition and state APIs.
- `irregular-flap-scenario`: the demo scenario in which a fix seems to hold and the shop
  goes on flapping without a rhythm.

### Modified Capabilities
- `incident-lifecycle`: the webhook ignores `resolved` and merges a re-firing of an open
  incident's rule into that incident.
- `mitigation-retry-walk`: the reporting lag extends the rule-derived deadline rather than
  the clear-minutes one.

## Impact

- `argus_web` (Grafana parser, intake), `argus_incidents` (merge lookup), `argus_core`
  (`Alert` gains the rule identity), `read_mcp_server` / `read_mcp_client` (rule definition
  and state), `agent_mitigation/trying.py` (verdict and deadline for series-condition
  alerts).
- Demo app: rule evaluator in-process on the simulated clock, two Grafana-shaped routes,
  the new scenario.
- `tests/e2e/framework` (user's edit): the alerts the tests post link to the rule the
  staged scenario trips, as the demo app reports it.
- One paid recording for the new scenario's case (~$5). Existing recordings survive unless
  a case's verdict flips; a full `e2e_replay` settles that and the suite's runtime.
- Narrows "A flap with no rhythm is still reported mitigated" in
  `docs/failure-modes-backlog.md` to the alerts that name no rule.
