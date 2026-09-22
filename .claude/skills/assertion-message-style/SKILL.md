---
name: assertion-message-style
description: Use when writing or reviewing the message in an AssertionError anywhere in this workspace - a test's own assertion, a framework assertion, or one in argus_testkit. Covers what a failure message has to tell a reader, and the capital-and-full-stop convention the suite is written in.
---

## Say what was expected, then what came back

```python
raise AssertionError(f"Expected the route [{expected}], got [{route}].")
```

Both halves, in that order, with the actual value bracketed so an empty string
and a missing one are visibly different. A message that says only "the route was
wrong" makes the reader open the test to find out what it wanted; one that says
only `[mitigate]` makes them open it to find out what that was.

Brackets around every interpolated value, including the expected one. `Expected
[], got [None]` is a readable failure; `Expected , got None` is a puzzle.

## A capital and a full stop

The suite is a wall of these, read in a hurry. What makes one scannable is that
they all open and close the same way.

- **Start with a capital.** Usually `Expected`.
- **End with a full stop**, unless the message ends on an interpolated value - a
  rendered list, mapping or repr. A stop after `{...}` reads as part of the
  value rather than as punctuation, so leave it off.

`uv run python scripts/check_assertion_style.py` reports both, and reports only -
this is a convention with real exceptions, not a contract.

## Name the subject, not the operation

`the_route_is` raises "Expected the route [...]", not "Expected [...]". The
assertion's own name carries the subject at the call site, and its message has
to carry it again in the failure output, where the call site is not visible.

This is also the test for whether a named assertion earns its place over the
generic `the_answer_was`: if the message would say nothing the generic one does
not, use the generic one.

## Distinguish the failures the caller acts on differently

An assertion that folds two failures into one message costs a reader the thing
they most need. Where absence and wrongness are different problems, say which
happened:

```python
if current is None:
    raise AssertionError(f"Expected incident [{expected}] to be current, got none.")

if current.id != expected:
    raise AssertionError(f"Expected incident [{expected}] to be current, got [{current.id}].")
```

Nothing current at all is a front page with no incident on it. The wrong one is a
front page confidently showing the wrong incident. `assert current is not None and
current.id == expected` reports neither.

## Report every wrong field, not the first

When a claim spans several fields, collect the mismatches and raise once:

```python
wrong = {
    field: (expected, getattr(change, field))
    for field, expected in wanted.items()
    if getattr(change, field) != expected
}
if wrong:
    raise AssertionError(f"Expected {wanted}, and {wrong} differed (expected, got).")
```

A run of separate `assert`s stops at the first, so a change with the right
revision at the wrong minute reports whichever happened to be checked first. This
is the same reason the house rule prefers `all_of(...)` over consecutive asserts.

## Related

- `test-naming-style` - naming the values that end up inside these messages.
- `unit-and-component-boundaries` - where an assertion belongs once it is shared.
