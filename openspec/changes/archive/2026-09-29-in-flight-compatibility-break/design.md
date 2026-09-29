## Context

Seven modes exist and five of the taxonomy's families are covered, two of them
entire. Tail/outlier has one half built - `slow-canary-rollout` for FM-06 - and
this is the other half.

The fixture already stages everything this needs except one thing. A deployment
is a real Argo CD application with a real revision history; the shop's replica
count is live state a write reaches; the platform stand-in serves the running
Deployment's manifest, which is how a scale-out learns the count it is about to
replace. What nothing in the estate can express today is a deployment that is
*part way there* - every deploy in the fixture is instantaneous, and the history
is a list of instants.

Three constraints shape the rest.

**A scenario has to have a live condition.** Telemetry that cannot react cannot
grade a mitigation, and every generated scenario here is a function of state
somebody can change.

**No minute may fall clear by accident.** A stretch since an action with one
clear minute and no two consecutive elevated ones reads as a confirmation, so a
scenario that lets up on its own confirms whatever was tried last.

**The wrong answers have to be wrong in the fixture, not in a rule.** A restart
has to change nothing here because nothing about the mixture is the process's
doing, not because something refuses to grade it.

## Goals / Non-Goals

**Goals:**

- A mode for an incident where both revisions are correct, and evidence that
  names it without naming a culprit commit.
- A channel that says whether a deployment converged, usable by every mode that
  has a deploy at its onset rather than only by this one.
- A scenario whose failing share is arithmetic a reader can check: the product of
  the share writing the new shape and the share unable to read it.
- The existing rollback answering it, with no new action, no new undo descriptor
  and no new member of the pre-authorised set.

**Non-Goals:**

- Rolling *forward* as a mitigation. See the rejected alternative below.
- Modelling a rollout that progresses. The rollout in this scenario is paused and
  stays paused; a fixture whose mixture drifted minute by minute would be a
  second flapping scenario with none of the first one's point.
- Any claim about what Code-Fix does here. As with `cpu-saturation`, the walk asks
  the code tier like any other mode and the agent answers from the repository in
  front of it. What the record holds is what it answered; nothing asserts it
  should have answered nothing.

## Decisions

### An eighth mode, though the action does not change

The mapping from modes to mitigations is already many-to-one, and
`failure_mode.py` says why: a value that had to earn its place by bringing a new
action with it would be a vocabulary serving the dispatch table instead of the
person reading the incident. This is the strongest case in the set for that rule
rather than an exception to it. A reader who calls this `bad-deployment` takes
the right action and writes a false record: a revision named as the fault, a fix
filed against code with no defect in it, and nothing said about the rollout that
was left half-done - which is the only thing that will happen again.

Alternative considered: no new value, and let the incident be recorded as
`bad-deployment`. Rejected because it makes the postmortem wrong by
construction, and the postmortem is the artefact this system exists to produce.

### The rollout state is read from the running Deployment, not from the history

Argo CD's revision history records that a sync happened. Whether the pods have
finished turning over is on the Deployment itself - `status.replicas`,
`status.updatedReplicas`, and `spec.paused` - which the platform stand-in already
serves at `GET /argocd/{application}/resource`, and which the write tier already
reads to learn the count it is replacing. So the channel reads the live resource
and reports four things: the revision being converged on, how many replicas have
reached it, how many have not, and whether the rolling update is paused.

Alternatives considered:

- **A new metric series** - a `replicas_at_target_revision` beside
  `cpu_limit_cores`. Rejected: the revision spread of a fleet is platform state,
  not a service measurement, and putting it in the bucket would make the detector
  date an onset from a deploy turning over, which is an ordinary event.
- **A field on the history entry** - `converged: bool`. Rejected: the history is
  what Argo CD reports about syncs that completed, and a flag bolted onto a past
  event would say nothing about how far the current one has got. It also makes
  the fact retrievable only for a deployment already in the history, which is the
  wrong precondition for asking whether a deployment finished.

