## Why

Change-induced failure is the largest family of real incidents (31%), and its
config half - FM-10, a non-code change breaking a service that nobody edited -
is the one Argus has never staged. Every scenario built so far moves the error
rate. This one does not: the shop keeps serving correct pages and merely gets
slow, which is the incident error-rate alerting never fires on and the case that
says whether Argus reads latency at all.

It also buys the first mitigation that is neither a toggle nor a restart. A
config revision rolled back is a real, reversible platform operation that leaves
the fault in git - mitigating without resolving, exactly as restarting a leaking
process does, reached from a different direction.

## What Changes

**The Target Service gains a cache, and a way to lose it.**

- Io's account page caches the rendered spend summary and recomputes on a miss.
  The fallback is correct and slow, which is why nothing fails.
- The cache endpoint is read from deployment config. A config deploy moves its
  port, so every lookup fails to connect, every page recomputes, and latency
  climbs while the error rate stays at baseline and memory stays flat.
- The endpoint's port lives in `deploy/values-production.yaml` in the Target
  Service's own repository and is changed by a real commit, so what Argus reads
  when it asks "what changed" is a diff rather than an assertion.
- The hit ratio is set so that **the tail does not show the incident**: `p95`
  already describes a recomputed request before the onset and describes one
  after it, while `p50` steps twenty-fold. The aggregate Argus watches most
  confidently is the one that misses this.
- A new metric, `cache_hit_ratio`, is reported on every minute of every
  scenario - not only the ones about caching, for the reason memory is.
- The scenario is **generated**, not authored, and is the first generated
  scenario that has a deploy: the Argo CD stand-in currently short-circuits
  every generated scenario to an empty revision history, and that branch opens.

**Argus gains a third mitigation: roll the config revision back.**

- A new `FailureMode.CONFIG_INDUCED_FAILURE`, and a strategy answering it.
- A new write-tier tool performing Argo CD's own rollback operation, which
  re-syncs the application to a previously-deployed revision without touching
  git. Its undo descriptor is the revision it was rolled back *from*.
- Automated sync is disabled before the rollback and is part of what the undo
  puts back, because a real Argo CD refuses a rollback while auto-sync is on and
  will re-sync to the bad revision the moment it is re-enabled.
- The incident is therefore **mitigated and not resolved**: git still holds the
  wrong port, and what ends it is a one-line change to the values file - the
  first time Code-Fix proposes a change to config rather than to source.

## Capabilities

### New Capabilities
- `cache-misconfiguration-scenario`: the config-induced scenario the Target
  Service stages - a real cache seam in its own source, a port read from
  deployment config, telemetry computed from whether the endpoint is reachable,
  a config deploy recorded in the revision history, and the values file whose
  diff names the change.
- `config-rollback-mitigation`: rolling a deployment's configuration back to a
  previously-deployed revision as a mitigation Argus may take unasked -
  performed through the platform's own rollback operation, recorded with the
  revision it left so the change can be put back, and treated as having
  mitigated the incident without resolving the cause.

### Modified Capabilities
- `generic-mitigation-tier`: the closed set of generic mitigations gains the
  config rollback, and with it the first admitted action whose undo restores two
  things rather than one.
- `argo-deploy-adapter`: the revision history read from an Argo CD-shaped API
  gains the application's automated-sync state, which the rollback has to read
  before it may act.
- `resource-metrics`: a metric bucket gains `cache_hit_ratio`, reported on every
  minute whether or not a scenario is about caching.
- `trend-onset-detection`: departure is currently judged on error rate, p95 and
  memory. The median joins them, because this incident is invisible in the tail
  by construction - and each quantile is judged against its own spread rather
  than a shared absolute bar.

## Impact

- **`Argus-Demo-Target-App`**: a new `io_shop/summary_cache.py` seam and its use
  in `account_page`; a `CacheEndpoint` condition in `generator.py` beside
  `ProviderOutage`; a `cache_hit_ratio` field on the generated minute; a new
  scenario in `scenarios.py`; a `POST /argocd/{application}/rollback` route and
  an automated-sync field on the Argo CD stand-in; `deploy/values-production.yaml`
  and the commit that changes it.
- **`argus_core`**: a new `FailureMode` value, a new action type and its undo
  descriptor, a `cache_hit_ratio` field on `MetricBucket`, and `p50_ms` joining
  the signals `anomaly` judges departure and recovery on.
- **`agent_mitigation`**: a strategy for the new mode, registered in
  `DEFAULT_STRATEGIES`.
- **`write_mcp_server` / `write_mcp_client`**: the rollback tool and its typed
  client function.
- **`read_mcp_server`**: the automated-sync state on the Argo CD adapter.
- **No infrastructure change.** No Kubernetes, no Argo CD installation, no Redis
  container, no new repository. The cache is a callable seam and the platform is
  the stand-in the Target Service already serves.
