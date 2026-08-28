# Agent Instructions

## Tests and test infrastructure are off-limits to AI coding agents

Any AI coding agent operating in this repository - Claude Code, or any other tool -
must never create, edit, or delete a test file. This applies to every `tests/`
directory in the repo: root `tests/`, every `modules/*/tests/`, and
`benchmark/tests/`. It applies equally to all of `modules/argus_testkit/`, the
shared test-support module, and to all of `modules/anthropic_double/`, the
record/replay stand-in for the Anthropic API.

The testkit holds no test cases, but many assertions in the repo runs through it.
An agent able to edit it could turn the whole suite green from one file - by
making, for example, `all_of` swallow failures, or, for example, `eventually` 
succeed on timeout - without touching anything named like a test. A rule that stops 
at `tests/` would leave that open.

The double is the same hazard one level down. Every integration and contract
test judges the adapter against what the double replays, so an agent free to
reshape a recording could make its own code pass without the adapter ever
being right - and the recordings are exactly the evidence that it is. Claude
built the double while the change was in flight; the door closed once the
adapter landed, and it stays closed.

Argus is built test-first: a human writes the test for the next unit of behavior,
the coding agent implements against it. That division only holds if it's a hard
rule, not something the agent is trusted to remember - so if you believe a test is
missing, wrong, or needs to change, do not write it. Propose it as text/diff in
your response instead, and wait for a human to add it.

This is a policy about how Argus's own codebase gets built, and it stops at this
repository's edge. It has nothing to do with what Argus does at runtime, and it
does not apply to Argus's own Code-Fix sub-agent, which writes tests freely in
the separate demo Target Service repo (see spec §7.4, §13, §18.3 for the
distinction).

Nor does it apply to an agent working on that repo as a developer. The demo
Target Service is a fixture, held to different standards than Argus, and its
tests are a regression net written after the code rather than a specification
written before it - so an agent writes them directly there. Test-first is a
claim about how Argus's behavior gets decided, and nothing about a fixture's
behavior is decided that way.

Full context: spec §18.3 (`docs/spec-and-architecture.md`).

## Private means private, and tests are not an exception

A leading underscore marks a name as belonging to its own module. Nothing outside
that module may import it, call it, or reference it - not other production code,
not tests, not "only in a test". Python declining to enforce access is not
permission to work around it; the marker is a contract about what may be depended
upon, and a test that depends on a `_name` has broken it exactly as a caller would.

When a test appears to need a private name, the design is telling you the unit
under test has no public API. Fix the code, not the test: extract the logic into a
module or function whose published interface *is* the thing being tested, and
leave behind as private only what genuinely is - a transport wrapper, an
adapter, a formatting detail. Widening a test's reach in place of widening the
code's API hides a missing seam and produces tests that pin implementation
details rather than behavior.

This applies symmetrically to a class's private methods and attributes, and to
a package's private modules.
