## 1. The pricing service in the demo app (code first, tests after)

- [x] 1.1 Add `io_shop/pricing_service.py`: what the account page asks the pricing
      service for, behind a seam the generator answers without a network round
      trip - the shape `payment_provider.py` already establishes
- [x] 1.2 Put the call on the account page's render path in `account_page.py`, so
      the dependency is in source rather than in a fixture
- [x] 1.3 Give `target_app/state.py` a process clock for the pricing service,
      separate from the shop's, and a restart that moves only it
- [x] 1.4 Extend the Argo CD stand-in so a restart addressed to `io-pricing`
      restarts the pricing service, and the platform reports that application's
      process start time. **Corrected mid-flight**: not a field on
      `GET /argocd/{application}` as `design.md` had it, but
      `GET /argocd/{application}/resource-tree` - the vendor's real route, whose
      `nodes[].createdAt` is genuinely a pod's start time, so no liberty is taken
- [x] 1.5 Serve the catalogue: what `io-shop` calls, what each is for, and whether
      the organisation owns it. `io-pricing` owned, the payment provider not.
      **Open question settled**: a registry the organisation keeps
      (`GET /registry/services/{service}`), homegrown rather than shaped like a
      vendor's catalogue, and it answers the same with nothing seeded - the
      coupling was there all along. The summary cache is in it too, so the
      registry is not a two-line prop
- [x] 1.6 Add the `pricing-service-degraded` scenario: a `dependency_is_slow`
      condition, the generator's latency multiplier on all three quantiles, a flat
      error rate, flat memory, no deploy and no flag - and log lines naming the
      pricing service, its host and the time each call took
- [x] 1.7 Make the restart of `io-pricing` end the scenario's condition, and make
      a restart of `io-shop` leave it exactly where it was. Fixed on the way: the
      shop's pod `createdAt` did not move on a restart at all, because the tree
      read `process_started_at` rather than the latest restart
- [x] 1.8 Cover the new code in the demo app's own suite, after the code, as that
      repo's policy has it - including the two restarts doing different things.
      331 pass (was 294); lint and mypy unchanged at their pre-existing counts
- [x] 1.9 One commit rather than two: nothing here names a commit hash, so there
      is no ordering to respect and the pricing service, the scenario and their
      coverage are one change

## 2. The catalogue on the read tier

- [x] 2.1 **Propose the test** for the catalogue adapter in chat - the response
      shape, the ownership flag, and a service with no entry answering empty
- [x] 2.2 Add the catalogue source to `read_mcp_server`, typed at the adapter so
      the model never parses the provider's JSON. **Design revised mid-flight**:
      an ownership Argus does not recognise is *not* refused - it comes through
      as not-ours and keeps the register's own word, so one new word anywhere in
      the register cannot blind Argus and the incident can still say why a
      service of the organisation's own was out of reach. `Ownership` is
      therefore the vocabulary Argus knows rather than the closed set of what a
      register may say, and `is_ours` tests *for* the word that means ours
- [x] 2.3 Register the tool on the read server and add the typed function to
      `read_mcp_client`. `nox -s guard_exports` is red until a consumer imports
      it, which is task 4.3
- [x] 2.4 `nox -s "test_module(module='read_mcp_server')"` and
      `read_mcp_client` green - 9 new cases pass, `typecheck` clean across 518
      files, `lint` clean

## 3. The kernel: the mode, the address, the contract

- [x] 3.1 **Propose the tests** in chat for `FailureMode.INTERNAL_DEPENDENCY_FAILURE`
      and its `meaning()`, and for `Hypothesis.faulting_service`
- [x] 3.2 Add the mode with its maintainer comment and its model-facing meaning,
      wording the meaning so that what separates it from
      `upstream-dependency-failure` is ownership. Both meanings changed, not one:
      neither of the pair is the obvious reading, so whichever the model
      considers first has to send it to the other
- [x] 3.3 Add `faulting_service` to `Hypothesis`, optional, documented as an
      address rather than a description, with a validator refusing one that names
      no cause - and deliberately *not* refusing this mode without an address,
      since that refusal belongs to the mitigation
- [x] 3.4 Add the catalogue's type to `argus_core.models` - two modules name it, so
      it is a contract and lives in the kernel. `ServiceDependency` plus an
      `Ownership` enum closed at the boundary, and `is_ours` so the gate's
      question is answered in one place
- [x] 3.5 Edit revision `001` in place for the hypothesis column. `nox -s schema`
      still to run against a live postgres - nothing is up right now, and the
      DDL is already proven by `argus_incidents`, whose suite applies the chain
      to a postgres of its own and round-trips the column
- [x] 3.6 Persist and load the new column in the hypothesis repository
- [x] 3.7 `nox -s guard_layering`, `guard_written_columns` and
      `test_module(module='argus_core')` green - 233 and 83 pass

## 4. The Investigator

