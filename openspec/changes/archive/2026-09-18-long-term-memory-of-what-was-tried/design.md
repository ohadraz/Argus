## Context

Argus already holds two memories and one index. Episodic memory is the incident's
own rows in Postgres, which stop a walk re-toggling a flag it has already ruled
out *within one incident*. The repository index (§11.5) is Qdrant plus a local
embedding model, and is derived state rather than memory at all. Long-term memory
- §11.2's third store - has never been built.

The spec describes it as a store of resolved incidents whose summaries bias the
Investigator's first hypotheses. Exploring that revealed the weakness: a cause is
re-derivable from the incident in front of you, so recalling one only saves
turns. What is not re-derivable at any budget is what was **done** - which
mitigation was tried, and what it reached. That fact exists in exactly one place,
the record of the incident that produced it, and it is the one that changes a
decision rather than shortening a path to it.

The constraints that shaped the design are already in the repo: `code_index`
established how a vector store and a local embedder are wrapped behind a `[store]`
extra; `assembling.py` established that the walk's collaborators are injected
ports; `walk/candidates.py` already holds the one function that decides which
candidate is next.

## Goals / Non-Goals

**Goals:**

- Record what every finished incident tried and what each attempt reached.
- Let the mitigation side consult that record when it fixes candidate order.
- Keep the mechanism switchable, so §21 can compare two configurations that
  differ in exactly one thing.
- Keep memory strictly optional at runtime: no incident is ever worse off for the
  store being down.
- Build the search for the real case - one cause raising differently-named alerts
  - rather than for the fixture's small, uniform alert vocabulary.

**Non-Goals:**

- Seeding the Investigator. What is stored is not a hypothesis, and the
  Investigator cannot act on it.
- A recall tool the model chooses to call. A choice that varies run to run cannot
  be measured on and off, and the model has no use for the fact anyway.
- Storing generated prose. The postmortem is for humans; this is for the walk.
- Cross-service memory. One Target Service, one corpus.
- Demonstrating the benefit in the current benchmark - see Risks.

## Decisions

### The record is what was done, not what it was

One record per finished incident: the alert that opened it, the text describing
what it looked like (the embedded field), and every action with its outcome.

*Alternative considered - store the root cause and recall it to seed hypotheses
(§11.2 as written).* Rejected: the Investigator re-derives the cause from
evidence anyway, so this is a speedup with no new capability, and a speedup the
benchmark's uniform scenarios would struggle to detect. The outcome of an action
is the only thing here that no amount of investigation can reach.

### The embedded text is assembled, not written

At close, the text that gets embedded is the alert's own words followed by what
the investigation concluded and the evidence it cited. One vector then carries
both how the monitoring named the incident and what it actually looked like, and
there is no reason to keep those in separate vectors and merge two searches.

*Alternative considered - have a model compose a sentence describing the
symptom.* Its only job is to be matched against, and a join of text already on
hand embeds to very nearly the same place. Against that, a model call would make
this module take the `llm` extra and a layering allowance it otherwise needs
none of, would add a failure mode wanting a fallback, and would make a record's
text unreproducible.

*Alternative considered - use the postmortem's executive summary, which is
already written.* Rejected because it would make the memory write depend on the
postmortem node having run and succeeded, which is the coupling the separate
node exists to avoid.

### Every finished incident, not only a resolved one

An escalation after three refutations is the most informative record the system
can produce. A resolved incident says one thing worked; an escalated one says
three things did not, and the second is what the ordering rule actually consumes.

An incident where no action reached a determined outcome - withdrawn mid-window,
or escalated before acting - writes no record. Its content would be empty.

### Qdrant, one more collection - not Chroma

§24 chose Chroma when Argus had no vector store at all. It now runs Qdrant for
the repository index, with `fastembed` and a store wrapper already in the
workspace.

*Alternative considered - Chroma, as specified.* Its one genuine advantage was
running embedded with no server; `QdrantClient` takes `location=":memory:"` or a
local `path` for the same thing. At a few hundred records neither engine has a
retrieval advantage worth measuring, so what remains is operational: one store to
run, one client to learn, one service in compose.

