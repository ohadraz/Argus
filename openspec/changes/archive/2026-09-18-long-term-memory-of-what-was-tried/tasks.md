## 1. Settle what is stored

- [x] 1.1 Decide the similarity floor and how many records inform one ordering,
      and whether each is configuration. **Five records, floor 0.5, both
      settings, both stated as starting guesses.**

## 2. The module

- [x] 2.1 Scaffold `modules/incident_memory/` per the `new-module` skill -
      `pyproject.toml`, `src/incident_memory/`, `tests/incident_memory_test/`.
      (The test package is the user's to create - see group 7.)
- [x] 2.2 Declare the `[store]` extra (`qdrant-client`, `fastembed`) as
      `code_index` does, with the hard dependency on `argus_core` only.
- [x] 2.3 Add `incident_memory` to `[tool.importlinter] root_packages` and write
      the contract saying what it may depend on; `nox -s guard_layering` green.
- [x] 2.4 Confirm it is auto-discovered: `uv run python -m nox --list` shows
      `test_module(module='incident_memory')`.

## 3. The record and the store

- [x] 3.1 `records.py` - the memory record as a value: incident id, the embedded
      text, the alert's metadata, and each action with its subject and outcome.
      Decide whether it is a contract type belonging in `argus_core.models`.
      **Stays in `incident_memory` - only this module and its callers name it.**
- [x] 3.2 `composing.py` - a record from an incident's alert and stored
      actions; nothing where no attempt reached a verdict on a subject it named.
- [x] 3.2b `describing.py` - assemble the embedded text: the alert's own words,
      then the hypothesis summary and its supporting evidence. No model call,
      so no fallback and nothing unreproducible.
- [x] 3.3 `store.py` - write one record, search by text with a metadata
      narrowing, ordered most-similar-first. Collection name from configuration.
- [x] 3.4 Reuse the embedder seam rather than a second copy of it: decide whether
      `an_embedder` is lifted out of `code_index` or a sibling is written, and
      make that decision once. **Lifted to `argus_core.embedding` behind a new
      `embedding` extra; `code_index.embedding` is now only which model it asks
      for, and both old import paths still resolve, so no test file moved.**
- [x] 3.5 An absent collection reads as an empty corpus; a first write creates it.
- [x] 3.6 Make the subject of an action something a record can be composed from.
      The column was declared and read by both queries and written by nothing, so
      every attempt was discarded as evidence about nobody and no incident could
      ever be remembered. Written by the claim, before the action is taken.
      **Renamed `action.target` to `action.subject` while fixing it** - the walk,
      `ActionTaken` and `WhatWasTried` all say subject, and a name only the column
      used is how it stayed invisible. Reaches `rev_001_the_schema.py`,
      `TakenAction`, the repository, the `RecordAction` port and `gathering.py`,
      whose account of what was done had been reading "on None" throughout.

## 4. Writing at the close of a walk

- [x] 4.1 A new walk node that writes it, and its port in `walk/ports.py`.
- [x] 4.2 Wire it into the graph beside the postmortem node, each independent of
      the other's failure.
- [x] 4.3 Supply the port in `assembling.py`, and a no-op supplier for a
      deployment with memory disabled.
- [x] 4.4 Narrate a write that failed on the incident's timeline.

## 5. Reading before the candidate order is fixed

- [x] 5.1 A recall call that takes the incident's text and returns past records,
      made once per incident before the first proposal.
- [x] 5.2 Extend the ordering in `walk/candidates.py`: demote a candidate whose
      subject was refuted on a similar past incident; never exclude one; leave
      untouched candidates in confidence order.
- [x] 5.3 Narrate a reordering, naming the past incident behind it; narrate
      nothing when the order did not change.
- [x] 5.4 An unreachable or slow store is treated exactly as an empty result -
      no escalation, no stalled walk.

## 6. Configuration and the switch

- [x] 6.1 Settings for the collection name, the switch, the similarity floor and
      k; `.env` and `.env.example` alongside.
- [x] 6.2 With memory disabled: nothing written, nothing searched, decisions
      identical to an empty store.
- [x] 6.3 The switch reaches the e2e stack's settings, so a mode can be run
      either way.

## 7. Tests (proposed in chat, pasted by the user)

- [x] 7.1 `incident_memory` unit tests: composing a record from actions, the
      empty-content case, ordering of search results.
- [x] 7.2 `incident_memory` component test against a real Qdrant: write, search,
      absent collection, empty corpus.
- [x] 7.3 `orchestrator` unit tests: the new node writes what the composer built;
      a failed write does not take the postmortem down; the ordering rule demotes
      without excluding; disabled memory changes nothing.
- [x] 7.4 An e2e case whose `given` seeds past incidents **through the real
      writer**, then runs a scenario and asserts the order memory produced.
- [x] 7.5 Decide whether the e2e memory case needs its own recordings, given the
      tool list does not change. **No, and none were cut.** Memory reorders
      candidates and writes a row; neither asks the model anything, so the walk's
      calls are the ones already recorded. The case replays
      `both-feature-flag-toggle` and `both-flag-toggle-red-herring` as they
      stand. Its first failure looked like a stale recording and was 3.6.

## 8. Documentation and the spec

- [x] 8.1 `docs/spec-and-architecture.md`: rewrite §11.2 as this design (store of
      what was done, Qdrant, read by the mitigation side), update the §24 row from
      Chroma to Qdrant, and §7 for the new node. Per the `spec-doc-style` skill -
      as though it had always said this.
- [x] 8.2 §21: state plainly that the fixture's alert vocabulary cannot separate
      similarity search from exact match, and what would.
- [x] 8.3 `CLAUDE.md`: one line for the new module in the repo-structure list.

## 9. Green

- [x] 9.1 `lint`, `typecheck` (458 files), `guard_layering`, `guard_e2e_boundary`.
- [x] 9.2 `test_module` for the four modules 3.6 reaches: `argus_incidents` 72,
      `orchestrator` 154, `incident_memory` 28, `argus_web` 80.
- [x] 9.3 `e2e_replay(mode='both')` - 19 passed in 14:45.
- [x] 9.4 `openspec validate --all` - 42 passed.
- [x] 9.5 `sweep`, which is where the store's own port came from: `test_all` and
      `e2e_replay` both published Qdrant on 6333 and only ever ran one at a time,
      so a suite that had nothing to do with either died on the bind. A port per
      stack in `noxfile.py`, the treatment the Slack double already had.