- [x] 4.1 **Propose the tests** in chat: the answer tool carrying the address, and
      a determination of this mode with no address recorded as answered
- [x] 4.2 Add the field to the answer tool's schema and to the prose that tells the
      model when an address is required
- [x] 4.3 Make the catalogue tool available during investigation, and say in the
      brief what it is for - the channel nobody reads until an incident. It is the
      first channel with no window, so it records no `Reading` and takes no
      arguments; `results.answered` is the windowless counterpart to `served`.
      Unlike the change channel it does not raise when the register is
      unreachable - an absence there supports no conclusion, so the model is told
      and goes on
- [x] 4.4 Carry `faulting_service` through `investigation.py` into the recorded
      hypothesis
- [x] 4.5 `test_module(module='agent_investigator')` green - 77 pass, and the new
      required fetcher reached five test files plus four call sites in root
      `tests/`, all hand-applied

## 5. Mitigation: the strategy and the second gate

- [x] 5.1 **Propose the tests** in chat: the strategy proposing a restart of the
      named dependency, proposing nothing without an address, and the gate
      refusing a name outside the estate
- [x] 5.2 Add the strategy and register it for `INTERNAL_DEPENDENCY_FAILURE`.
      `RestartDependencyStrategy` is a second strategy rather than a branch in
      the first, because the two differ in where the service comes from - the
      alert, or the address the investigation wrote down - and both produce the
      same action kind, so `GENERIC_MITIGATIONS` is untouched
- [x] 5.3 Carry the catalogue into the walk as a value, fetched by the
      Orchestrator before the gate - beside `flag_changes`, for the same reason.
      **Corrected**: not into `propose_action`. The strategy needs no catalogue -
      it reads the address the investigation wrote down - and what weighs
      ownership is the gate. `FetchDependencies` is bound once in `against` and
      handed to both the investigation and the walk, so the model and the gate
      read one register rather than two. Unlike the flag history an unreadable
      register is carried as an empty list rather than as a third value: what
      the walk reasons about is the estate it may touch, and an estate it
      cannot vouch for is one it does not touch
- [x] 5.4 Add the blast-radius question to `admitting`, beside
      `is_a_generic_mitigation` and not inside it, with the alerting service always
      within the bound. `is_within_reach(action, alerting_service, dependencies)`
      - 10 cases, including that an unreadable register (an empty list) still
      leaves every mitigation addressed to the alerting service available
- [x] 5.5 Publish the third refusal in its own words, through the same path the
      other two take to the candidate's row, the timeline and the postmortem.
      The gate asks reach after the kind and before the cap, and asks it by
      calling `is_within_reach` directly rather than through a seam - the way it
      already calls `a_mitigation_answers`. Admissibility is injected because a
      kind nobody pre-authorised cannot be built any more; being out of reach is
      expressible as data, so a stand-in would only hide the state the case is
      about.
      **Found on the way, second**: 5.4's `is_within_reach` read
      `the_subject_of`, which for a flag revert is the flag's name - so wiring
      the gate would have refused every flag mitigation as outside the estate. A
      subject is whatever an action acts on; an address is a service, and only
      some actions have one. `_the_service_it_is_aimed_at` answers `None` for a
      revert, and two new cases hold it: the revert passes, and a rollback of an
      application the register never named still does not.
      **Found on the way**: `_WHY_IT_WAS_REFUSED` is a direct subscript and had
      no entry for `ALREADY_TRIED_ENOUGH`, so an incident refused for hitting the
      retry cap raised `KeyError` while being narrated. Pre-existing, now covered
      by `test_every_refusal_reaches_a_reader_in_words` and fixed
- [x] 5.6 Narrate a restart of something other than the alerting service so a
      reader is not left thinking the shop was restarted. `ActionTaken` carries
      `a_dependency_of`, set by the walk, which is the only party holding both
      the address and the service that alerted - the agent is not
      incident-scoped and the account is rendered from events alone. `None` on
      the ordinary incident, and asserted as firmly as a name: a clause said of
      every action distinguishes nothing.
      **Found on the way**: deciding this by subject would announce every flag
      revert as acting on a dependency, since a flag's name is never the
      alerting service. So `_the_service_it_is_aimed_at` moved out of
      `agent_mitigation` into the kernel as `the_service_addressed_by` - two
      modules ask it now, which makes it a contract - and the gate and the
      announcement draw the same distinction from one `match`
- [x] 5.7 `test_module(module='agent_mitigation')` and `argus_narration` green -
      629 pass across the four modules touched, `lint`, `typecheck` (520 files)
      and `guard_layering` clean. Fixed on the way: `test_admitting`'s empty
      register needed an annotation, which mypy had been failing on since 5.4

## 6. The write tier restarts the right thing

- [x] 6.1 **Propose the tests** in chat: the resource name derived from the
      service, and the start time read per service. Proposed as the whole file -
      the settings builder, the platform double and the three reading cases all
      changed shape, which is not an edit a set of anchors says honestly
