## Why

Code-Fix is the one agent that is still a stub. `propose_fix` returns `None` and
says so honestly, which was the right placeholder while the FSM's shape was
being settled - but it means the only permanent outcome Argus can reach is a
reverted flag, and a reverted flag is a workaround somebody has to come back to.
The fault that caused the incident is still in the code, held off by a toggle.

The state machine has been saying something untrue about that. A confirmed
mitigation records the incident as `resolved`, when what actually happened is
that the symptom stopped. Nothing is resolved: the bug is where it was, and the
flag holding it back is a debt nobody has written down.

Both of those are the same gap. Argus has read tiers, write tiers, an
investigation that names a cause and a mitigation that acts on it - and then
stops one step short of the thing that would let the flag go back on.

## What Changes

- The Code-Fix agent becomes real: it reads the Target Service's source, writes
  a patch, and opens a **draft** pull request against the service's repository.
  It brings a regression test where one can be written.
- Merging remains impossible. There is no `merge_pull_request` on either MCP
  server, and the binding Code-Fix holds has no function for it - tier
  enforcement by absence rather than by a check some later caller could skip
  (§13). What comes back from the agent is an address a human can open.
- The read tier gains the repository's source: what files there are, and what
  one of them says. Under a credential that can only read, so `argus-read-mcp`
  stays incapable of mutation with a repository in it.
- The write tier gains the branch and the proposal. Every path a patch names is
  written, tests included: the test that fails before the fix and passes after
  is the half that shows the fix works, and a tier withholding a path would
  refuse exactly that. What bounds the change is the branch and the human merge.
- **`mitigated` becomes a status of its own.** A confirmed mitigation lands
  there instead of in `resolved`: the symptom stopped and the cause did not. It
  is terminal, because what would resolve it is a human merging the fix, which
  is outside Argus's autonomy and nothing here can wait for.
- A mitigation that worked goes **on** to Code-Fix rather than straight to the
  postmortem, which is what makes the fix reachable on the happy path at all.
  Code-Fix is now arrived at by two roads: Argus having run out of reversible
  moves, and Argus having made one that worked.
- The retrieval seam is one port with room for two implementations. Search and
  read is what the demo runs on; a RAG retriever behind the same seam is the
  alternative, and which one is better on which repository is the benchmark's
  question to answer rather than this change's to assert.

## Capabilities

### New Capabilities
- `code-fix-agent`: what Code-Fix is told, what it may read, the one shape its
  answer takes, and the fact that a proposal is as far as it goes.

### Modified Capabilities
- `read-mcp-server`: a fourth channel - the service's own source - read under a
  credential that cannot write.
- `write-mcp-server`: a branch, a draft pull request, and the fixture path
  neither will write.
- `incident-status-derivation`: `mitigated` exists, a confirmed action reaches
  it, and nothing derives `resolved` any more.

## Impact

- `modules/agent_codefix`: the stub becomes a loop - a prompt, two read tools,
  a submission, then a branch and a proposal.
- `modules/read_mcp_server`, `modules/read_mcp_client`: `list_repository_files`
  and `read_repository_file`.
- `modules/write_mcp_server`, `modules/write_mcp_client`:
  `commit_to_new_branch` and `open_pull_request`.
- `modules/argus_core`: `OpenedPullRequest` as a contract; the repository
  settings and the two credentials; `IncidentStatus.MITIGATED`.
- `modules/orchestrator`: the port widens to return a pull request, the node
  reports where it can be read, and a mitigation that worked routes through
  Code-Fix. `route_after_codefix` collapses to one destination.
- `modules/argus_web`: the incident page dresses `mitigated` - green, because
  the shop is serving, and dashed, because the incident is not closed.
- `Argus-Demo-Target-App`: green on `main` with the fault still in it and no
  test covering it - the ordinary condition of real code, and the one Code-Fix
  is built to meet. Writing the test that exposes the bug is part of the work.

## Non-Goals

- **Merging, or anything that observes a merge.** `resolved` stays reachable
  only in principle; what would set it is a human's action and a trigger that
  does not exist yet.
- **The RAG retriever.** The seam admits it; this change builds the search-and-
  read side, which is what the demo repository needs.
- **Proving the model actually fixes bugs.** This change builds the pipeline.
  Whether a patch is correct is the benchmark's question (§21), answered by
  running the patch's own tests against the base branch and against the fix -
  from outside the repository, so nothing inside it has to be protected.
