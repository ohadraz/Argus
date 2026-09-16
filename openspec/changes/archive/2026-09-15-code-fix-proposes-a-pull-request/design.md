## Context

`agent_codefix` is a stub. `propose_fix` returns `None` and says so honestly,
which was the right placeholder while the walk's shape was being settled - but
it leaves the graph with one permanent outcome, a reverted flag, and a reverted
flag is a workaround somebody has to come back to. The fault is still in the
code; a toggle is holding it off.

Everything the agent needs already exists around it. The investigation reaches a
named cause. The walk calls Code-Fix through an injected `ProposeFix` port, so
the call site needs no rearranging. Two MCP servers are deployed and split by
autonomy tier (§12.1), each paired with a typed client, and the transport is
shared. What is missing is a channel to the Target Service's own source, a way
to put a change somewhere, and an agent between them.

The state machine has been saying something untrue alongside this. `status_after`
derives `resolved` from a confirmed action, when what was actually established is
that the symptom stopped. The two gaps are one gap: Argus stops one step short of
the thing that would let the flag go back on, and calls stopping there "resolved".

The Target Service is `Argus-Demo-Target-App` - a repository small enough that a
model can hold all of it at once, and public, which is what makes its read side
cheap.

## Goals / Non-Goals

**Goals:**
- A fault the investigation named reaches a human as a draft pull request on the
  service's own repository, with the case for it written out.
- Merging stays impossible, by construction rather than by a check (§13).
- The read tier gains source without gaining the ability to change it.
- The status says what actually happened: `mitigated` when a symptom stopped.
- The seam admits a RAG retriever later without the demo needing one now.

**Non-Goals:**
- **Merging, or anything that observes one.** `resolved` stays reachable in
  principle and is derived nowhere.
- **The RAG retriever.** The port is shaped for it; this change builds the
  search-and-read side.
- **Proving the model fixes bugs.** This builds the pipeline; whether a patch is
  correct is the benchmark's question (§21).
- **A repository too large to list.** Choosing what to read when you cannot read
  everything is a different problem with a different answer.

## Decisions

**The flag scenario is the code-fix scenario.** No seeded branch and no second
fault: the feature-flag incident already carries a real bug in real code, so the
walk is Mitigation reverting the flag and buying time, then Code-Fix patching the
fault so the flag is safe to turn back on. A scenario of Code-Fix's own would
make the two agents demonstrate different incidents and would hide the one thing
worth showing - that a mitigation is not an ending.

**`mitigated` is a status of its own, and terminal.** A mitigation stops a
symptom; it does not end a cause. `resolved` means the cause is gone, which here
means a human merged the fix - and nothing observes a merge, so nothing derives
`resolved`. Terminal in the sense `escalated` is: something is still owed, which
is what the status is for saying, and a page polling it would poll forever.
`RESOLVED_ROUTE` goes away with it, and `route_after_codefix` collapses to one
destination because both its arms already reached the postmortem.

**`fix_found` decides what the incident carries, not what state it is in.** The
status answers "did the symptom stop", and asks that first: an incident mitigated
and then given a fix carries both at once, and the order of the questions is what
keeps it `mitigated` rather than `escalated`. A fix reached *without* a
mitigation is still `escalated` - the symptom is happening and a proposal does
not stop it.

**A confirmed mitigation routes on to Code-Fix.** This is what makes a fix
reachable on the happy path at all; without it, Code-Fix is only ever reached by
an incident nothing could be done for. So `fixing` has two roads into it: Argus
having run out of reversible moves, and Argus having made one that worked.

**Enforcement is by absence.** There is no `merge_pull_request` on either server,
in either client, or in the binding Code-Fix holds. A check that refuses to merge
is a check a later caller can skip or a model can argue with; a function that
does not exist is neither. `draft=True` is not a parameter for the same reason.

**A patch is whole files, submitted as a tool call.** A diff is a second thing
that can fail, and it fails by producing a file that is subtly not what anyone
wrote. Source parsed out of a fenced block fails the same way and more often -
a stray line of commentary becomes a line of Python, a forgotten closing fence
truncates the module being fixed. A whole file that came out wrong is wrong
visibly, on a branch, in front of the person approving it. The model has read the
file by then, so writing it out entire costs tokens and buys exactly that.

**Reading the submission is lenient, one entry at a time.** Every field of
`SubmittedFix` is optional, a prose field arriving as a number is written out,
and a file entry missing either half is dropped. Refusing a whole submission over
a fourth malformed file would throw away three correct ones, and the incident
would record "no fix was found" - describing the reader rather than the agent. An
entry with a path and no readable content is the dangerous one: written out it
puts an empty file over the module it was fixing.

**An empty patch is a real answer.** "I looked and there is nothing to change" is
a conclusion a human acts on, and is true of every flag scenario. It parses, and
it opens no pull request - an empty proposal sends somebody to read a diff with
nothing in it.

