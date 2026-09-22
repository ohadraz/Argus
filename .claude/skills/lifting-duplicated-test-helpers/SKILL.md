---
name: lifting-duplicated-test-helpers
description: Use when the same test helper is defined in more than one file and you are deciding whether and where to share it - or when running `scripts/find_duplicate_helpers.py` and acting on what it reports. Covers which destination each kind of helper belongs in, which duplicates to leave alone, and the renaming traps that break suites silently.
---

## Find them with the script, decide with this

`uv run python scripts/find_duplicate_helpers.py` lists every helper defined
identically in two or more test files, already sorted into four buckets. It
reports and exits zero - a duplicated builder is not a build break the way a
broken layering contract is.

The script picks the bucket. It cannot pick the destination *within* a bucket,
and that is the decision worth getting right.

## Duplication in a builder is cheap; duplication in infrastructure is not

This is the whole of it. Two suites that each build a two-line `an_alert()` are
not coupled to one another, and forcing them to share one couples them for the
first time. Two suites that each stand up a database, drive an app, or parse a
vendor's payload are already coupled - to the infrastructure - and a second copy
is a second thing that can drift from what the infrastructure actually does.

So: **lift infrastructure, leave data.** When a duplicate is a fixture, a driver,
a parser or an assertion two suites make the same claim with, lift it. When it is
a value somebody made up so a test had something to pass, leave it.

## Where each kind goes

**A `@pytest.fixture` shared inside one module goes to that module's
`conftest.py`** - never to `framework/`. pytest only looks in conftest, and being
a fixture is what guarantees each test gets a fresh one. Moved into a framework
module it becomes an ordinary function every caller must remember to call, and
the first test that reuses one carries the previous test's calls into it.

**A builder shared inside one module goes to `framework/builders.py`.** A helper
that makes a value the tests pass in.

**An assertion shared inside one module goes to `framework/assertions.py`.** A
helper returning `Assertion[T]`.

**Something that drives the system under test goes in its own framework module** -
`reading.py`, `pages.py`, whatever it is. It is not an assertion: it answers a
question and leaves the judging to the assertion. Keeping the two apart is what
stops a "driver" quietly asserting something nobody asked it to.

**Shared by the root suites only goes to `tests/framework/`.**

**Shared across modules AND carrying no package goes to `argus_testkit`.**

**Shared across modules but carrying a package stays where it is.**
`argus_testkit` declares `dependencies = []` and imports nothing outside itself.
That is load-bearing, not an accident: it is the vocabulary every suite is
written in, and depending back on the code under test would close a cycle.
`orchestrator`'s own `conftest.py` says so in its docstring. Four copies of
`_an_alert()` is the cheaper thing to own.

A helper whose *name* carries Argus's vocabulary is domain-bound even when its
imports are empty. `_the_read_tier_was_asked_for` reaches for nothing, but "read
tier" is spec §12.1 - putting it in a generic testkit puts Argus's autonomy tiers
in a library that knows nothing about Argus.

## Before renaming anything, look for the collision

Lifting means renaming: `_the_page_says` becomes `the_page_says`. A blanket
`\bold\b -> new` across a file has broken this suite twice.

1. **Grep the new name in the target file first.** `_attribute` became
   `attribute`, and a local assertion already had a parameter called
   `attribute` - the parameter shadowed the import and every call raised
   `'str' object is not callable`.
2. **Check the shared library for the name.** `argus_web`'s `_the_answer_was`
   collided with `the_answer_was` in `argus_testkit`, and they were different
   assertions - one an equality, one an HTTP status. It became
   `the_response_was`.
3. **Word boundaries are not enough.** `_it_reads` sits inside
   `the_clock_time_it_reads_as`. `\b` happens to save you there because `_` is a
   word character; do not rely on having been lucky.

## The constants section is not a to-do list

The script also reports module-level constants declared under the same name and
value in two files. Most of them are `DONT_CARE_` and `SOME_` test data, and two
suites naming a flag the same thing share nothing - leave them. Read the list for
the few that are infrastructure: a format, a timeout, a configured window.

It is there because a constant sitting beside a duplicated helper is easy to lift
with it and easy to leave behind. `TIMESTAMP_FORMAT` sat next to `_an_iso_minute`
through a pass that moved only the function, and a window whose bounds are spelled
differently from the bucket ids they are compared against matches nothing and
raises nothing.

## When a helper is bound by `partial`, stop scripting and read the files

A helper reached through `partial(_helper, conn)` is the one case where the
substitution approach falls apart, and it does so quietly enough to take four
attempts. `an_incident_created_for` cost exactly that: remove the `partial` by
guessing which argument spellings appear at the call sites, and you miss the
ones spelled differently; fix the file the type checker happened to name first,
and the others are still broken; add the bound argument back with a regex, and
the multi-line calls get it twice; collapse those, and a closing paren goes
missing.

The failure is not the regex. It is patching against the last error message
instead of handling the whole shape at once. So when a lift involves a `partial`,
several consumers, or call sites in more than one layout: open each file and
rewrite it, and let the gates confirm rather than discover.

The tell is cheap to check before starting - `grep -c` the helper's name per
file, and look for `partial(`. More than two consumers, or any binding, means
read them.

## Two more things that cost a rerun

**Insert the new import after the last import *statement*, not the last line
that starts with `from`.** A parenthesised import spans several lines, and
anchoring on the line lands the new import inside the block.

**Never `rmtree` a scratchpad tree you have hand-edited.** Make the whole
transform reproducible from a script instead, so rerunning it costs nothing.

## Verify per module, not at the end

Copy one module's change set, then `lint`, `typecheck` and that module's suite
before starting the next. Both breakages above were found this way and would
have been far harder to place in a nine-module diff. Expect
`uv run ruff check --fix .` to be needed for import ordering and for imports that
were only used by the helper you removed.

## Related

- `test-naming-style` - what a helper should be called once it is shared.
- `unit-and-component-boundaries` - which file a test belongs in at all.
