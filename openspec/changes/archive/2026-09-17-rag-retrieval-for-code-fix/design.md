## Context

Code-Fix reads the Target Service's repository through three tools on the read
tier: `search_repository` (substring, answering `path:line: text`),
`list_repository_files`, and `read_repository_file`. The agent is handed the
investigation's hypothesis and its quoted evidence - which, since the demo shop's
error boundary records the innermost frame, usually names a file and a line - and
searches from there.

The substring is the weak link. It matches the words the investigation used, not
the code that does what those words describe, and its own tool description
already tells the model that listing every file is what to do when the search
found nothing. That fallback is guessing from names.

§8 has named the alternative from the start: RAG behind the same retrieval seam,
with which retriever wins on which repository left to the benchmark (§21). The
seam exists - `SourceSearcher`, `FileLister` and `FileReader` are Protocols the
fix loop takes as keyword arguments - so nothing about the loop's shape has to
change to admit a fourth channel.

What does not exist is anywhere to retrieve *from*. There is no vector store in
the deployment, nothing that turns a repository into vectors, and no notion of a
repository version that an index could claim to be current as of.

## Goals / Non-Goals

**Goals:**

- Retrieval by meaning, reachable by Code-Fix as a tool beside the substring
  search, over the same repository and under the same read-only credential.
- An index that is ready before an incident arrives and never built during one.
- An index that survives a push: current when GitHub is reachable, honestly
  behind when it is not, and reconciling on its own either way.
- One implementation of "turn this repository into an index", with the startup
  job and the push webhook as two callers of it.
- Both retrievers alive and selectable, so §21 has two things to compare.

**Non-Goals:**

- Long-term memory (§11.2). Different store, different corpus, different reader.
- Asserting which retriever is better. This change makes the comparison possible.
- Runtime repository registration. The repository comes from configuration.
- Re-ranking, hybrid BM25 fusion, or query expansion. All are real improvements
  and all are additions to a retriever that first has to exist.

## Decisions

### Qdrant is the store

Carried over from the store comparison already done (pgvector, Chroma, Weaviate,
Vespa, OpenSearch, Milvus, LanceDB). The deciding property is filtered search:
every query here filters - by repository, and by the paths that are the service's
own source rather than its scenario harness. Qdrant applies the filter *during*
graph traversal; pgvector post-filters, so a narrow filter over an HNSW search
returns a fraction of the `k` asked for and silently retrieves less than it
claims to. Weaviate is the close runner-up on hybrid maturity, which would matter
if BM25 fusion were in this change; it is not.

Chroma stays the choice for long-term memory (§11.2, §24). Two stores is not a
contradiction - one holds a repository's source and is filtered on every query,
the other holds a few dozen incident summaries and is filtered by one metadata
field. The spec's Chroma decision was always about the second.

### fastembed produces the vectors, and the reason is not quality

`fastembed` runs `BAAI/bge-small-en-v1.5` (384 dimensions) through ONNX Runtime
inside the process that needs it. It is chosen for three properties, and
retrieval quality is not among them:

1. **It is local.** No network call is made to embed a chunk or a query, so
   nothing here can fail because a vendor was slow, and nothing here has to be
   faked for a test to run.
2. **It makes no external calls.** Every other option is a new external party -
   which under this repo's own rules means a double to build and a contract suite
   to run against it before CI is free and keyless again.
3. **It is free.** Indexing embeds every chunk of the repository and every push
   re-embeds what changed; a hosted embedding API turns that into a standing bill
   for a demonstration project.

A code-specialized hosted model - `voyage-code-3` is the one Anthropic points
at - would retrieve better than a small general-purpose English model on source
code, and it is worth saying plainly that this design accepts worse retrieval to
stay local and free. The embedding call is a seam for exactly that reason: if the
benchmark says semantic retrieval underperforms, "the model is small" is a
hypothesis that can be tested by swapping one injected function.

### The index is built ahead of an incident, never inside one

Building the index on first use was considered and rejected. It puts minutes of
downloading, chunking and embedding onto the critical path of a live outage -
the one moment the work is most expensive and least excusable - and it makes
GitHub's availability a hard dependency precisely when nothing can wait for it.
The cheapest possible version of that idea still fails on the day GitHub is
slow.

So the index is built like the schema is built: by a job that runs before the
services that read it, in the compose ordering slot the schema job already
occupies, after Qdrant and before anything that queries it.

### The watermark lives in Postgres; the vectors live in Qdrant

One row per repository:

```
REPOSITORY_INDEX {
    text repository PK      -- owner/name
    text indexed_sha        -- what the vectors in Qdrant describe
    text pending_sha        -- what the last push said is deployed
    timestamptz indexed_at
}
```

`indexed_sha` is what an agent searching the index is actually searching.
`pending_sha` is what the repository is at. **The difference between them is the
whole mechanism**: it is the retry queue, the staleness signal and the work list
at once.

This is the level-triggered reconciliation Kubernetes controllers are built on,
and the reasoning is the same. `pending_sha` is desired state, `indexed_sha` is
actual state, and the reconciler's only job is to close the gap - it never needs
to know *why* it woke up, only what the two shas currently say. The push webhook
is the edge that wakes it and carries no work of its own; an edge that is missed
is caught by the next pass, where in a purely edge-triggered design a missed
event is missed permanently.

That is why there is no retry counter, no backoff table and no dead letter. A
failed re-index leaves the gap open, so the next pass tries again; three pushes
during an outage leave `pending_sha` at the third, so the reconciler converges on
the current commit rather than replaying a backlog. The state is the goal, not
the history of attempts to reach it.

