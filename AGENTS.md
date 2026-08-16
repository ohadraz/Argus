# Agent Instructions

## Tests are off-limits to AI coding agents

Any AI coding agent operating in this repository - Claude Code, or any other tool -
must never create, edit, or delete a test file. This applies to every `tests/`
directory in the repo: root `tests/`, every `modules/*/tests/`, and
`benchmark/tests/`.

Argus is built test-first: a human writes the test for the next unit of behavior,
the coding agent implements against it. That division only holds if it's a hard
rule, not something the agent is trusted to remember - so if you believe a test is
missing, wrong, or needs to change, do not write it. Propose it as text/diff in
your response instead, and wait for a human to add it.

This is a policy about how Argus's own codebase gets built - it has nothing to do
with what Argus does at runtime, and does not apply to Argus's own Code-Fix
sub-agent, which writes tests freely in the separate `argus-target-service` repo
(see spec §7.4, §13, §18.3 for the distinction).

Full context: spec §18.3 (`docs/spec-and-architecture.md`).
