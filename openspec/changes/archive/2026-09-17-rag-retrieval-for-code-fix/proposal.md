## Why

Code-Fix localizes a fault by agentic search: it greps for a string the
investigation named, reads what comes back, and follows the code. That works
because the cause arrives with a traceback in it, and it works on a repository
small enough that a substring is nearly an address.

It fails on the case it was built for. A substring search finds the code that
says what the investigation said; it does not find the code that *does* what the
investigation described in other words. A hypothesis reading "the spend summary
divides by a count that can be zero" matches nothing in a repository that spells
it `len(purchases)`, and the agent's next move is to guess - list every file and
read names, which is the fallback the tool descriptions already call a fallback.

Retrieval by meaning is the missing channel, and §8 has always named it: RAG as
the alternative to agentic search behind the same seam, with which retriever wins
on which repository left to the benchmark (§21) rather than asserted here. This
change builds that side. It is also a stated requirement of the project.

## What Changes

- **A repository's source becomes searchable by meaning.** Its files are cut
  into chunks, embedded, and stored in a Qdrant collection. Code-Fix gains a
  retrieval tool that takes a description and answers with the passages that
  mean the same thing, beside the substring search it already has.
- **The index is built before an incident needs it, never during one.** A job at
  startup indexes the configured repository, in the same shape and for the same
  reason as the schema job: a service that needs the index refuses to start
  without one. Indexing on first use was considered and rejected - it spends the
  minutes of a live outage on work that had all day to happen, and makes GitHub's
  availability a dependency at the one moment nothing can wait for it.
- **A push keeps it current.** Argus consumes GitHub's push webhook and
  re-indexes what changed. Backfill and incremental alike go through one indexing
  entry point; nothing owns a second copy of how a repository becomes an index.
- **The index knows what it is current as of**, and says so when it is behind.
  A push not yet consumed - GitHub unreachable, a retry still pending - leaves
  the index describing an earlier commit, and an agent searching it is told that
  rather than left to read old files as though they were deployed.
- **A reconciler closes the gap, in the background.** The webhook records what
  the repository is at; a level-triggered loop compares that to what is indexed
  and acts on the difference. That is why a missed or failed delivery heals
  itself, and why none of it happens on an incident's path.
- **Which retriever Code-Fix uses is configured, not hardcoded.** Both are real
  and both stay: the benchmark's question is which one wins, and a question
  cannot be asked of an implementation that was replaced.

## Capabilities

### New Capabilities
- `code-index`: what the index holds, when it is built, how a push and a
  reconciler keep it current, what it is current as of, and what happens while it
  is behind.
- `semantic-code-retrieval`: retrieval by meaning as a channel Code-Fix can
  reach - what is asked, what comes back, and how it differs from a substring
  match that found nothing.

### Modified Capabilities
- `code-fix-agent`: the retrieval channel is selectable rather than fixed, and
  the agent is told when what it searched is behind the deployed code.
- `read-mcp-server`: a fifth channel - the service's source by meaning - under
  the same credential that cannot write.

## Impact

- **A new module owns indexing** - chunking, embedding, and writing a
  collection - and is the only place that knows how a repository becomes an
  index. The reconciler calls it for a backfill and for an incremental pass
  alike; the webhook calls it not at all.
- `modules/read_mcp_server`, `modules/read_mcp_client`: the semantic retrieval
  tool, over the collection indexing wrote.
- `modules/agent_codefix`: a fourth tool in `TOOLS`, a retriever chosen by
  configuration, and an opening message that states the watermark when the index
  is behind.
- `modules/argus_web`: the push webhook. It validates and enqueues, as the alert
  webhook does - the indexing itself belongs to the worker, so `argus_web` does
  not install an embedding model to serve HTML (`guard_layering`).
- `modules/argus_core`: the index's settings and the watermark as a contract;
  a new front door if the store's client is shared.
- Deployment: Qdrant as a container with a persistent volume, and the reconciler
  between it and any service that reads it - the schema job's position in the
  compose ordering, gated on its healthcheck rather than on its exit.
- `noxfile.py`: an `index` session, on the schema session's model.

## Non-Goals

- **Long-term memory (Chroma, §11.2).** A different store, a different corpus
  and a different consumer - the Investigator's past incidents, not the
  repository's source. It follows; nothing here waits for it.
- **Deciding which retriever is better.** This change makes both reachable and
  the choice configurable. Which one wins on which repository is §21's to
  measure.
- **Registering repositories at runtime.** The repository comes from
  configuration, as it does today. Startup is the registration event.
- **Indexing anything but the Target Service's own source.** The path filter
  that already keeps the scenario harness out of `search_repository` keeps it
  out of the index.