Qdrant holds one collection per repository. Points carry `path`, `start_line`
and `end_line` in their payload and no sha - the collection always describes
"now", and what "now" means is the row above. Putting the sha in the payload was
rejected: an incremental re-index of four changed files would leave the
collection holding points from two generations, and every query would then need
to know which.

### One indexing function, backfill and incremental alike

```
code_index.index_repository(repository, sha, paths=None) -> None
```

`paths=None` is the **backfill** - the whole repository, which is what
reconciling from an empty index means. A list of paths is the **incremental**
case: delete the points filtered to each path, insert the new chunks. The push
names those paths, as added, modified and removed.

The two are one function because they are one operation seen from two starting
states, which is the same reason the reconciler does not distinguish them:
backfill is reconciliation when actual state is empty. Nothing else in the system
knows how a repository becomes an index.

### The webhook is the edge: it records desired state and nothing else

`POST /webhooks/github/push` on `argus_web`, alongside the alert webhook and
shaped the same way: verify, write one row, answer `202`.

- **Verify first.** GitHub signs the delivery as `X-Hub-Signature-256`, an
  HMAC-SHA256 of the raw body under the configured secret, compared in constant
  time. This is a publicly reachable endpoint that moves Argus's picture of
  production, and an unsigned caller must not be able to move it.
- **Ignore refs that are not the deployed branch.** A push to a feature branch
  changes nothing about what is running.
- **Write `pending_sha` from the payload's `after`, and return.**

It does not index, and the reason is `guard_layering`: `argus_web` serves HTML
without installing an agent, and an indexing dependency in it would install an
ONNX runtime and a vector-store client into the web process to serve a page.
The same argument the alert webhook already makes - the work belongs to a
process nobody is holding a connection open to.

### The reconciler is one process, and startup is not a special case

A separate startup job *and* a separate reconciler would be two deployment units
running the same function, so they are one process: a reconcile loop that
compares the two shas and closes the gap. On a cold start actual state is empty,
so the first pass is a backfill - not a different job, just the first
reconciliation. Its healthcheck goes green once the index is current, and the
services that read the index depend on that condition, which is how "the index
exists before anything queries it" stays a real gate rather than an assumption.

Running it inside the existing incident worker was rejected: that worker is busy
for the length of a walk, and a push landing mid-incident would wait out the
investigation it was supposed to inform.

The loop wakes on a timer rather than on the webhook. The webhook could notify
it, and that would only shorten the wait - a reconciler that is only ever woken
by an edge is edge-triggered wearing a reconciler's name, and the property worth
keeping is that it converges whether or not anything told it to.

### Chunks are units of code, and a hit reads like a search hit

Python files are cut at top-level `ast` boundaries - each `FunctionDef` and
`ClassDef` its own chunk, module-level remainder its own - so a retrieved passage
is a thing with a name rather than forty arbitrary lines. Everything else falls
back to overlapping line windows.

Each chunk carries its path and line span, and the retrieval tool answers in
`path:start-end` form followed by the passage. That is deliberately close to what
`search_repository` already returns: the model's next move after either tool is
`read_repository_file`, and a second answer shape to learn buys nothing.

### The retriever is read-tier, and which one is in play is configuration

Retrieval is a repository read, so it belongs on `argus-read-mcp` beside the
other three: `search_repository_by_meaning(description, limit)`. No `ref`
parameter - the index is current as of what it is current as of, and a caller
naming a ref would be asking a question the store cannot answer.

Code-Fix's tool list is then assembled from configuration: substring only,
semantic only, or both. Both are retained in the code whichever is configured,
because §21's question is which wins and a replaced implementation cannot be
compared to anything.

### An index that is behind says so

When `indexed_sha != pending_sha`, the retrieval tool prefixes its answer with
the fact and both shas, and Code-Fix's opening message states it. The agent is
then reading passages that may not be the deployed code, and it is told rather
than left to find out by proposing a patch against a file that has moved.

This follows the rule the investigation loop already runs on: a bound or a
limitation the model cannot detect from the inside is stated as a fact in the
message, because nothing about the model's own confidence will reveal it.

## Risks / Trade-offs

- **A small general-purpose model retrieves worse on code than a specialized
  one.** → Accepted, and stated above as the price of local and free. The
  embedding call is an injected seam, so the alternative is testable without
  rebuilding the index pipeline.
- **The index is behind and the agent patches code that moved.** → The drift is
  detected and stated, the substring search over live GitHub is still in the tool
  list, and the patch lands on a branch a human reads before merging.
- **The model weights are a download at image build.** → Baked into the image
  rather than fetched at start, so a build is the only thing that needs the
  network and CI does not embed against a cold cache.
- **Qdrant is another container in a stack that already runs services as host
  processes.** → It makes the dockerizing debt more visible rather than worse;
  Qdrant has no host-process mode worth having.
- **A new publicly reachable endpoint.** → HMAC verification before anything is
  read from the body, constant-time compare, and the only state it can move is
  one string in one row.
- **`e2e_replay` has no real GitHub to push.** → The `github_double` already
  serves the repository archive; the webhook is exercised by posting a signed
  payload at it, which is the real path end to end minus the sender.
- **Two vector stores in one system looks like indecision.** → Named in the
  design above so the report can say why, rather than being discovered as an
  inconsistency.

## Open Questions

- Whether the benchmark runs both retrievers over the same recorded incidents or
  needs new scenarios written for cases where substring search is expected to
  fail. §21's to answer when the dimension is added.
- Whether the read tier should expose the watermark as its own tool, rather than
  prefixing it onto every retrieval answer.