*Alternative considered - Postgres, no vector store at all.* Genuinely tempting:
if the match is "same alert name, same flag", it is a `WHERE` clause. Rejected
because that match only holds for the fixture. In a real system one cause raises
several differently-named alerts, subjects get renamed and versioned, and
`Alert.summary` is prose - the link between two incidents that mean the same
thing is semantic. See Risks for the cost of this choice.

### A new node, at the close of the walk

`postmortem_node` is the last node today and is the obvious place to bolt this
on. It is the wrong place: its job is writing the incident up, and filing what
was tried is a different job reading a different source. A node of its own, with
its own injected port, keeps each testable alone and keeps a failure in one from
taking the other down.

### Recall is read once, before candidate order is fixed

`the_next_worth_trying` already sorts candidates and already filters by this
incident's own attempts. Recall widens that filter across incidents: demote a
candidate whose subject was refuted on a similar past incident, leave everything
else alone.

Read once, before the first proposal, rather than per candidate: one search per
incident, a deterministic order, and one event in the timeline accounting for it.

### Demote, never exclude

A past refutation is evidence about a past incident. The same flag can break the
service twice. Excluding a candidate on that basis would let old evidence produce
an escalation the walk had the means to avoid, so memory only reorders - the set
of candidates tried is identical with memory and without it.

### A new module, `incident_memory`

The record, the store, the writer and the search. Qdrant and the embedder behind
a `[store]` extra exactly as `code_index` does, so a caller naming only the types
does not install an ONNX runtime. It joins `[tool.importlinter] root_packages`
with a contract saying what it may depend on.

## Risks / Trade-offs

- **The benchmark cannot show the win.** The Target Service's alerts are few and
  uniformly worded, so similarity search and an exact-match lookup would score
  identically on it. → State it in the eval write-up rather than discovering it
  at eval time. The mechanism is built for the real case; demonstrating it needs
  either a richer fixture or a live system, and both are out of scope here.

- **A vector store for a few hundred rows is over-engineered for today.** → True,
  and accepted deliberately: the alternative bakes the fixture's limitations into
  the design. The cost is one collection in a server that is already running.

- **Memory could entrench a wrong order.** One unlucky refutation demotes a
  subject on every later similar incident. → Demotion never excludes, so the
  candidate is still tried; and the timeline names the past incident behind the
  change, so a human can see why the order was what it was.

- **A cold store looks like a broken one.** Empty results and unreachable results
  are handled identically by design, which means a misconfigured store is
  invisible. → The write path's failure is narrated on the timeline, so a store
  nothing can be written to shows up there rather than only as silence on the
  read side.

- **Two stores now share one Qdrant.** A collection name collision or a wiped
  volume takes both. → Distinct collection names in configuration; the repository
  index is derived state and rebuilds itself, and memory's loss degrades ordering
  without breaking a walk.

## Migration Plan

Nothing to migrate. No schema change - the record is derived from tables that
already exist. No data lives in Chroma, which was never built. The collection is
created on first write, and an absent collection reads as an empty corpus.

Rollback is the switch: disabling memory returns the walk to confidence order.

### The floor and the count are configuration, and start as guesses

A search returns at most **five** records and discards anything below a
similarity of **0.5**. Both are settings (`INCIDENT_MEMORY_RECALL_LIMIT`,
`INCIDENT_MEMORY_SIMILARITY_FLOOR`), and both are stated here as the starting
guesses they are - the same status the anomaly thresholds had before any
incident had been measured.

The floor exists because a nearest-neighbour search always answers. With none,
a corpus holding one unrelated incident would demote a candidate on the strength
of the least-unlike thing it had. It is applied in the store rather than by the
caller, so nothing above it ever sees a record it was meant to ignore.

Five because the ordering rule only asks whether *any* recalled record refuted a
subject: a sixth record changes an order the first five did not only in a corpus
far larger than this system will have.

## Open Questions

None outstanding. The two numbers above are deliberate guesses rather than open
questions - the benchmark calibrates them, and nothing waits on that.
