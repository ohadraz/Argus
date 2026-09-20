## 1. Make the median a signal worth reading

- [x] 1.1 Fix the generator's latency noise: `p50_ms` and `p95_ms` currently
      take the same absolute wobble, which makes the median ±18% of its
      baseline and the tail ±4%. Make the wobble proportional, so the median is
      the steadier of the two as it is in a real service
- [x] 1.2 Add `p50_ms` to the signals `argus_core.anomaly` judges departure and
      subsidence on, beside `error_rate`, `p95_ms` and `memory_used_bytes`
- [x] 1.3 Re-run the onset check over every existing scenario and confirm each
      is dated where it was before 1.1. With the old noise model the two flag
      scenarios moved a minute earlier than the flag itself, which is what 1.1
      exists to fix - that specific regression is the check
- [x] 1.4 Add the scenario to `_WHAT_FIRED` in `target_app/monitoring.py`,
      claiming the existing `HighLatency` rule

## 2. The cache, in the shop's own source

- [x] 2.1 Add `io_shop/summary_cache.py`: a `LookUpSummary` callable seam and
      the answer it returns, shaped as `payment_provider.AskTheProvider` is
- [x] 2.2 Have `io_shop/account_page.py` consult the cache and recompute on a
      miss, so the fallback is real code and the page is correct either way
- [x] 2.3 Add `deploy/values-production.yaml` holding the cache endpoint, and
      read the endpoint from it at startup - a file nobody reads is not
      configuration
- [x] 2.4 Cover 2.1-2.3 in the demo app's own suite (code first, tests after -
      the demo app is a fixture and is not under TDD)

## 3. Generating the incident

- [x] 3.1 Add `CacheEndpoint` to `generator.py` beside `ProviderOutage`: when
      the endpoint became unreachable, and when it was put back
- [x] 3.2 Draw the hit/miss per rendered page, and only when a scenario stages
      the condition - each minute seeds one generator, so a draw taken
      unconditionally would shift every draw after it and move the figures of
      every scenario that has nothing to do with a cache
- [x] 3.3 Compose each request's latency from the path it took, so `p50` and
      `p95` fall out of the sample rather than being asserted
- [x] 3.3a Set the healthy hit ratio around 90% and keep the miss distribution
      tight, so that `p95_ms` barely moves - before the onset it already
      describes a miss, and after it describes the same miss. Confirm from the
      generated buckets that `p50_ms` departs steeply and `p95_ms` does not:
      the tail masking the incident is the property this scenario is for
- [x] 3.4 Add `cache_hit_ratio` to `GeneratedMinute` and to `/metrics`, reported
      on every minute of every scenario
- [x] 3.5 Emit the connection-failure log line naming the configured host and
      port, at the density the other failure lines use, naming no cause
- [x] 3.6 Verify the cache condition changes nothing for a scenario that does
      not stage one: no draw is taken, so every other scenario's figures are
      identical before and after this group. Bit-identity against *main* is not
      the check - task 1.1 deliberately moved every latency figure - so what is
      compared is each scenario's own output with the condition absent, and
      each scenario's onset, which must not move

## 4. The deploy, and the diff behind it

- [x] 4.1 Commit `deploy/values-production.yaml` with the working port, then a
      second commit changing it - the two commits the diagnosis diffs
- [x] 4.2 Add the scenario to `scenarios.py`, staging the cache condition and
      naming the commit that changed the port
- [x] 4.3 Open the `is_generated → empty revision history` branch in
      `argocd_application` so a generated scenario can carry a deploy
- [x] 4.4 Report the application's automated-sync state on the stand-in's
      application endpoint
- [x] 4.5 Confirm the code index reconciles cleanly over a repository that now
      carries a YAML file, and that other scenarios' seeded commit is unaffected

## 5. Rolling back, on the stand-in

- [x] 5.1 Add `POST /argocd/{application}/rollback` to the stand-in, shaped as
      the platform's own rollback operation and addressed by history id
- [x] 5.2 Refuse the rollback while automated sync is enabled, as the real
      platform does, and add the operation that suspends it
- [x] 5.3 Implement the rollback by putting the endpoint back in the service's
      own state, so the incident genuinely ends and can be honestly graded
- [x] 5.4 Refuse a rollback to a revision absent from the application's history

## 6. Argus: the mode and the action

- [x] 6.1 Add `FailureMode.CONFIG_INDUCED_FAILURE` to `argus_core.models`, with
      the comment saying what separates it from a bad deployment and a flag
- [x] 6.2 Add the action and its undo descriptor, carrying both the revision to
      return to and the automated-sync state to restore
- [x] 6.3 Extend the undo path so a descriptor recording two pieces of prior
      state restores both, and a partial restore escalates rather than closing
- [x] 6.4 Add `cache_hit_ratio` to `MetricBucket`, optional so a service with no
      cache reports its absence rather than zero
- [x] 6.5 ~~Add the automated-sync state to what the Argo adapter reads~~ -
      **folded into 7.1**. The read tier must not learn either: a `ChangeEvent`
      is vendor-neutral by construction, and a history identifier and a sync
      policy are one platform's vocabulary. The write tier already talks to
      the platform directly, as `restarting.py` does, so the rollback tool
      reads both itself

## 7. Argus: performing it

- [x] 7.1 Add the rollback tool to `write_mcp_server`: read the application for
      the running entry and the sync policy, suspend automated sync, roll back
      to the immediately preceding deployment, and return the descriptor
      recording both changes. Refuse before touching anything where there is
      no earlier entry
- [x] 7.2 Add its typed function to `write_mcp_client`
- [x] 7.3 Add the strategy to `agent_mitigation` and register it in
      `DEFAULT_STRATEGIES` for the new mode
- [x] 7.4 Add the action's kind to the declared set of generic mitigations
- [x] 7.5 Confirm a confirmed rollback leaves the incident mitigated and not
      resolved

## 8. Proving it end to end

- [x] 8.1 Propose the e2e case in chat for the user to add - `tests/` is
      off-limits - staging the scenario and asserting the diagnosis, the
      rollback, and the incident ending
- [x] 8.2 Record the scenario's model answers against the real API under `both`
      mode, and commit the recording
- [x] 8.3 Run `e2e_replay(mode='both')` green, and report the token spend from
      the real recording run
- [x] 8.4 Run `lint`, `typecheck`, `guard_layering`, `guard_exports` and
      `test_all` green
- [x] 8.5 Update `docs/failure-modes-backlog.md`: FM-10 is built, and what it
      added beyond the scenario
- [x] 8.6 Update `docs/spec-and-architecture.md` as a specification - the
      third mitigation and the new mode described as though always intended
