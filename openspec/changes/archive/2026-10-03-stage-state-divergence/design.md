## Context

FM-31 state divergence is foundational integrity's last unbuilt member. The
published taxonomy gives it one sentence - *distributed system components fall out
of sync; caches, replicas or stateful services hold inconsistent views of the same
data* - 196 incidents, and no example. Every other mode in
`docs/failure-modes-backlog.md` inherited a described shape; this one does not, so
the staging is a design decision rather than a transcription.

Four things in the estate constrain it.

**Argus reads generic signals only.** Every retrieval channel is something a service
exposes for its own reasons: a Prometheus endpoint, application logs, a flag
provider's API, Argo CD's API, GitHub, a service register. Nothing is published for
Argus's benefit, and a staging that needed a bespoke endpoint or a bespoke series
would only work against a service built to be watched by Argus. A stale cache moves
none of the generic signals - not the error rate, not a quantile, not CPU, not the
replica count.

**There is no cache in the stack.** `docker-compose.yml` runs no Redis. The summary
cache is arithmetic in the generator and a flag (`CacheOutage`) in the state, and
the healthy cache answers every shopper with one constant string. That is enough for
the three scenarios whose subject is a cache's *latency* and nothing at all for one
whose subject is what a cache *holds*.

**The shop has no cache write path.** `LookUpSummary` is `Callable[[str],
CacheAnswer]` - read-only, with no invalidation and no write-back - and purchases are
not recorded events: `the_accounts_the_check_examines` derives them from a fixed grid
as of the instant it is asked. There is no moment at which the shop records a
purchase, so there is nothing to hang an invalidation on.

**A flat window currently reads as recovered.** `has_recovered_since` says so in its
own docstring: "a window with no departure in it has no incident to have recovered
from, and every minute in it counts as recovered - which is the right answer for the
only caller, since Mitigation asks this of a window it reached by way of an onset."
Every acting mode has a measured onset, so the assumption has held. Silent data
corruption has a stated onset and a flat window, and never exposed it, because it
declines to act.

## Goals / Non-Goals

**Goals:**

- Stage state divergence as a promoted stale replica: replication broke three hours
  ago unnoticed, the primary died, the standby was promoted, and the cache now
  serves figures the ledger has moved past.
- Keep every retrieval channel generic. Detection arrives as the shop's own business
  alert, which is what any shop running a data-integrity job already sends.
- Add the sixth generic mitigation: discard the entries the evidence named, via
  one call to the store that holds them.
- Confirm the attempt from the action's own count, and end the incident `MITIGATED`.
- Close the flat-window hole, so an action with no receipt cannot be confirmed by a
  window that never departed.

**Non-Goals:**

- A new incident status. "Acted, outcome unverified" is not needed: the incident *is*
  a stale copy, and removing the copy leaves nothing to verify.
- Repairing anything in the shop's data. Nothing in it is wrong.
- Re-asking the monitoring stack, or asking the shop anything it does not already
  publish.
- A `FLUSHDB`, a key pattern, or any discard whose scope Argus chose.
- Replacing the other scenarios' computed cache with a real one.
- Giving the shop a cache write path, an invalidation or a recorded-purchase event.
- A structured action-items field on the postmortem. The lasting fix - the cache's
  replication - reaches the postmortem as prose, which is what the postmortem is.

## Decisions

### The staging is a promoted stale replica, and the lag is three hours

Replication to the standby broke and nobody noticed, because nothing reads a
standby. The primary then died and the behind copy was promoted. That is a pure
state fault with a real onset and nothing in any change channel, which is what the
taxonomy describes and what no built scenario stages.

Three hours, and the number is a mitigation decision rather than an arithmetic one.
The shop's grid takes an order every two minutes across 240 accounts
(`SOMEBODY_BUYS_EVERY`), so the stale count is the lag in minutes over two, capped
at every account once the lag passes eight hours. At three hours that is 90 of 240.
At a week it saturates: every account has bought, every cached figure is stale, and
discarding the named set and emptying the store then remove *the same entries* - which
makes the central decision below a distinction without a difference. At three hours
a wider discard would be touching 150 entries nothing proved wrong, and the decision
has teeth.

Checkability is not the reason. A saturated cache is still checkable, against the
gap rather than the count - each entry would be missing `lag / 480` purchases. What a
week costs is the named set, and a second thing: "every cached figure disagrees" also
reads as a cache that is misconfigured or empty, which makes the separation from
silent data corruption harder to assert rather than easier.

*Alternatives considered.* A flag that switches off an invalidation on the write
path: rejected, because it is `silent-data-corruption`'s staging with a different
store and the flag history would carry the answer. Per-replica in-process memos
cleared by a restart: rejected, because it buys no new action, and the existing
mitigations stop being a set of near-misses.