**Three outcomes at the node, not two.** A fix that was not warranted and a fix
that could not be *proposed* are different things to whoever reads the incident:
one is a verdict on the code, the other is something somebody can go and repair.
So `propose_fix` returns `None` for both of its honest silences - no files, or no
submission within its turns - and raises what the repository raised. The node
catches broadly: an unreachable GitHub is a bad afternoon, not a lost incident,
and an exception here would take everything the investigation learned with it.

**The branch is cut from the deployed base and every write names it.** GitHub's
Contents API writes to the repository's default branch when no branch is given,
so a write that forgot to say would land on `main` - silently, and it is the one
outcome this module exists to make impossible. The branch is named for the
incident (`argus/fix-<id>`), so two incidents patching the same file do not
overwrite each other's proposal and a branch found weeks later says where it came
from.

**Writing the branch and opening the proposal are separate modules.** They fail
differently and the caller has to tell them apart: a push that was rejected and a
proposal that was never made are different situations, and one module doing both
would report them through one exception.

**A fix brings its own test, and no path is withheld.** The test that fails
before the fix and passes after is the half that shows the patch works, and it
belongs where the service's tests live. A locked file would refuse exactly that,
and it would be defending a grader that runs nowhere: correctness is answerable
from outside the repository, by running the patch's own tests against the base
branch and against the fix. What bounds a bad change is that everything lands on
a branch nobody runs and that merging is a person's act (§13).

**The read tier raises rather than answering emptily.** A truncated listing, a
path that is not there, a file that is not text - each has an innocent-looking
empty answer available, and each would be read as a fact about the repository
rather than about the attempt to read it. The truncation flag is the load-bearing
one: it arrives beside a well-formed, complete-looking, short list of entries, and
a caller that missed it would conclude a file it cannot see does not exist.

**Two credentials, two slices, one repository.** The read tier holds a token that
can read a repository and cannot push to one, which is what lets source be read
from a process incapable of mutation. The write tier's token is its own slice,
separate from the flag tier's although the same process reads both: one object
naming all of them would hand every flag call a token that can push code. For the
demo the read token is blank - the repository is public, and unauthenticated
reads at 60 req/hr are enough.

**httpx, not a GitHub SDK.** GitHub publishes no official Python SDK; PyGithub is
third-party and githubkit self-declares unstable. Four calls do not justify the
dependency, and the wire vocabulary is named as constants either way.

**The cause is given, and the reading is bounded.** The agent is told what the
investigation concluded rather than asked to find it again - a model
rediscovering a settled cause spends its whole reading budget on it. The turn
bound is never expressed to the model, because a bound it could ask to extend
would not be one. It is also told that a mitigation may already have hidden the
symptom, so it reads the code as broken whether or not anything is broken now.

**One retrieval seam, two implementations.** Search-and-read is what the demo
runs on; a RAG retriever sits behind the same four ports. Which one is chosen is
configuration rather than a size threshold - a threshold would leave the RAG path
never running in any benchmark, and which retriever wins on which repository is an
M10 dimension to measure rather than assert.

**The ports are `Protocol`s, and `fixes_over` binds both tiers at the composition
root.** Two clients rather than one, because the two halves of proposing a fix
are two tiers by design, and this is the one place both ends of that split are
held at once. `Protocol` rather than a `Callable` alias for the reason the
investigator's channels are: `create_autospec` needs something introspectable,
and specing against the client functions would spec the wrong shape - those take
the connection they are asked over, and the loop is asked about a repository.

## Risks / Trade-offs

- **The write token is a real credential that can push code** → fine-grained, on
  the one repository, Contents and Pull requests only, in `.env` and a repository
  secret. Scoped so it cannot become the flag token by being nearby (§14).
- **A model that rewrites a file badly** → it is on a branch, in a draft, and
  nothing in the system can merge it. The worst outcome is a bad diff a human
  closes.
- **A write that fails partway leaves a branch with half a patch** → a push
  cannot be un-pushed from here. What matters is that nobody proposes it as whole:
  the failure propagates and no pull request is opened.
- **The demo app's suite is green on `main` with the fault still in it** → by
  design. A bug nobody has written a test for is the ordinary condition of real
  code, and finding it, exposing it with a test and fixing it in one pull request
  is the work. The cost is that correctness now needs a human to read the PR
  until the benchmark (§21) runs the patch's tests for itself.
- **Search-and-read does not scale past a small repository** → acknowledged and
  bounded: the listing refuses rather than truncating, so the failure is loud, and
  the RAG side of the seam is where the answer goes.
- **`e2e_replay` serves recordings from a queue in order, and Code-Fix now
  converses before the postmortem** → its turn is seeded with a literal body -
  no files, the fault is not in the code - rather than a recording. Without it the
  codefix conversation consumes the postmortem's seed and the postmortem is
  written from somebody else's answer while the suite still passes.
- **`resolved` is now dead in the derivation while remaining in the enum** → kept
  deliberately. It is the state Argus cannot reach on its own, and deleting it
  would erase the distinction the whole change is about.
