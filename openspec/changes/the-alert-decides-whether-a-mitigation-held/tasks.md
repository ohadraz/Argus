## 1. Demo app: simulated alerting (fixture, tests after code)

- [x] 1.1 The shop's rules: query range, group interval, `keepFiringFor`, condition over the generated metrics; existing scenarios' rules resolve inside the three clean minutes
- [x] 1.2 Rule state evaluated on read (no background loop), on the simulated clock, over the generated (possibly frozen) window
- [x] 1.3 Every alert the shop sends links to its rule in `generatorURL`, as Grafana's webhook does
- [x] 1.4 Routes: `GET /api/v1/provisioning/alert-rules/{uid}`, the rule-group route, `GET /api/prometheus/grafana/api/v1/rules?rule_uid=`
- [x] 1.5 The irregular-flap scenario: revert clears one minute, then single failing minutes with non-repeating gaps keep the rule firing
- [x] 1.6 Demo app suite green; commit and push the demo app

## 2. Intake (TDD)

- [x] 2.1 `Alert` carries a vendor-neutral rule reference; the Grafana adapter fills it from the rule uid in `generatorURL` and reads `status`
- [x] 2.2 A `resolved`-only webhook opens nothing
- [x] 2.3 A firing whose rule matches an open incident joins it; a closed one's is a new incident

## 3. Read tier (TDD)

- [x] 3.1 A vendor-neutral alert-rule port (definition: range, interval, `keepFiringFor`; state: firing/normal, last evaluation) with a Grafana adapter, served by the read tier with a typed client
- [x] 3.2 Not added to any agent's model tool list

## 4. Mitigation (TDD)

- [x] 4.1 Deadline for a series alert = action + range + interval + `keepFiringFor` + reporting lag
- [x] 4.2 Confirm on a normal evaluation whose range starts after the action; refute at the deadline while firing; no early refutation from metrics
- [x] 4.3 Own-finding alerts keep the receipt / readings-returning path unchanged
- [x] 4.4 The recovery minute is still read off the metrics and recorded with the verdict

## 5. End to end

- [x] 5.1 Propose the `tests/e2e/framework` change so the alerts the tests post carry the demo app's rule reference (user applies)
- [x] 5.2 Propose the e2e case for the irregular flap (user applies)
- [x] 5.3 Full `e2e_replay(mode='both')`: every existing case passes; the run's duration is on record in its ledger
- [x] 5.4 Paid recording of the new case (~$5), after the preflight checks
- [x] 5.5 Spec §: verification judged by the alert rule; `docs/failure-modes-backlog.md` defect narrowed to alerts that name no rule

## 6. Review before commit

- [x] 6.1 The rule decides before the metrics' own verdicts, and a metrics read that fails does not stop it (TDD)
- [x] 6.2 `keep_firing_for` read under the provisioning API's own name, in Argus and the demo app (TDD)
- [x] 6.3 A rule whose evaluation measured nothing (`health` error/nodata) is unreadable (TDD)
- [x] 6.4 A webhook is read from its first alert still firing (TDD)
- [x] 6.5 Comments, docstrings, spec, backlog and this change's artifacts say what the code does
- [x] 6.6 Test gaps the review found: rule-path branches, wiring, read-tier parsing, intake repository, demo routes
- [x] 6.7 Redundant and misplaced tests; restated wire vocabulary
- [x] 6.8 `@contextmanager` functions annotated `Iterator` rather than `Generator`
- [x] 6.9 Full `e2e_replay(mode='both')` green after the review
