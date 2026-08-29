---
name: spec-doc-style
description: Use when editing docs/spec-and-architecture.md, to keep it written as a specification rather than a changelog - no "this now exists", no notes appended to paragraphs the design has outgrown.
---

`docs/spec-and-architecture.md` describes Argus's design **as though it were
always the intent**. A reader should not be able to tell from it what was built
first, what was rewritten, or what any individual change added.

## Never write

- "this now exists", "is now implemented", "as of this change"
- "previously X, now Y"
- "the deeper fix is…", "until that exists…", "for now…"
- "TODO", "coming later", or anything else dated
- a note appended to an older paragraph explaining that the paragraph is stale

Each of those records *history*, and history is already recorded - by git and by
`openspec/changes/archive/`. A spec carrying it too says two things at once and
ages badly.

## Instead

**Rewrite the paragraph.** When an older section anticipated something that has
since been built, the section is now wrong about the design, not merely
incomplete: replace it so it describes the design that exists. Deleting a
sentence that is no longer true is not losing information - the change that made
it untrue is in the archive with its reasoning intact.

Write in the present tense, and state constraints as properties of the system
("the read tier holds no credential that can change state"), not as decisions
somebody made ("we decided the read tier should not…").

## Where each thing belongs

| Content | Home |
|---|---|
| how the design works, and why it is that way | `docs/spec-and-architecture.md` |
| what a specific change adds and how it was decided | `openspec/changes/<name>/` |
| what happened, when | git history, `openspec/changes/archive/` |
| the testable statements a capability must satisfy | `openspec/specs/<capability>/spec.md` |

The spec is prose about the whole; the OpenSpec capability specs are the
requirement-and-scenario form of the same design. Keep a claim in one of them,
not both.
