## Why

FM-31 state divergence is the last unbuilt member of foundational integrity, the
family that carries 12% of real incidents. The taxonomy describes it in one
sentence - *caches, replicas or stateful services hold inconsistent views of the
same data* - and gives it no example, so nothing about the staging is inherited.

It is worth building for what it settles rather than for the share it adds. Every
mode Argus acts on today has a **measured** onset: a series departed, and the same
departure rule that found the incident judges whether the mitigation ended it.
The two modes with a **stated** onset - silent data corruption and this one - have
a window that is flat from end to end, and `has_recovered_since` counts every
minute of a window with no departure as recovered. So the first alert-only mode
that acts gets its action confirmed on the first poll, whatever the action was: a
restart that touched nothing would be reported `MITIGATED` with every page still
wrong. Silent data corruption never exposed that, because it declines to act.

State divergence is the one mode that cannot decline. Its action is a complete fix
that Argus can prove it performed - the stale entries are discarded and the shop
rebuilds them from data that never moved - so `RECOMMENDED` would be Argus
withholding an answer it has. That forces the rule the flat window has been owed:
where the onset was stated rather than measured, only an action carrying its own
receipt may be confirmed, and everything else is unconfirmed.

## What Changes

- **A twelfth generated scenario, `cache-failed-over`.** Replication to the summary
  cache's standby broke three hours ago and nobody noticed, because nothing reads a
  standby. Then the primary died and the standby was promoted, so the cache now
  serves figures the purchase ledger has moved past. An account page shows a
  monthly total - and a count of the purchases behind it - that disagree with the
  purchases printed beside them. Nothing fails, nothing waits, nothing accumulates,
  no flag moved and no revision went out.
- **An incident with two dates, which is new.** The onset is the promotion, because
  that is when customers began seeing wrong figures. The oldest purchase missing
  from a stale entry dates something else entirely - when replication broke - and
  the two are hours apart. A reader who takes the older date for the onset is
  dating the incident from before anybody could have seen it. The promotion has
  honest corroboration in a channel Argus already reads: the shop's own log carries
  the reconnection to a new primary.
- **A `state-divergence` failure mode**, with the meaning text that separates it
  from the two modes it arrives alongside: silent data corruption, where the
  authoritative copy is the wrong one, and the in-flight compatibility break,
  where two sides disagree about the *shape* and the page fails.
- **A sixth generic mitigation: discard the stale entries the evidence named.**
  One call naming them all, non-blocking, and answering with the number of keys it
  removed. Not `FLUSHDB`, and on one ground rather than two: the finding
  named a set of entries, so a wider discard is a change Argus has no evidence for
  and cannot account for. Entries nothing proved wrong are left alone.
- **A receipt as a verdict, and it is the only verdict available.** The discard
  answers with how many of the named keys it removed, which is the server stating
  they are gone. Nothing else can answer: the only channel that sees cache
  staleness at all is the shop's own integrity job, and waiting on its next
  scheduled run is precisely what made silent data corruption decline to act. So
  the receipt is not the preferred confirmation but the sole one, which is a
  stronger claim than the design first made.
- **Mitigated, never resolved, in the shape a leak already has.** A restart
  reclaims the heap and the heap starts filling again; a discard clears the stale
  entries and time starts adding them again, because a promoted stale replica goes
  on diverging. The alert's key list is therefore a snapshot at check time, and
  what closes the set is the lasting fix - a TTL, or refusing to promote a replica
  that is behind - which lives in the cache's own operation and not in the shop.
- **The confirmation rule a stated onset has been owed.** Where the onset was
  stated rather than measured, an action with no receipt may not be confirmed by a
  flat window. A restart taken against this incident is therefore refuted and the
  walk tries its next candidate, instead of closing as mitigated. Asked as a third
  predicate over the window - whether it holds a departure to have recovered from -
  beside the two that already share their arithmetic.
- **A real Redis in the stack.** There is none today: the cache is arithmetic in
  the generator, and `CacheOutage` is a flag. Argus speaks the real protocol to a
  real `redis:7-alpine`, seeded by this scenario alone through the seam a cache is
  already reached by, so no existing scenario's arithmetic changes.
- **The stale keys travel as data, into the record and never into a prompt.** A
  hypothesis is prose, and a list of exact strings routed through prose arrives
  abbreviated. They are also never rendered to the model at all: the model needs to
  know that cached figures disagree and by how much, not which keys they are, and
  rendering them would bill a list of addresses on every round of a walk.

## Capabilities

### New Capabilities
- `state-divergence-scenario`: the staged failover - what the cache serves, how
  many shoppers read stale, what the alert carries, and what the shop goes on
  doing correctly throughout.
- `cache-entry-discard-mitigation`: the sixth generic mitigation. Which entries
  are discarded, where their keys come from, why the set is named rather than
  flushed, and what admits it unasked.
- `redis-cache-adapter`: the write tier's Redis seam - the vendor's own command over
  the real protocol, the count it returns, and the failures a caller has to tell apart.
- `receipt-confirmed-mitigation`: a verdict read off the action's own answer
  rather than off the service's window, and when that is the only honest judge.

### Modified Capabilities
- `generic-mitigation-tier`: the declared set gains a sixth member, and with it
  the first action whose undo puts nothing back - because nothing was lost.
- `write-mcp-server`: a tool for discarding named cache entries, and the first
  that reaches a datastore rather than a control plane.
- `unverifiable-action-recommendation`: `RECOMMENDED` is for an action nothing can
  judge. An action that reports what it changed is judged by that report, so the
  status narrows to the actions that genuinely cannot answer for themselves.
- `incident-withdrawal`: withdrawing a discard puts nothing back, and says so.

## Impact

- `modules/argus_core`: `FailureMode.STATE_DIVERGENCE` and its meaning text; the
  action and its undo descriptor; the alert's new field; the recovery rule in
  `anomaly.py` that currently reads a flat window as recovered.
- `modules/agent_mitigation`: the strategy, its place in `DEFAULT_STRATEGIES` and
  in `GENERIC_MITIGATIONS`, the keys reaching `propose`, and the verdict path in
  `trying.py`.
- `modules/write_mcp_server`, `modules/write_mcp_client`: the tool and its typed
  function.
- `modules/argus_narration`: a line for the new action and its withdrawal.
- `Argus-Demo-Target-App`: the scenario, the failover, the stale share, the alert,
  and the shop writing real cache entries for this scenario.
- `docker-compose.yml`: Redis.
- `docs/failure-modes-backlog.md`, `docs/spec-and-architecture.md`: the family
  covered entire.
- e2e recordings under both `grep` and `both` prefixes; eval cases separating this
  mode from silent data corruption.
