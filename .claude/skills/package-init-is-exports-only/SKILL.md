---
name: package-init-is-exports-only
description: Use when adding a function, class, or constant to a package's `__init__.py` under `modules/*/src/`, or when deciding where a module's entry-point function should live. An `__init__.py` carries a docstring, imports and `__all__` - never logic.
---

A package's `__init__.py` states what the package offers. It never implements it.

Allowed, and nothing else:

- a module docstring, saying what the package is and naming the modules that do the work
- `from __future__ import annotations`
- `from <package>.<module> import ...`
- `__all__`

Not allowed: `def`, `async def`, `class`, or any assignment other than `__all__`
- including a type alias, a constant, and a "it's only three lines" helper.

## Where the logic goes instead

A module named for what it does, beside its siblings. The package's entry point
is not special and does not get to live in the doorway: `write_postmortem` lives
in `agent_postmortem/writing.py` and is re-exported, exactly as `PostmortemDocument`
lives in `document.py` and is re-exported.

Name the module for the work, following whatever the package already does -
gerunds (`writing.py`, `checking.py`, `mitigating.py`, `undoing.py`) where the
module is an activity, plain nouns (`document.py`, `sources.py`, `estimate.py`)
where it is a thing.

## Why

Three reasons, in the order they bite:

- **A test file has somewhere to point.** Tests mirror source modules
  (`test_<module>.py`), so a reader who does not understand `writing.py` opens
  `test_writing.py`. Logic in `__init__.py` has no such counterpart - the file
  named after it would be a test for the package's export list.
- **Importing the package runs it.** Anything reaching for one name in the
  package executes every statement in `__init__.py`, so a helper there is
  evaluated by importers that will never call it.
- **It stops being an export list.** The file that answers "what does this
  package offer" only answers it while that is all it contains; three hundred
  lines in, the exports are something to scroll past.

## Fixing an existing one

Move the definitions into a new module, leave the imports and `__all__` behind,
and change no callers: a package re-exporting the same names has the same public
API, so `from agent_postmortem import write_postmortem` keeps working and
`agent_communicator.post_update` still resolves for `create_autospec`.