### The divergence grows, and the key list is a snapshot

The fixture has no write path, so nothing can rewrite an entry and nothing can
invalidate one. What the scenario seeds is the figure each active account's entry
held at the minute replication broke; the ledger moves on and the entries do not.

The seam stays read-only, with no write-back on a miss, even though
`cached_summary`'s fallback describes a cache that would repopulate. A write-back
would refill a discarded key between the discard and the read-back - with a correct
value, so the receipt would stay honest, but an assertion that the entry is gone
would flake. So **the discard is permanent for the run**, which is what makes the
end-to-end claim assertable: the count, and the absence, are both safe to assert.

A trap in the fixture is worth recording here, because it nearly produced a
scenario with no incident in it. Staging the stale figures by asking the shop what
its check *would have found* three hours ago gives 2 stale accounts out of 240
rather than 90. An account is derived over a reach-back window that slides with
the instant asked for, and its prices come from a sequence seeded on the shopper -
so a window that drops its oldest purchase and gains a newer one returns the
identical total. The monthly figure is very nearly time-invariant, and **the same
question asked earlier is not the figure from earlier.** What is staged instead is
each shopper's real purchase list truncated at the break, which gives exactly the
lag over the order cadence, holds across instants, and is the more honest model of
a frozen copy. Anything else that reasons about "the shop as it was at time T"
meets the same trap.

The consequence is that the stale set is **not closed**: an account diverges as soon
as it buys after the lag began, so time keeps adding accounts at one every two
minutes until all 240 are stale at the eight-hour mark. That is accepted rather than
engineered around - it is what a promoted stale replica actually does, and building a
write path to make it look tidier would be fixture machinery in service of a
presentation.

Two things follow, and both are improvements. The alert's key list is explicitly a
**snapshot at check time**, which the payload contract has to say. And the mode's
ending is the one the set already knows best: **this is the leak's shape in a data
store.** A restart reclaims the heap and the heap starts filling again; a discard
clears the stale entries and time starts adding them again. What closes the set is
the lasting fix, in the cache's operation rather than in the shop.

### Detection is the shop's own alert, and the alert carries the keys

The shop runs a data-integrity job already - it is what finds silent data corruption.
Here it asks a second question: does what the cache holds agree with the purchases
behind it. An alert is a generic surface; every monitoring stack receives them from
arbitrary sources, and a shop paging on its own reconciliation is ordinary.

The keys travel in the alert because the job addressed the cache to compare it, so it
already holds them, and because a key format is the shop's own. The alternative -
Argus composing keys from a configured template - was rejected on the rule every
strategy already follows: a subject comes from the record, never from Argus's
configuration.

The payload carries how many entries disagree and out of how many were checked (a
count alone is meaningless: 90 of 240 and 90 of 90 are opposite incidents, which
`Reconciliation` already gets right), the widest gap in cents, the item-count
discrepancy, the keys, and the onset. **The key list's length must equal the
disagreeing count, and both halves assert it** - two fields that check each other,
so a list that arrived truncated fails loudly instead of reading as a smaller
incident, which is the exact failure a payload of exact strings has.

`SummaryEntry` carries `items_counted` beside `amount_cents`, so a stale entry
diverges in two fields and the page contradicts itself in two places. That also
sharpens the separation from silent data corruption in the evidence rather than only
in the prose: there the amount is wrong and the count is not.

*Rejected outright, after being proposed and argued down:* a `GET /integrity-check`
endpoint, and a `cached_summaries_stale` gauge on `/metrics`. Both work, and both
require the service to have been built for Argus. The endpoint is a bespoke API; the
gauge is a bespoke series. Neither is something a shop publishes for its own
reasons.

### The incident has two dates, and the onset is the promotion

The onset is the minute the standby was promoted, because that is when customers
began seeing wrong figures. The oldest purchase missing from a stale entry dates
something else - when replication broke - and the two are three hours apart. A
reader who takes the older date for the onset dates the incident from before anybody
could have seen it, and would then look for a cause in minutes where nothing was
wrong.

The promotion has corroboration in a channel Argus already reads: the shop's own log
carries the reconnection to a new primary. So the onset is not merely stated, and
the older date is evidence about the lag rather than about the incident - which is a
distinction worth staging, because no built scenario has two dates to confuse.

### The action discards the named keys and never empties the store

Redis spells it `UNLINK key [key ...]`, standard since 4.0: variadic, O(1) per key with the
memory reclaimed on another thread, ignores keys that are not there, and returns the
number removed. One call carries every key.

