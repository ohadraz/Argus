Tests are the user's to write throughout (`AGENTS.md`): each task below that
names a test means proposing it whole in chat, having it added, watching it
fail, and only then writing the code under it.

## 1. Who responded, and for how long

- [x] 1.1 Propose the test: two responders who acknowledged at different moments
      are answered with both of their spans added together, each from their own
      acknowledgement rather than from the incident's start.
- [x] 1.2 `modules/oncall_source/`, scaffolded per the `new-module` skill,
      depending on `pagerduty` and on nothing of Argus's but `argus_core`.
- [x] 1.3 The sum: each responder's earliest acknowledgement to the incident's
      end, added together, over an incident the caller supplies.
- [x] 1.4 Test: two people acknowledging, one of them twice, are two responders.
- [x] 1.5 Test: an incident nobody acknowledged answers no minutes and no
      responders - distinguishably from a provider that could not be read.

## 2. Reaching the provider

- [x] 2.1 The listing: `RestApiV2Client` aimed by `base_url`, the incident's
      acknowledgements, the vendor's errors raised as this module's own
      unavailability.
- [x] 2.2 The PagerDuty key and base URL in `argus_core.config`, `.env.example`
      and `noxfile.py`'s e2e settings, the key absent by default. Nothing in
      `docker-compose.yml`: the services that read them run as host processes.
- [x] 2.3 Test: no credential configured means the source reports it could not
      answer, and no request is sent.

## 3. The titles

- [x] 3.1 Propose the test: a responder whose provider record names a job title
      is reported with that title.
- [x] 3.2 The user lookup, one request per acknowledgement, behind the same
      client, composed onto `Acknowledgement.job_title` in the adapter.
- [x] 3.3 Test: a responder whose record cannot be read leaves the minutes and
      the count standing, with that title absent.
- [x] 3.4 `Engagement` carries the titles, read off the acknowledgements
      themselves rather than through a second port.

## 4. On call in the demo

- [x] 4.1 PagerDuty-shaped incident and user endpoints on the Target Service,
      over the scenario it already seeds: an authored acknowledgement a few
      minutes in, by an authored user with a job title. Written code-first, per
      the demo app's rule.
- [x] 4.2 The endpoints' own regression tests, in the demo repo, after the code.
- [x] 4.3 `orchestrator/postmortem.py` wires the adapter into the `Engagement`
      port in place of `_no_engagement_source`.
- [x] 4.4 Test: the e2e stack produces a postmortem reporting engineer minutes
      rather than an absence, and the minutes are shorter than the incident.

## 5. The document says it

- [x] 5.1 Test: the titles reach the document, and no responder is named in it.
- [x] 5.2 The document and the incident page report the minutes, the count and
      the titles.
- [x] 5.3 Test: an unattended incident reports zero minutes rather than an
      absent source, and the assumptions do not claim a source failed. Already
      covered - `test_absent_figures`'s "nobody responded" case.

## 6. Closing out

- [x] 6.1 `lint`, `typecheck`, `test_module` for each touched module, then
      `test_all`.
- [x] 6.2 `integration`, and `e2e_replay` in the background.
- [x] 6.3 Spec §7.6 and §21.3 updated for what `engineer_minutes` now measures,
      per the `spec-doc-style` skill.
- [x] 6.4 Re-read this change's delta specs against what was built before
      archiving - the last change's deltas described a design the tests had
      already moved past.
- [x] 6.5 One-line commit, approved before it is made. The Target Service's
      change is its own commit in its own repo.
