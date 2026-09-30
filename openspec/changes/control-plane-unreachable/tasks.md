Every task under `modules/` and `tests/` is TDD: the failing test comes first,
and Claude may not write it. A task reading "propose the test" means propose the
whole file in chat for the user to add, then implement against it. The demo app
is the exception - its tests are a regression net written after the code, and
Claude writes them there directly.

Tasks are ordered so that everything before §7 is free to verify.

## 1. The vocabulary

- [x] 1.1 Propose the test for an unreachable platform round-tripping through
      the marker: a server-side error carrying it, recognised by
      `argus_core.mcp_transport` and re-raised as the typed exception.
- [x] 1.2 Add the marker, the typed exception and the server-side helper to
      `argus_core.mcp_transport`, beside `EXHAUSTED_ACTION_MARKER`,
      `ActionExhausted` and `an_exhausted_action`.
- [x] 1.3 Propose the test for the platform of each action kind: the four
      Argo CD-backed kinds naming the deployment platform, the flag revert
      naming the flag provider.
- [x] 1.4 Add the `ActionType` → platform mapping to
      `argus_core.models.action`, exhaustive rather than defaulted, so a sixth
      mitigation fails the type check instead of silently acquiring a platform.
- [x] 1.5 Export whatever of 1.2 and 1.4 is public through the front doors
      (`argus_core.mcp_transport`, `argus_core.models`), and add nothing to an
      `__init__.py` but imports and `__all__`.

## 1b. A platform lost mid-action

- [x] 1b.1 Propose the test for a marked failure carrying an undo descriptor
      across the wire: raised with one, parsed back with one, and a marked
      failure without one still arriving as it does today.
- [x] 1b.2 Let `an_unreachable_platform` take an optional undo descriptor and
      serialize it after the marker; parse it back where `isError` becomes an
      exception, so `PlatformUnreachable` carries it.
- [x] 1b.3 Propose the test for `trying.py`: a platform lost after the
      suspension landed still returns `PLATFORM_UNREACHABLE`, and the outcome
      carries what has to be put back.
- [x] 1b.4 Return the descriptor on the outcome, so the action row records the
      change as any other action that changed something does.

## 2. The write tier reports it

- [x] 2.1 Propose the tests for `write_mcp_server`: a refused connection, a
      timeout and a `503` each reported as an unreachable platform, and a
      platform that answers and rejects the action still reported as a failed
      action.
- [x] 2.2 Add the predicate that recognises an unreachable platform from a
      response or a transport failure to `write_mcp_server.argocd`, as
      vocabulary - its docstring bars exception *policy* there, not this.
- [x] 2.3 Raise it from `rolling_back`, `restarting`, `scaling` and `pinning`,
      each for itself, so every module keeps its own name for the failure.
      Three shapes per tool: the read before any write, the suspension itself,
      and the action proper - and where the suspension landed, the failure is
      marked *and* carries its descriptor rather than escalating.
- [x] 2.5 The one carve-out: `restarting`'s post-acceptance failure stays an
      ordinary refusal and escalates. Not for want of a descriptor - a restart
      never carries one - but because Argus cannot say whether a restart is
      happening, and every verification after it would be unreliable.
- [x] 2.6 Rewrite `scaling`'s post-suspension test, which landed asserting the
      old behaviour. Hand-applied, so it goes in the 1b.3 batch.
- [x] 2.4 Surface it through `write_mcp_client` as the typed exception, so a
      caller catches a type rather than reading a string.

## 3. The walk narrows itself

- [x] 3.1 Propose the test for `agent_mitigation.trying`: an unreachable
      platform caught ahead of the broad `except`, returning the new verdict
      rather than `ESCALATED` or `NOT_ATTEMPTED`.
- [x] 3.2 Add the verdict and catch the exception in `trying.py`, above the
      broad `except` and below `ActionExhausted` - the ordering is load-bearing
      for the reason the existing comment gives.
- [x] 3.3 Propose the tests for candidate advance: candidates whose action acts
      through the unreachable platform passed over with no action proposed and
      no attempt recorded, and a candidate on a reachable platform still tried.
- [x] 3.4 Carry the unreachable platform on the walk's state and pass over
      same-platform candidates where the ordering is decided
      (`orchestrator.walk.candidates` / `choosing`).
- [x] 3.5 Propose the tests for status derivation, both halves: an unreachable
      platform with candidates run out deriving `ESCALATED` rather than a
      further investigation round or `FIXING`, **and** an unreachable platform
      with a reachable candidate still ahead deriving `MITIGATING`.