`FLUSHDB` is rejected on one ground, not two. The finding named a set of entries, so
a wider discard is a change Argus has no evidence for. The second ground the design
first gave - that discarding the cache entire would send every page back to walking
the purchase history, the latency incident `cache-misconfigured` describes - does not
survive the fixture's scale, where that is 240 pages. It is dropped rather than
softened. `DEL` is rejected because it blocks the server for the duration.

### The receipt is the confirmation, and nothing else can answer

The discard's count is the store stating which of the named keys existed and are now
gone. No read-back follows: a `GET` is the same server answering about the same keys,
and the restart's follow-up read of a pod's `createdAt` exists only because
Kubernetes performs a restart asynchronously and the platform's 200 is an
acknowledgement rather than a statement.

The stronger finding is that the receipt is not the *chosen* confirmation but the
**only** one available, and the search for a generic alternative closes cleanly. The
only generic channel that can see cache staleness is the shop's own integrity job,
and its cadence is precisely what made silent data corruption decline to act -
re-asking it means waiting on the next scheduled run to learn whether you fixed
anything. Logs are no better: a miss-and-recompute line says a key is gone, which is
what the discard already said from the same store, and it waits on a shopper arriving.

A second reading was also dropped for its own reason: the natural read-back is the
recomputed figure, and nothing repopulates an entry except a request for that
shopper. A quiet shopper's entry stays absent for hours, so waiting on the figure
would be waiting on traffic Argus does not control.

### What the receipt establishes is enough, and the status is `MITIGATED`

The incident is "the cache holds a value the ledger has moved past". Remove the value
and there is no divergence left to measure - an absent entry sends the page to the
ledger, and that behaviour is designed and load-bearing (`summary_cache`'s own
docstring: a cache that holds nothing and a cache that cannot be reached both end
with the page working the figure out for itself).

`MITIGATED` rather than `RESOLVED`, and the reason is structural rather than
circumstantial. `IncidentStatus.RESOLVED` is defined as the permanent fix being
merged, and states that Argus does not reach it on its own by construction (§13). No
mitigation Argus takes lands there. What remains here is a recurrence path, not a
refill one: nothing upstream is pushing stale values into a promoted primary, and
what is untouched is that a cache which can promote a lagging replica will do it
again.

### A flat window may no longer confirm an action that reports nothing

Two rules exist for judging an attempt: levels falling back towards a baseline, and -
for the blind spot - readings existing again. This change adds a third, the action's
own report, and closes the gap the first one leaves. Where the onset was stated, the
window is flat throughout, and the action reports nothing about what it changed, the
attempt is unconfirmed and the walk tries its next candidate.

Without that, a walk reading this incident as a resource leak restarts the shop, reads
a window that never departed, and closes the incident `MITIGATED` with every page
still wrong. That is the one outcome worse than escalating.

**It is asked as a third sibling predicate over the window, not as a widened return
type and not as a rule the caller is trusted to remember.** `anomaly.py` has already
answered this exact question once: `has_a_reading_since` exists because "a `False`
from `has_recovered_since` covers two states that mean opposite things - the service
was watched and has not come back, or nobody watched it", and the answer chosen was a
separate honest predicate asked first, sharing `_first_index_at_or_after` so the two
cannot disagree about which minutes count. The same mechanism applies here: whether
the window holds a departure to have recovered *from* is a question about the window
alone, needing no onset provenance and no action kinds.

Two alternatives were argued and dropped. A tri-state return from
`has_recovered_since`: rejected because it would be a second mechanism for one class
of defect in one file, where the first is already written down and reasoned for. The
judgement inside `has_recovered_since` itself: rejected because the predicate would
have to know the onset's provenance and the action's kind, pulling the mitigation
layer's vocabulary into a metrics module. The defect was never that the predicate
lies - it is that its precondition is documented, unenforced and *unaskable*, and a
sibling makes it askable.

Whether an action reports what it changed is declared with the action's kind, beside
the declaration of whether it may be taken unasked. The gate judges before anything
is performed, so there is no answer to inspect when the question is asked.

### The keys reach the record and never a prompt

They arrive at the strategy as a parameter, in the same shape `flag_changes` arrives -
evidence passed in, selected from, not composed. They are deliberately not carried on
the hypothesis: `faulting_service` is the precedent for an address on a conclusion and
it is one short string copied from a register, where a list of exact keys routed
through a model's conclusion arrives abbreviated, elided or invented.

They are also never rendered to the model at all. The model needs to know that cached
figures disagree, by how much, and over how many purchases - not which keys they are -
and a list of addresses re-rendered on every round of a walk is real token spend for
no decision it informs. This is a requirement rather than a note, because a later
change that helpfully included them would be invisible.

### A real Redis, seeded by this scenario alone

