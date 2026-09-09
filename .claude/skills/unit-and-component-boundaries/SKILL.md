---
name: unit-and-component-boundaries
description: Use when deciding what a test file covers, where a new test belongs, whether a collaborator should be injected, or when a module's test drives the whole package through its front door instead of the module itself. Covers test-file mirroring, injection seams for internal collaborators, and when a test is `component` rather than `unit`.
---

## One test file per source module, named after it

`modules/<module>/tests/<module>_test/test_<source module>.py`. `writing.py` is
covered by `test_writing.py`, `assumptions.py` by `test_assumptions.py`.

The point is navigational: a reader who does not understand `measuring.py` opens
`test_measuring.py` and finds out what it is for. A file named after a behaviour
(`test_absent_figures.py`) cannot be found that way, and its tests drift into
covering four modules at once.

Modules with no behaviour - a package `__init__.py`, a file of pydantic models,
a file of `Protocol` aliases - get no test file. Nothing to describe.

## A test's `when` calls the thing under test, directly

```python
.when(
    lambda: assumptions_of(an_answer, a_measured_incident(), NOBODY_RESPONDED,
                           DONT_CARE_BANDS, DONT_CARE_COST, DONT_CARE_WORKING_YEAR)
)
```

Never through a local wrapper (`_the_assumptions_of(...)`) that fills in
arguments the test would otherwise have chosen. The wrapper hides the call, so
a reader cannot see what is being tested or with what, and a signature change
becomes invisible at every call site.

**Unless** the wrapper hides only what *no* test in the file varies. Then it is
naming the act rather than concealing a choice, and it has to keep being that:

- named for the act under test (`a_postmortem_written_with`), so the `when`
  still reads as a call to the thing being tested
- taking every argument any test in the file varies, so nothing steering the
  outcome is invisible at the call site
- holding no branching of its own

A wrapper that grows a flag, or a parameter one test sets and the others do not,
has stopped naming the act and become a second implementation of it. Split it
back into direct calls at that point rather than adding the argument.

Builders build *values* - `a_measured_incident()`, `an_evidence_bundle()` - and
a builder earns its place when the value has more fields than the test cares
about. A builder is not a wrapper: it returns a thing, it does not perform the
act under test. Everything the test does not care about is a named
`DONT_CARE_*` constant at the top of the file, which reads at the call site
exactly as loudly as it should.

## A collaborator a module *delegates to* gets an injection seam

The test is not "does it have its own test file" - it is whether the caller
hands the work over or does the work.

`writing.py` delegates: it does not measure the incident, ask the model or
compose the disclosures, it arranges what three other modules answered. Each of
those three is injected into `write_postmortem` as a default-argument parameter
typed as a `Protocol` (see `test-mocking-style` for the mechanics). Otherwise
`test_writing.py` re-tests every disclosure through a finished document, and the
same scenarios exist twice at two levels of indirection.

`measuring.py` does not delegate: pricing a response at a band *is* measuring
it, so it calls `responder_cost` and `loss_between` directly and its tests
assert real figures - even though both have test files of their own. A seam
there would let `measure` pass its own tests while measuring nothing.

Ask which sentence is true:

- "this module decides X by asking Y" - Y is a seam
- "this module computes X, partly by calling Y" - Y is not

A module with no seams at all is the common case and not a smell. The seams
appear at the joints where responsibility changes hands, which in a well-split
package is one module in five, not five in five.

With the seam in place the two files split cleanly:

- `test_assumptions.py` says **what the disclosures are**, calling the function.
- `test_writing.py` says **that what came back was arranged onto the document**,
  with the collaborator mocked. One test, not fifteen.

With the seam in place, a module that delegates has no figures of its own to
assert, and that is the sign it was the right call: what is left to test is
exactly what it does.

## The whole package through its front door is `component`, not `unit`

`unit` is one source module with its collaborators mocked. `component` is
**one `modules/<module>` package entire, through its own public API, with only
the infrastructure it cannot fake brought up around it** - every internal
collaborator real, only the ports faked.

An agent whose dependencies are all ports (`Revenue`, `Metrics`, `LLMClient`)
needs no infrastructure at all, so its component test is an ordinary fast test
with no database and no marker cost. It lives in
`modules/<module>/tests/<module>_test/component/`, named for the package rather
than for a source module, and it is where the real end-to-end figures are
asserted - the arithmetic actually reaching the actual document.

It is `integration` only if it spans two packages.

## When a signature grows past readable, group the parameters that travel together

Six ports passed separately to one function, where every real caller passes the
same six from the same place, are not six arguments - they are one value the
caller happens to have spelled out. Give it a name (`Sources`) and a frozen
dataclass in the module that already names the concept.

The test is the call site: if every production caller sets the same group in one
place and only one argument varies per call, that group is a value object. This
is what keeps a function injectable without its signature reaching fourteen
parameters.
