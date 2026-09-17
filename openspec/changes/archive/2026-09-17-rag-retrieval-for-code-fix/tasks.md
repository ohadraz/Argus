Tests come first and are proposed in chat, whole file at a time, for the human to
add - `tests/`, `argus_testkit` and the doubles are off-limits. Every task below
that says "implement" is preceded by that proposal and the human's paste.

## 1. Foundations

A dependency is added by the test that could not pass without it, never ahead of
one. `qdrant-client` and `fastembed` are therefore not here: they arrive in 3.4
and 3.3, where something first fails for want of them.

- [x] 1.1 Confirm `fastembed` and `qdrant-client` resolve against Python 3.14 at
      all, as a spike - nothing added to any `pyproject.toml` by it. If they do
      not, the embedding decision reopens before anything is built on it
- [x] 1.2 Scaffold `modules/code_index/` per the `new-module` skill: own
      `pyproject.toml` depending on `argus_core` alone,
      `src/code_index/`, `tests/code_index_test/`
- [x] 1.3 Add `code_index` to `[tool.importlinter] root_packages` and place it in
      a layer; confirm `nox -s guard_layering` names it rather than passing
      silently
- [x] 1.4 Confirm the new module is auto-discovered: `nox --list` shows
      `test_module(module='code_index')`
- [x] 1.5 Add each setting the index needs at the point a test reads it, not
      before - the store's endpoint, the collection, the model, the chunk
      bounds, the webhook secret and the retrieval channel arrive across
      groups 3 to 7

## 2. The watermark

- [x] 2.1 Add `REPOSITORY_INDEX` to Alembic revision `001` in place - repository,
      `indexed_sha`, `pending_sha`, `indexed_at`
- [x] 2.2 Implement the repository owning that table in `code_index`: read the
      row, record a completed index, record a pushed commit
- [x] 2.3 Implement the currency question: current, or behind naming both
      commits. One comparison, no stored flag
- [x] 2.4 Verify `nox -s schema` applies cleanly from an empty database

## 3. Turning a repository into an index

Reading a repository whole is `repository_source`'s, extracted from
`read_mcp_server` when the index turned out to ask the same question. The kernel
was the wrong home for it - a pure rule about which paths are the service's own
is a line and belongs there; an archive, a vendor's API and a failure type are a
module.

- [x] 3.1 Implement chunking: Python files at top-level `ast` boundaries,
      everything else in overlapping line windows, every chunk carrying path and
      line span
- [x] 3.2 Implement the source-path filter, reusing the rule
      `search_repository` already applies so both channels see one body of code
- [x] 3.3 Implement the embedding seam - an injected callable, defaulting to
      `fastembed` built on first use so a unit test never loads a model
- [x] 3.4 Implement the store writes: create the collection if absent, upsert
      chunks, delete the points for a path before re-inserting it
- [x] 3.5 Implement `index_repository(repository, sha, paths=None)` - the single
      entry point, whole repository or named paths, recording the watermark on
      completion
- [x] 3.6 Component test the whole module through that entry point against a
      real Qdrant

## 4. Retrieval

- [x] 4.1 Implement retrieval by meaning in `read_mcp_server`: embed the
      description, query filtered to the repository and its source paths, answer
      `path:start-end` plus the passage
- [x] 4.2 Implement the two distinct empty answers - nothing near enough, versus
      a store that could not be reached, which raises
- [x] 4.3 Implement the staleness prefix: when behind, the answer states both
      commits
- [x] 4.4 Register `search_repository_by_meaning` on the read server, behavior in
      the module and registration holding none
- [x] 4.5 Add the typed function to `read_mcp_client`

## 5. Code-Fix

- [x] 5.1 Add the `SEARCH_BY_MEANING` tool definition, written to tell the model
      what it is for and how it differs from substring search
- [x] 5.2 Implement tool assembly from configuration - substring, meaning, or
      both - keeping both implementations present whichever is chosen
- [x] 5.3 Implement the retrieval branch in `_ran`, and confirm a failed call
      comes back as a readable tool result rather than ending the attempt
- [x] 5.4 Implement the opening message's staleness statement, and confirm a
      current index adds nothing to it. The watermark reaches Code-Fix as a
      read tool of its own rather than through a database in the agent, which
      settles the design's open question about exposing it