- [x] 3.6 Redirect the past-the-end tail in `orchestrator.walk.state`: the index
      check stays first, and the flag turns `INVESTIGATING`/`FIXING` into
      `ESCALATED`. Not a branch before the arithmetic - that returns `ESCALATED`
      the instant the rollback fails, while the flag revert is still ahead.
- [x] 3.7 Propose the test that an escalation over an unreachable platform
      names the platform and the action kinds it took away, and does not
      consist of one action's transport error.
- [x] 3.8 Write what the escalation reports.

## 4. The record says so

- [x] 4.1 Propose the test for the event: one per incident naming the platform
      and the action kinds it carries, published before the next candidate is
      proposed, and not one per candidate passed over.
- [x] 4.2 Add the event to `argus_core.events` and publish it where the
      unreachability is first learnt.
- [x] 4.3 Propose the test for its narrated line.
- [x] 4.4 Add the line to `argus_narration`, naming the actions that were
      unavailable and not the platform alone, and generating them from the
      `ActionType` map of 1.4 so a sixth mitigation fails the type check rather
      than leaving a stale sentence.

## 5. The Target Environment

- [x] 5.1 Add the scenario switch to `Argus-Demo-Target-App`: the deployment
      platform's **acting** routes answer `503` - rollback, restart, resource
      write, spec - while its reporting routes keep answering and the shop keeps
      serving and reporting metrics. Not the `/argocd/*` prefix wholesale:
      `GET /argocd/{application}` is the deploy-history read, and refusing it
      hides the deployment that is this incident's first candidate.
- [x] 5.2 Stage the incident itself - a deployment and a flag both moving in
      the window, the deployment the closer and more specific change so that
      the rollback is the more plausible cause.
- [x] 5.3 Cover both in the demo app's own tests, written after the code.
- [x] 5.4 Commit and push the demo app. Code-Fix reads GitHub rather than
      disk, so an unpushed commit buys a confident fix to the wrong file.

## 6. Free verification

- [x] 6.1 `lint`, `typecheck`, `guard_layering`, `guard_exports`.
- [x] 6.2 `test_all`.
- [x] 6.3 Propose the e2e case: the rollback reached for, the platform
      unreachable, the remaining platform candidates passed over, the flag
      revert taken, the incident `MITIGATED`, and the event in the record.
- [x] 6.4 Bring the stack up and drive the scenario by hand, confirming the
      shop stays healthy and the walk reaches the flag revert - before anything
      is paid for.

## 7. The recording

- [x] 7.1 Record the walk under `both`, against the real API. One mode only:
      nothing in this claim varies by which tool found a file.
- [x] 7.2 Confirm from the recording that the model actually ranked the
      rollback above the flag revert. If it did not, 5.2's staging is what
      changes, not the assertion.
      **It did not.** The staged deploy reworks the lifetime average and the
      symptom is a `ZeroDivisionError` on the monthly path the flag gates, so
      the model ranked the flag first and named the deploy's irrelevance as its
      reason. The recorder refused the corpus for carrying no
      `platform-unavailable`, and the set was deleted. 5.2 restages with a
      deploy that plausibly owns the failing call path; 7.1 re-runs after it.
- [x] 7.3 `e2e_replay(mode='both')` green, and report the recorded token spend.
      All 39 items green, across two runs. The first collected 39 and ran 29
      under `-x`: 28 passed and `test_slack_hears_the_incident` failed when the
      walk died on `get_metrics_summary: timed out` inside mitigation
      verification. That case and the 10 that `-x` had stopped were then run
      together and all 11 passed. The timeout is intermittent, unrelated to this
      change, and its own defect - it strands an incident in `mitigating` with no
      verdict and leaves no row in `replay_log`.
      Recorded spend for this walk: **136,428 tokens** - 47,178 cache-write,
      79,709 cache-read, 18 input, 9,523 output, over 9 answers.

## 8. The written record

- [x] 8.1 Update `docs/spec-and-architecture.md` §13 - autonomy rests on
      reachability as well as on verification, stated as a rule rather than as
      a note about this scenario.
- [x] 8.2 Update `docs/failure-modes-backlog.md`: FM-30 in the family table,
      and remove it from "what is worth building next".
- [ ] 8.3 One-line commit message, approved before committing. Archive as a
      second separate commit.
