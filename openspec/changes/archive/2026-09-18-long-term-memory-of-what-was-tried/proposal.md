## Why

Argus forgets every incident the moment it ends. Each new incident re-derives
its cause from evidence, which is the right thing to do - but it also re-tries
mitigations that were tried before and did not help, because nothing anywhere
records that they were tried. A cause is re-derivable from the metrics and the
logs of the incident in front of it; **what was done about it, and whether that
worked, is not** - it exists only in the record of the incident that did it.

That is the one thing long-term memory can supply that no amount of retrieval
budget can. Milestone 7 (§23) asks for past incidents to be retrievable and used
to seed new ones; this is that milestone, aimed at the fact that is genuinely
missing rather than at the one the Investigator could work out for itself.

## What Changes

- A **new store of resolved incidents**, one record each, carrying what the
  incident looked like and every action Argus took on it with the outcome that
  action reached. Qdrant, in a collection of its own beside the repository index
  (§11.5), searched by similarity over the incident's symptom text with a
  metadata filter first.
- A **new node at the end of the walk** writes that record. It derives it from
  the `ACTION` rows and the incident's own alert, not from the Postmortem's
  prose - filing what was tried is a different job from writing the incident up,
  and the Postmortem node keeps only its own.
- **The mitigation side consults it when ranking candidates.** A candidate whose
  subject was tried for a similar incident and refuted is ranked below one that
  was not. The Investigator is unchanged: this fact is not a hypothesis and it
  cannot act on it.
- **Recall is a seed, not a tool.** It is read before the candidate order is
  fixed, on every incident, so that "with memory" and "without memory" are two
  measurable configurations rather than two runs of a model that may or may not
  have chosen to ask.
- **Chroma is replaced by Qdrant** for long-term memory, updating the §24
  decision. **BREAKING** to that decision only - nothing is deployed on Chroma,
  so no data moves.
- Recall is switchable off, for §21's comparison and for a deployment that wants
  the walk to depend on nothing but the incident in front of it.

## Capabilities

### New Capabilities

- `incident-memory`: the record of a finished incident - what it looked like,
  what was tried, what each attempt reached - and the store it is written to and
  searched in. Covers what is written, when, by what, and what a search returns.

### Modified Capabilities

- `mitigation-retry-walk`: the order candidates are tried in becomes informed by
  what was tried on similar past incidents, where today it is confidence order
  filtered by this incident's own attempts.

## Impact

- **New module** `incident_memory/` - the record, the store, the writer and the
  recall. Qdrant and the embedding model behind a `[store]` extra, as
  `code_index` does, so a caller that only names the types does not install an
  ONNX runtime.
- **`orchestrator`** - one new walk node and its edge, one new port in
  `assembling.py`, and recall threaded into candidate ordering
  (`walk/candidates.py`).
- **`argus_core`** - configuration for the collection and the switch; a
  contract type if the record is named by two modules.
- **Layering** - `incident_memory` joins `[tool.importlinter] root_packages` and
  a contract says what it may depend on.
- **No schema migration.** The record is derived from tables that already exist;
  the store it goes to is not Postgres.
- **Docker-compose** gains nothing: the Qdrant service the index already needs
  serves the second collection.
- **Evaluation (§21)** gains a configuration to compare, and the honest caveat
  that the Target Service's alert vocabulary is too uniform to separate
  similarity search from an exact-match lookup - the mechanism is built for the
  real case, and the fixture cannot yet demonstrate the difference.
