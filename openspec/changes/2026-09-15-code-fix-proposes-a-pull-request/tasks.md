Tests are the user's to write throughout (`AGENTS.md`): each task below that
names a test means proposing it whole in chat, having it added, watching it
fail, and only then writing the code under it. `Argus-Demo-Target-App` is the
exception - it is a fixture, and its tests are a regression net written after
the code rather than a specification written before it.

## 1. Something to fix

The flag scenario already carries a real fault in real code, so Code-Fix does
not get a scenario of its own. The walk is: Mitigation reverts the flag and buys
time, then Code-Fix patches the fault so the flag is safe to turn back on.

- [x] 1.1 The demo app's suite is green on `main` with the fault still in it and
      no test covering it - a bug nobody has written a test for, which is the
      ordinary condition of real code and the condition Code-Fix is built to
      meet. Writing the test that exposes it is part of the fix.
- [x] 1.2 Tests that merely needed *a* failure ride the lifetime path with an
      account that never bought anything - a divisor that stays empty after the
      patch, so the boundary's own property does not report itself broken on
      the branch that fixed the bug.
- [x] 1.3 The `tests/` write ban is scoped to the Argus repository, matching the
      hook that already was, and the hook is reachable from any working
      directory.

## 2. The write tier

- [x] 2.1 Propose the test: a pull request is opened as a draft, from the
      branch carrying the fix onto the branch it fixes, under the credential
      that can write, and a repository that refuses is never reported as a
      proposal.
- [x] 2.2 `write_mcp_server.pull_requests`: `open_pull_request`, draft not a
      parameter, `OpenedPullRequest` declared in `argus_core.models` because
      four parties name it.
- [x] 2.3 Propose the test: a fix gets a branch off the base branch's head,
      every file is written to that branch, an existing file names the blob it
      replaces and a new one names none.
- [x] 2.4 `write_mcp_server.branching`: `commit_to_new_branch`, whole files
      rather than a diff, and no path withheld - the test exposing the bug is
      the half of a patch worth having.
- [x] 2.5 Both registered on the server and exposed as typed client functions.
      No `merge_pull_request` anywhere, on either side.
- [x] 2.6 `Settings`: the repository, the API url, and the credential that can
      push - in `.env.example` with what each one is for.

## 3. The read tier

- [x] 3.1 Propose the test: the repository's files are listed from a ref,
      directories are left out, a file is read as text, and a listing the API
      truncated is refused rather than offered as the whole.
- [x] 3.2 `read_mcp_server.repository`: `list_repository_files` and
      `read_repository_file`, under a read-only credential, raising rather than
      answering emptily for a path that is not there.
- [x] 3.3 Registered on the read server and exposed as typed client functions.
- [x] 3.4 `Settings`: the read credential, documented as read-only on purpose.

## 4. The agent

- [x] 4.1 Propose the test: a submitted fix is read by attribute, a prose field
      that arrived as a number is written out, and a malformed file entry costs
      that entry and nothing else.
- [x] 4.2 `agent_codefix.prompting`: `SubmittedFix`, whole files rather than a
      diff, an empty patch parsing as the real answer it is.
- [x] 4.3 Propose the test: the model is told what the investigation concluded,
      its reads are answered, a submitted patch is written to a branch named
      for the incident and proposed, and a fix proposing no files proposes
      nothing.
- [x] 4.4 `agent_codefix.proposing`: the loop, bounded by turns, with the four
      repository ports as seams and `fixes_over` binding both tiers at the
      composition root.
- [x] 4.5 The walk's `ProposeFix` port returns a pull request; the node reports
      where it can be read, and survives a repository that refused - an
      unreachable GitHub is a bad afternoon, not a lost incident.

## 5. Mitigated

- [x] 5.1 Propose the test: a mitigated incident has nowhere left to go.
- [x] 5.2 `IncidentStatus.MITIGATED`, terminal, with `resolved` documented as
      the state Argus cannot reach on its own.
- [x] 5.3 Propose the test: a confirmed action mitigates rather than resolves; a
      fix found without a mitigation still escalates; and an incident that was
      mitigated and then had a fix proposed stays mitigated.
- [x] 5.4 `status_after` asks "did the symptom stop" first, and derives
      `resolved` nowhere.
- [x] 5.5 Propose the test: a mitigation that worked routes on to look for a
      fix.
- [x] 5.6 `route_after_mitigation` returns the fixing route, and the graph wires
      mitigation to Code-Fix - a second road to a node that had one.
- [x] 5.7 Propose the test: every incident reaching Code-Fix goes on to the
      postmortem. `route_after_codefix` collapses to one destination and
      `RESOLVED_ROUTE` goes away.
- [x] 5.8 The incident page dresses `mitigated`: green because the shop is
      serving, dashed because the incident is not closed.

## 6. End to end

- [ ] 6.1 The e2e suites say `mitigated` where they said `resolved`.
- [ ] 6.2 `e2e_replay`: Code-Fix's turn is seeded with a literal body rather
      than a recording - "no files, the fault is not in the code", which is the
      true answer for a flag scenario. Without it the codefix conversation
      consumes the seed meant for the postmortem, and the postmortem is written
      from somebody else's answer while the suite still passes.
- [ ] 6.3 A live run: `nox -s stack`, the flag scenario staged from the shop's
      console, the flag reverted, the incident `mitigated`, and a draft pull
      request on the demo application's own repository.
- [ ] 6.4 CI and compose carry the repository settings, once the e2e path
      reaches these tools.

## 7. Afterwards

- [ ] 7.1 The RAG retriever behind the same seam, and the benchmark dimension
      that says which retriever wins on which repository.
