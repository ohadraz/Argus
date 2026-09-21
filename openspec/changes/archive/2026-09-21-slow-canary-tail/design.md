## Context

The shop already composes per-request latency when a cache is configured: each
request takes the cached path or the recomputed one, the minute's quantiles are
real percentiles over that mixture, and `_the_quantile_at` reads them off by
nearest rank over a 200-request sample. That machinery is what this scenario is
built out of - a third path, reached by a small share of the sample, whose cost
is drawn from the shopper rather than decided in advance.

Argus reads four series: the error rate, the median, the p95 and the heap. A
fault reaching three requests in a hundred is below the 95th percentile by
arithmetic, does not fail, and allocates nothing. So the detector currently
finds no onset in this window at all, and the incident does not exist as far as
Argus is concerned. That is the gap, and it is the only gap: what to *do* about
a flag somebody moved has been settled since the first scenario.

## Goals / Non-Goals

**Goals:**
- A p99 on every bucket, with a baseline visible before the onset, so departure
  in the tail is a judgement against the service's own spread rather than
  against a number somebody picked.
- A scenario whose p50, p95, error rate and heap are all flat across the onset,
  and whose p99 moves unmistakably - and which holds that claim every minute,
  not most minutes.
- Reuse of the flag revert end to end: the same mode, the same strategy, the
  same undo, the same recovery verdict.

**Non-Goals:**
- A new failure mode or a new mitigation. FM-06 is a detection gap; treating it
  as a mitigation gap would be inventing an action to justify a scenario.
- Modelling the quadratic walk's cost by executing it. The generator models
  every cost it reports; running the slow path 200 times a minute across a
  90-minute window is the thing `_SAMPLE_SIZE` exists to avoid.
- Per-request latency for the scenarios that do not have a cache. They keep the
  baseline quantile model and gain a baseline tail alongside it.

## Decisions

### The cohort is an exact count of the minute's sample, not a per-request draw

Every other condition in the generator is a share drawn against per-request
entropy. This one is a count, `round(share × sample × how much of the minute the
rollout was live for)`, and the reason is arithmetic rather than taste.

With `_SAMPLE_SIZE = 200` and a 3% rollout, a binomial draw has a mean of 6 and
a standard deviation of 2.4. The p95 sits at index 189 and tolerates at most ten
slow requests; the p99 sits at index 197 and needs at least three. About four
minutes in a hundred draw eleven or more and show the incident in the p95, and
about six in a hundred draw two or fewer and hide it from the p99. A scenario
whose entire claim is *the p95 never sees this* cannot be wrong about it one
minute in twenty-five.

The precedent is already here: `_with_the_allocations_that_failed` computes
`round(_FAILING_SHARE * _SAMPLE_SIZE)` and does not draw. A percentage rollout
in a real provider buckets by user hash rather than flipping a coin per request,
so an exact share is also the more faithful of the two.

*Alternative considered:* raise `_SAMPLE_SIZE` until the binomial noise fits
inside the band. It would have to roughly quadruple, which quadruples the cost
of every `/metrics` read in every scenario to fix one.

### The cost comes from the shopper's history, not from a constant

The slow path re-walks the purchase history once per item, so its cost is the
ordinary recompute multiplied by the number of items - `_RECOMPUTED_PAGE_MS ×
len(purchases)`, over the 1-12 items `_an_account` already draws. That gives the
cohort a real internal spread of 190ms to 2280ms, which is what a tail is: not
"3% of requests are slow" but "the slowest requests belong to the heaviest
accounts".

It also makes the p99 robust from below. The 99th percentile of the minute is
the fourth-smallest of the six canary pages; even a minute whose six canary
shoppers all bought one or two items reports a p99 at twice the baseline, and a
typical minute reports seven or eight times it.

### The scenario stages a healthy cache

Per-request latency is composed only when a cache endpoint is configured -
`_what_the_page_cost` returns `None` otherwise, and the minute falls back to the
baseline quantile model, which has no mixture for a percentile to be taken over.
So this scenario configures the cache at the port it actually listens on, with
no outage: `the_working_cache_endpoint()`, lifted out of
`roll_the_configuration_back`, which has been constructing exactly that value
inline.

This is not incidental. A 90% hit ratio puts the p95 on a recomputed page at
~190ms, and *that* is the mechanism by which the p95 stays flat: the slow cohort
displaces nothing below index 194, and index 189 was a recomputed page before
the rollout and is a recomputed page after it. The two tail scenarios are now
mirror images built from one mechanism - the cache misconfiguration hides in the
tail because the tail was already a miss, and the slow rollout hides in the p95
for the same reason.

### `p99_ms` is required, not nullable

Unlike `cache_hit_ratio`, there is no service that has no tail. A nullable field
would invite a reader to treat its absence as meaningful, and nothing about a
deployment makes the 99th percentile inapplicable the way having no cache makes
a hit ratio inapplicable.

Scenarios without a cache get `_BASELINE_P99_MS` with the tail's own wobble
fraction, multiplied by the pressure curve and added to the provider wait
exactly as the p95 is. Their p99 therefore departs whenever their p95 does,
which is what leaves every existing scenario reading as it did.

### The alert fires on the tail

`_WHAT_FIRED` gains an entry: `HighLatency`, "p99 latency above threshold for
5m". The summary is the scenario's thesis stated by the monitoring itself - a
rule written against p95, which is how most latency alerting is written, never
fires here at all, and the responder is being told which percentile to look at
because no other one moved.

## Risks / Trade-offs

**The p99's own baseline noise could read as a departure.** → The tail wobbles
by the larger of the two fractions already (`_TAIL_WOBBLE_AS_FRACTION_OF_BASELINE
= 0.04`), and in composed minutes the p99 is the 197th of 200 sorted draws,
which is noisier than the p95. Mitigated by the same thing that mitigates it for
every other series: the spread is read off the window's own quiet stretch, so a
noisier series gets a wider bar. To be confirmed against a generated window
before the scenario is wired up, not assumed.

**A fifth flag scenario.** → Accepted. The other four are all about the error
rate; this is the first where the flag does not break anything, and it costs no
mitigation work precisely because the lever is one Argus already has.

**Adding a field to `MetricBucket` widens the model's prompt.** → The metrics
tool dumps the whole bucket, so the tail reaches the model for free and every
existing recording still replays: the double serves recordings in sequence by
name, not by matching the request. Only the new case needs recording.

**The exact-count cohort is a second mechanism in a generator that draws.** → It
is a third, not a second - the failing allocations already work this way - and
the reason is written down where the constant is, which is the standing rule for
a number this load-bearing.
