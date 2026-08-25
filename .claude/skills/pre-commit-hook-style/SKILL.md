---
name: pre-commit-hook-style
description: Use when adding or editing a hook in .pre-commit-config.yaml, to avoid duplicating a check that's already running elsewhere.
---

Before adding a new hook to `.pre-commit-config.yaml`:

- Check whether an existing hooks-repo already covers the tool properly (e.g.
  `ruff-pre-commit` for ruff/ruff-format) - prefer that over a `local` hook,
  since dedicated hooks-repos are faster and already integrate with
  changed-files-only behavior by default.
- Only reach for a `local` hook when nothing upstream covers it. Today that's
  mypy, via `entry: uv run python -m nox -s typecheck`, and the e2e test-placement guard, via
  `entry: uv run python -m nox -s guard_e2e_boundary`.
- Don't add a hook that re-runs a check nox already runs elsewhere unless nox
  is genuinely the entry point (as with the two `local` hooks above) -
  duplicate invocations silently double commit time.