Argus speaks the real protocol, so there must be something real to speak it to. A
`redis:7-alpine` in the compose stack is cheaper and more honest than a Redis double.

It is reached through the seam a cache is already reached through rather than by
changing it: `_the_cache_answering` already returns `None` "where the deployment
configured no cache at all, which is what every scenario staged before there was one
looks like", so handing one scenario a different `LookUpSummary` is the existing
shape rather than a new branch. `summary_cache.py` is untouched. The guarantee that
no other scenario moves is better than comparing windows afterwards: that function
takes two entropy draws unconditionally and in order, specifically so that a request
skipping the cache cannot shift the sequence for the requests after it. Hold both
draws in the same order and every other scenario is identical by construction.

### Shared fixture vocabulary cannot live in a file the fix corpus patches

The key's spelling belongs beside the cache's other formats, in
`io_shop/summary_cache.py`, and cannot go there: **three recorded fixes in the
grading corpus replace that file wholesale.** A constant added to it disappears
whenever one of those patches is applied, and anything importing it then fails
during `grade_fixes` for a reason that has nothing to do with the fix being
graded.

So it lives in `target_app/cache_entries.py`, which no patch has touched. The rule
is general and worth stating once rather than rediscovering: before putting shared
vocabulary in a demo-app module, check whether that module is a patch target in
`tests/eval`'s corpus. Nothing in the file itself says that it is.

The key is `io-shop:summary:{shopper_id}` and carries **no period** - not
`...:2026-10`. A key naming the month stops matching the staged entries at
midnight on the first, and the staged-write, read-back and discard-by-alert chain
would break mid-run for a reason visible in neither repository. The current
month's figure sits under the shopper and is replaced, which is what a
time-to-live would do - and a time-to-live is the lasting fix this mode already
names.

### Argus asserts no figure the fixture chose

A test in the Argus repo asserts what Argus did, never what the demo app handed it.
Where a count matters it is asserted as a relation between two things Argus holds -
the count the action reports equals the count the evidence named - and never as an
absolute. The fixture is setup; in principle Argus would have told it what to stage,
and fixed scenarios exist only because the two are separate projects and processes.

This is why the length-equals-count cross-check is the right shape: it is internal to
the payload, so Argus can hold it without knowing a single fixture figure.

## Risks / Trade-offs

**A new container in the e2e stack, and five host processes already outlive `compose
down`.** → Redis joins the ports a run has to find free. The teardown and the
pre-run port check both have to know about it, or the next run fails for a reason
that looks like this change and is not.

**The write tier gains a dependency on a datastore client.** → Confined to one
module behind one seam, in the shape `restarting.py` and `scaling.py` already have:
an endpoint from settings, a call, and a failure that names what it dialled.

**A tool that deletes is a tool a model can point anywhere.** → The schema takes a
list of keys and nothing that can match a key it was not given - no pattern, no
service, no prefix. The handler rejects anything else, because a schema is a request
and correctness is the handler's job.

**The discard is irreversible in the narrow sense.** → It is, and nothing is lost:
the authority it derived from is untouched and the service rebuilds on demand. The
risk that remains is a *wrong* discard - keys from a hypothesis that misread the
incident - bounded by the keys coming from the evidence rather than from the model.

**The third confirmation rule could be read as a weaker standard.** → The record says
which rule settled an attempt, so a receipt-confirmed attempt cannot be mistaken for
a service observed getting better.

**The incident is mitigated while the divergence is still growing.** → True, and it is
the leak's position exactly. Nothing claims otherwise: the entries the evidence named
are gone, the record says the key list was a snapshot, and what closes the set is the
lasting fix.

**Two modes in this family now hinge on the same alert.** → Deliberate, and it is the
pair's value: both arrive as "N things disagree with the purchases", and what
separates them is which copy disagrees - plus, now, whether the item count diverges
too. An eval case is owed for the separation, because a reader who confuses them
reaches an action that repairs nothing.

**`anomaly.py` grows a third predicate over one window.** → Additive, sharing the
existing index helper so the three cannot disagree about which minutes count.
`has_recovered_since` keeps its signature and its docstring.

## Migration Plan

The schema chain gains nothing; no table changes. The order that matters is the
stack's: Redis before the shop, as postgres already is.

Recordings are keyed by scenario name, so nothing existing needs re-recording. This
scenario needs its own under both `grep` and `both` prefixes before CI's replay can
collect it, and until those exist the e2e case is uncollected rather than skipped -
the same treatment the index cases get under `grep`.

## Open Questions

Both of the design's original open questions are settled: the lag is three hours
(90 of 240 stale), and the demo app's own suite covers the comparison, which is its
own safety net and nothing in Argus depends on it.
