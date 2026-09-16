Tests come first and are proposed in chat, whole file at a time, for the human to
add - `tests/`, `argus_testkit` and the doubles are off-limits. Every task below
that says "implement" is preceded by that proposal and the human's paste.

## 1. Foundations

- [ ] 1.1 Add `qdrant-client` and `fastembed` to the workspace, pinned, and
      confirm `uv sync --all-packages` resolves on Windows, WSL and mac
- [ ] 1.2 Scaffold `modules/code_index/` per the `new-module` skill: own
      `pyproject.toml`, `src/code_index/`, `tests/code_index_test/`, workspace
      dependency on `argus_core`
- [ ] 1.3 Add `code_index` to `[tool.importlinter] root_packages` and place it in
      a layer; confirm `nox -s guard_layering` names it rather than passing
      silently
- [ ] 1.4 Confirm the new module is auto-discovered: `nox --list` shows
      `test_module(module='code_index')`
- [ ] 1.5 Add the index's settings to `argus_core` - Qdrant endpoint, collection
      name, embedding model, chunk bounds, the GitHub webhook secret

## 2. The watermark

- [ ] 2.1 Add `REPOSITORY_INDEX` to Alembic revision `001` in place - repository,
      `indexed_sha`, `pending_sha`, `indexed_at`
- [ ] 2.2 Implement the repository owning that table in `code_index`: read the
      row, record a completed index, record a pushed commit
- [ ] 2.3 Implement the currency question: current, or behind naming both
      commits. One comparison, no stored flag
- [ ] 2.4 Verify `nox -s schema` applies cleanly from an empty database

## 3. Turning a repository into an index

- [ ] 3.1 Implement chunking: Python files at top-level `ast` boundaries,
      everything else in overlapping line windows, every chunk carrying path and
      line span
- [ ] 3.2 Implement the source-path filter, reusing the rule
      `search_repository` already applies so both channels see one body of code
- [ ] 3.3 Implement the embedding seam - an injected callable, defaulting to
      `fastembed` built on first use so a unit test never loads a model
- [ ] 3.4 Implement the store writes: create the collection if absent, upsert
      chunks, delete the points for a path before re-inserting it
- [ ] 3.5 Implement `index_repository(repository, sha, paths=None)` - the single
      entry point, whole repository or named paths, recording the watermark on
      completion
- [ ] 3.6 Component test the whole module through that entry point against a
      real Qdrant

## 4. Retrieval

- [ ] 4.1 Implement retrieval by meaning in `read_mcp_server`: embed the
      description, query filtered to the repository and its source paths, answer
      `path:start-end` plus the passage
- [ ] 4.2 Implement the two distinct empty answers - nothing near enough, versus
      a store that could not be reached, which raises
- [ ] 4.3 Implement the staleness prefix: when behind, the answer states both
      commits
- [ ] 4.4 Register `search_repository_by_meaning` on the read server, behavior in
      the module and registration holding none
- [ ] 4.5 Add the typed function to `read_mcp_client`
- [ ] 4.6 Confirm the read tier still writes nothing: `nox -s contract`

## 5. Code-Fix

- [ ] 5.1 Add the `SEARCH_BY_MEANING` tool definition, written to tell the model
      what it is for and how it differs from substring search
- [ ] 5.2 Implement tool assembly from configuration - substring, meaning, or
      both - keeping both implementations present whichever is chosen
- [ ] 5.3 Implement the retrieval branch in `_ran`, and confirm a failed call
      comes back as a readable tool result rather than ending the attempt
- [ ] 5.4 Implement the opening message's staleness statement, and confirm a
      current index adds nothing to it
- [ ] 5.5 Run `nox -s "test_module(module='agent_codefix')"`

## 6. The push webhook

- [ ] 6.1 Implement `POST /webhooks/github/push` on `argus_web`: verify
      `X-Hub-Signature-256` against the raw body in constant time, before
      reading anything from it
- [ ] 6.2 Implement the ref filter - a push to anything but the deployed branch
      records nothing - and record `after` as `pending_sha`, answering `202`
- [ ] 6.3 Confirm `guard_layering` still passes: `argus_web` gained no embedding
      or vector-store dependency

## 7. The reconciler

- [ ] 7.1 Implement the reconcile pass: compare `indexed_sha` to `pending_sha`
      and close the gap through `index_repository` - backfill when the index is
      empty, incremental otherwise, one code path either way
- [ ] 7.2 Implement the loop around it, waking on its own schedule rather than on
      a notification
- [ ] 7.3 Implement the incremental case from the paths the push named
- [ ] 7.4 Confirm it is level-triggered: a failed pass retries with no attempt
      count, three pushes leave one target, and a notification that never
      arrived costs a delay rather than a permanently stale index
- [ ] 7.5 Add the `index` nox session, per the `nox-session-style` skill

## 8. Deployment

- [ ] 8.1 Add Qdrant to docker-compose with a persistent volume
- [ ] 8.2 Add the reconciler service, its healthcheck green only once the index
      is current, with readers depending on that condition
- [ ] 8.3 Bake the embedding model into the image so no start needs the network
- [ ] 8.4 Wire the webhook secret through configuration and the compose env

## 9. End to end

- [ ] 9.1 Propose the e2e covering a fix localized by meaning, and one covering a
      signed push moving the watermark
- [ ] 9.2 Refresh the Anthropic recordings for the new tool in Code-Fix's list
- [ ] 9.3 Run `nox -s e2e_replay` - free and keyless, no real GitHub
- [ ] 9.4 Run `nox -s e2e` once against the real API, and report the token spend
      from the replay log before teardown

## 10. Documentation

- [ ] 10.1 Update `docs/spec-and-architecture.md` per the `spec-doc-style` skill:
      §7.4's retrieval channels, §8's RAG entry, §11's index and its watermark,
      §12's store, §16's channels, §24's locked-in decisions - including that
      Chroma stays long-term memory's and Qdrant is the repository index's
- [ ] 10.2 Add the retriever comparison to §21 as a benchmark dimension
- [ ] 10.3 Update `CLAUDE.md` with the new module and the `index` session