- [x] 6.2 Derive the platform resource from the service being restarted rather than
      from `restart_resource_name`. The setting is gone from `Settings` and from
      `.env.example`: a fixed name carried the alerting service's deployment
      into a request addressed at one of its dependencies, so the platform
      restarted the wrong thing and answered that it had worked
- [x] 6.3 Move the restart's confirmation to the platform's application view, taking
      the service, and retire the no-argument `ObserveStartTime`.
      `the_pod_start_time` reads Argo CD's resource tree per application and
      takes the *newest* pod, since a rollout has two in it for a while. Only
      pods - a real tree carries the Deployment, the ReplicaSet and the Service,
      whose creation times have not moved since somebody declared them - and an
      unreadable `createdAt` answers `None` rather than raising, because an
      unconfirmable restart is not a broken one
- [x] 6.4 `test_module(module='write_mcp_server')` green, and the leak scenario's
      own coverage green - that is the evidence the shop's restart is unchanged.
      `test_all` green at 1384. The write client's fake platform had to grow the
      resource-tree route and lose its metrics one: it moved a gauge on restart,
      which is what proved the wait was real end to end, and a fake still
      serving the old surface would have hung rather than failed

## 7. End to end

- [x] 7.1 Rehearse the walk free on fabricated answers with
      `scripts/seed_a_rehearsal.py`, until the plumbing is proven. Green under
      both modes. The script grew a second rewrite: the large-fix rehearsal
      borrows a walk that reached the right conclusion about the wrong file, so
      only `submit_fix` differs, while this one borrows a walk that reached a
      different conclusion entirely - so it is `final_answer` that is rewritten,
      and the tool is now named beside each rewrite rather than assumed.
      **Found what it exists to find**: `get_service_dependencies` was
      registered *below* the guard that skips the index tools, so under `grep` -
      the mode CI runs - the read tier answered "unknown tool", the walk's own
      register read failed, the gate found nothing within reach, and FM-23 was
      unreachable. Whose a dependency is has nothing to do with how anybody
      finds source. Now covered by `read_mcp_server_test/test_server.py`, which
      is the first test of the tool list itself - the suite had cases for what
      every tool answers and none for which ones a deployment offers
- [x] 7.2 **Propose the e2e case** in chat:
      `tests/e2e/test_a_failing_dependency_is_restarted.py` - seed, alert, walk to
      `mitigated`, and assert the pricing service was the thing restarted. It
      asserts the wrong answer too: that `io-shop` was never restarted, since
      restarting the shop is admitted by every gate, provably changes nothing,
      and would still let the walk reach `mitigated` afterwards
- [x] 7.3 Add the assertion the case needs to the e2e framework, if the existing
      restart assertion cannot say which service. Nothing was needed: the case
      reads `ActionTaken.subject` and `a_dependency_of` directly, as its sibling
      reads the restart's absent direction, and a framework assertion used once
      would be a shared name for a question only one case asks
- [x] 7.4 One `record(mode='both')` for the new case only - **two, not one**.
      The case is collected in every mode, and a recording is the world it was
      captured in, so recording only `both` would leave `grep` replaying the
      fabricated answers: green, and proving nothing about the model. `both`
      captured 14 answers for 297,362 in / 26,378 out; `grep` captured 9 for
      92,647 / 12,523.
      **What the paid run was for**: the model named `io-pricing` in both
      worlds, and in `both` it wrote the runner-up down - "if the pricing
      service's own records are not what they appear this would instead be an
      upstream-dependency-failure, but the register explicitly marks io-pricing
      as internally owned" - which is the pair of reworded mode meanings doing
      what they were reworded for. Under `grep`, with no retrieval by meaning at
      all, it reached the same answer: the register carries this mode, not the
      index
- [x] 7.5 `e2e_replay(mode='both')` and `e2e_replay(mode='grep')` green - 62s
      and 43s against the real corpus

## 8. The account of it

- [x] 8.1 `docs/spec-and-architecture.md` §7.3 and §13: the mode, the strategy, and
      the second gate, written as though the design had always said so. Two more
      sections than planned: §7.2 said the model chooses among *three* channels
      and is offered a fourth tool, which the register makes wrong, and §16's
      account of windowing had no place for a channel that has no window
- [x] 8.2 `docs/failure-modes-backlog.md`: the propagation row becomes **Yes**, and
      FM-23 gets its paragraph beside the others - including that its permanent fix
      is the first one out of Code-Fix's reach. Also struck from "what is worth
      building next", which now opens with FM-35
- [x] 8.3 `nox -s lint`, `typecheck`, `guard_layering`, `test_all` green - 522
      files, 6 contracts kept, 1385 tests
- [ ] 8.4 Commit per the repo's one-line convention, then archive as a second commit
