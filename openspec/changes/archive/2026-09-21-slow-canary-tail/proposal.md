## Why

Every aggregate Argus reads is an average of a kind, and an incident that lives
in the tail is one an average is built to hide. The last scenario proved the
mirror of this - a cache lost in the median while the tail never stirred - and
it left the obvious question unasked: the shop reports a 50th and a 95th
percentile, and a fault reaching three requests in a hundred is below both of
them by construction. Argus would currently read four flat series and find no
onset at all.

FM-06 is the taxonomy's name for that, 3% of real incidents, and it is the
cheapest scenario left to build: what answers it already exists. A slow rollout
is a flag somebody moved, and putting a flag back is the first mitigation Argus
ever had. Nothing new is admitted, nothing new is undone. The whole of this
change is whether Argus can *see* it.

## What Changes

**The service reports a 99th percentile, and Argus judges on it.**

- `MetricBucket` gains `p99_ms`, reported on every minute of every scenario for
  the reason memory and the hit ratio are - a field that appeared only when it
  mattered would be a signal read by its presence, and a tail nobody can see a
  baseline for is not a tail anybody can call elevated.
- The tail joins the error rate, the median, the p95 and the heap as a series
  `anomaly` judges departure and recovery on. Without it this incident has no
  onset, and with it every other scenario is unchanged - a p99 that tracks its
  p95 departs exactly when the p95 does.

**The Target Service stages a rollout that is slow rather than broken.**

- A second rendering path in `io_shop`: a per-item spend breakdown that is
  correct on every input and re-walks the shopper's history once per item. Its
  cost is the ordinary recompute multiplied by how much the shopper has bought,
  so the pages it makes slow are the ones belonging to the shop's best
  customers - which is what a tail is.
- The rollout reaches **3% of traffic**, and that figure is the scenario. Above
  five in a hundred the p95 moves and the incident becomes ordinary; below one
  in a hundred the p99 cannot see it either and there is nothing to detect.
- The cohort is an exact count of the minute's sample rather than a per-request
  draw, as the failing allocations of a leak already are. At three in a hundred
  of two hundred requests a binomial draw lands outside the band that makes the
  scenario what it is about once every five minutes, and a fixture whose claim
  holds four minutes in five is not a fixture.
- The shop keeps its cache, healthy throughout, because that is what composes
  per-request latency into real percentiles - and it is what puts the p95 on a
  recomputed page, which is the mechanism by which the p95 does not move.
- The alert that fires names the tail: a rule written against p95 never fires on
  this, and one written against the error rate never fires either.

**Nothing is added to the mitigation side.** The mode is
`FEATURE_FLAG_TOGGLE`, the strategy is the flag revert, the undo is the flag's
previous state. The incident ends when the rollout is put back, and it is
mitigated *and* resolved - the first scenario since the flag ones where it is.

## Capabilities

### New Capabilities
- `slow-canary-scenario`: the tail-degradation scenario the Target Service
  stages - a real second rendering path in its own source, a rollout reaching an
  exact small share of each minute's traffic, a cost drawn from how much the
  shopper has bought, and telemetry in which only the 99th percentile moves.

### Modified Capabilities
- `resource-metrics`: a metric bucket gains `p99_ms`, reported on every minute
  whether or not a scenario is about the tail.
- `trend-onset-detection`: departure and recovery are judged on the error rate,
  the median, the p95 and the heap. The tail joins them, because this incident
  is invisible in all four by construction.

The dashboard's evidence table gains a tail column too, but it names no columns
at spec level, so that is implementation rather than a requirement change.

## Impact

- **`Argus-Demo-Target-App`**: a new `io_shop/spend_breakdown.py` rendering path
  and its use in `account_page`; a `SlowRollout` condition in `generator.py`
  beside `CacheOutage`; a `p99_ms` field on the generated minute and a baseline
  tail for every scenario that does not compose per-request latency; a new
  scenario in `scenarios.py`; a `the_working_cache_endpoint()` in `settings.py`;
  a p99 alert rule in `monitoring.py`.
- **`argus_core`**: `p99_ms` on `MetricBucket`, and the tail joining the signals
  `anomaly` judges departure and recovery on.
- **`argus_narration`**: `p99_ms` on `BucketRow`.
- **`argus_web`**: a tail column in `evidence.html`.
- **No mitigation change.** No new `FailureMode`, no new action type, no new
  undo descriptor, no new tool on either MCP tier, and no entry in
  `DEFAULT_STRATEGIES`. The scenario is answered by what is already there, which
  is the point of choosing it.
- **A recording set.** The new e2e case needs its own replay recordings under
  each `CODE_SEARCH` mode, which is the one step here that spends tokens.
