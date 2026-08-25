---
name: tdd-new-behavior
description: Use when adding new behavior to any module under TDD. Claude proposes the test in chat, the user adds it, Claude implements against it.
---

Given a described behavior to add:

1. Identify the exact test file it belongs in (e.g., `modules/agent-mitigation/tests/test_agent.py`).
2. Print the proposed test function as a code block in chat, using the project's
   pytest marker conventions (`unit` / `integration` / `e2e` / `contract`) and
   existing naming style in that module - including the variable-naming prefixes
   in the `test-naming-style` skill (`some_`, `dont_care_`, `a_`/`an_`).
3. Ask the user to confirm they've added it and that it currently fails (red) -
   do not proceed on assumption.
4. Only after confirmation, implement the corresponding source code in `src/`,
   with full type hints on every function signature.
5. Ask the user to run `uv run python -m nox -s "test_module(module='<name>')"` and confirm green.

Never call Write or Edit on any path under `tests/`, or anywhere under
`modules/argus_testkit/` - both are hook-blocked regardless, but don't attempt
it; go straight to printing the change in chat. A test that needs a new
assertion helper needs *two* proposals: the helper for the testkit, and the
test that uses it.

**A test may only touch public API.** Never propose a test that imports or calls
a `_name` from the module under test - a private name is private to tests as
much as to production callers. If the behavior you want to test is only
reachable through a private function, stop: the missing piece is a public seam,
not a test. Say so, propose the extraction (a module or function whose public
interface *is* the unit), and let the user decide before writing either. Test
files may of course define their own `_helpers`; the rule is about reaching into
someone else's module.

**Mid-implementation comments that reveal a gap**: if the user raises a valid
concern while you're implementing something (e.g. "wouldn't this misattribute
X if the order were different?") and no existing test covers that case, don't
silently implement the fix as if it were an obvious correction. Name the gap,
say it belongs behind a test, and either propose that test now via steps 1-5
above or ask whether to defer it - let the user decide, don't assume.