### The rollout is paused, and the pause is the reason nothing converges

`kubectl rollout pause` is first-class and ordinary: somebody sent half the fleet
to the new revision to watch it, and went off shift. That gives the scenario a
live condition that does not drift, an honest explanation for why the estate does
not fix itself, and a fact the new channel can report in one word.

Alternative considered: a rollout stalled because the new replicas cannot be
scheduled. Rejected - it drags capacity into an incident that is not about
capacity, and the evidence would then support a saturation reading that the
fixture would have to argue with.

### The incompatibility is in the summary cache, and it is one-directional

The deployed revision changes the shape of what the summary cache stores. The new
side writes the new shape and reads only the new shape - which is the mistake
itself, an expand-contract migration with the expand step missing. The old side
cannot read a shape that did not exist when it was written.

So a page fails when a replica on the old side draws an entry a replica on the
new side wrote, and the failing share is the product of two shares: it is zero
before the rollout starts, zero once it finishes, and largest in the middle. At
half and half, with the cache carrying its usual nine lookups in ten, that is
about one request in five.

One direction rather than both, because both would double the rate and lose the
asymmetry that makes the diff readable: a reader looking at the commit sees a
writer that changed and a reader that was not taught the old shape, which is the
defect in the *process* stated in code.

### Both revisions pass their own tests, and the fixture proves it

`tests/io_shop` is green at the parent commit and green at the child. That is
what makes "no revision is at fault" a fact about the fixture rather than a claim
in a description, and it is what `grade_fixes` would find if anybody pointed it
here: there is no failing test for a patch to turn green.

### Rejected alternative: make the rollback wrong and converge forward instead

The sharper scenario is the one where the new side has already written the new
shape into something that outlives a rollback, so going back is refuted - every
replica then reads rows it cannot parse, and the only thing that ends the
incident is finishing the rollout. That version makes the diagnosis decide the
action, which is stronger than making it decide only the record.

It is rejected on spec §13. Completing a rollout has no undo: there is no
returning a fleet to half-deployed, and the revision is at every replica the
moment it converges. An action that cannot be put back may not be autonomous, so
the mode's answer would be to diagnose it and ask a human - which is FM-01's
ending reached at the cost of a sixth action kind, an undo descriptor that cannot
undo, a gate question about irreversibility and a narration for all of it. The
distinction it would buy - "Argus will not do what it cannot undo", beside the
two refusals the write tier already makes - is worth writing down and is not
worth that.

It is written down here rather than lost: if the irreversible-action question is
ever taken up on its own merits, this is the scenario that motivates it.

## Risks / Trade-offs

**The near-miss reaches the right action anyway** → Stated in the proposal rather
than hidden, and carried by an eval case instead of by the walk: a case asserting
`bad-deployment` is not diagnosed where the deploy landed and did not finish. The
e2e case asserts the mode and the mitigation; it cannot assert that a wrong
reading would have failed, because it would not have.

**A sixth channel invalidates every recording** → Every `both-*` corpus is
captured against the Investigator's tool list, and a new tool moves it. This is
the same cost the seventh mode's meaning imposed, one level larger. The free
replay suite is the thing that says whether it landed, and it has to be
re-recorded before it can.

**The scenario needs two real commits in the demo app, pushed** → Code-Fix and the
deployment-diff channel read GitHub, not the working tree, so a commit that
exists only on disk buys a confident answer about the wrong file. Both commits are
pushed before anything paid is run, and their hashes are constants in
`scenarios.py`, as the cache port's and the slow average's are.

**A second cache scenario invites confusion with `cache-misconfigured`** → They
share a module and nothing else: there the cache is unreachable and every lookup
misses, here the cache is healthy and answering at its usual ratio and what is
wrong is what two versions of the shop put in it. The hit ratio is the series that
separates them, and it is already in the bucket.