- [x] 5.5 Run `nox -s "test_module(module='agent_codefix')"`

## 6. The push webhook

- [x] 6.1 Implement `POST /webhooks/github/push` on `argus_web`: verify
      `X-Hub-Signature-256` against the raw body in constant time, before
      reading anything from it
- [x] 6.2 Implement the ref filter - a push to anything but the deployed branch
      records nothing - and record `after` as `pending_sha`, answering `202`
- [x] 6.3 Confirm `guard_layering` still passes: `argus_web` gained no embedding
      or vector-store dependency. The store and the model became a `[store]`
      extra of `code_index` for it, as `anthropic` and `mcp` are of the kernel,
      and the allowance names `code_index.records` alone

## 7. The reconciler

- [x] 7.1 Implement the reconcile pass: compare `indexed_sha` to `pending_sha`
      and close the gap through `index_repository` - backfill when the index is
      empty, incremental otherwise, one code path either way
- [x] 7.2 Implement the loop around it, waking on its own schedule rather than on
      a notification
- [x] 7.3 Implement the incremental case from the paths a comparison names,
      rather than from the push. The webhook records one commit and no paths,
      and a pass has to be correct for the deployed branch whether or not any
      delivery arrived - so the paths come from `/compare`, and a comparison
      too large for the provider to list is treated as no answer
- [x] 7.4 Confirm it is level-triggered: a failed pass retries with no attempt
      count, three pushes leave one target, and a notification that never
      arrived costs a delay rather than a permanently stale index
- [x] 7.5 Add the `index` nox session, per the `nox-session-style` skill

## 8. Deployment

- [x] 8.1 Add Qdrant to docker-compose with a persistent volume
- [x] 8.2 Start the reconciler with the stack, one pass to completion before
      any service and the loop after it. Not a compose service with a
      healthcheck: Argus's own processes are not containerized yet, so the
      ordering lives where the schema job's does. It becomes a service with a
      condition when they are
- [ ] 8.3 Bake the embedding model into the image so no start needs the
      network. **Blocked on the same dockerization** - there is no Argus image
      to bake it into. CI caches it instead (8.4), and a local run downloads it
      once
- [x] 8.4 Cache the fastembed model directory in CI, so a run downloads
      130MB once rather than on every push
- [x] 8.5 Wire the webhook secret through configuration and the compose env.
      Configuration only, for the same reason as 8.2: the web process is
      started from the stack and reads the environment it inherits

## 9. End to end

- [x] 9.1 Propose the e2e covering a fix localized by meaning, and one covering a
      signed push moving the watermark
- [x] 9.2 Refresh the Anthropic recordings for the new tool in Code-Fix's list.
      One set per mode, stored under that mode's prefix: `grep` is what was
      already there - the walk Code-Fix took before this change - and `both` and
      `meaning` were captured against their own stacks, because a recording is a
      queue of answers to a walk that was offered a particular set of tools
- [x] 9.3 Run `nox -s e2e_replay` - free and keyless, no real GitHub. Once per
      mode, since each is a stack of its own: `grep` 15 cases (the index ones
      are not collected where there is no index), `both` and `meaning` 17 each,
      all green
- [x] 9.4 Run `nox -s e2e` once against the real API, and report the token spend
      from the replay log before teardown. 24 passed in 27m49s, over 84 model
      calls: 48,465 output tokens, 275,813 read from cache, 263,170 written to
      it, and 168 that were neither. The first attempt failed on the response
      cost, which turned out to be the Target Service calling its whole rolling
      telemetry window "the incident" - fixed there, and the figure is now
      counted from the page to recovery

## 10. Documentation

- [x] 10.1 Update `docs/spec-and-architecture.md` per the `spec-doc-style` skill:
      §7.4's retrieval channels, §8's RAG entry, §11's index and its watermark,
      §12's store, §16's channels, §24's locked-in decisions - including that
      Chroma stays long-term memory's and Qdrant is the repository index's
- [x] 10.2 Add the retriever comparison to §21 as a benchmark dimension
- [x] 10.3 Update `CLAUDE.md` with the new module and the `index` session
