"""Each Argus process's composition root, and nothing else (spec §20.1).

A process starts here - `python -m apps.<process>` - and here alone is it
decided which vendor's adapter answers each port it reads through, and its
telemetry is started. Every library below is handed what it reads as a port
and names no vendor, so swapping one is an edit to the root of each process
that uses it and to nothing else.

Nothing imports a root, and nothing but a root imports an adapter or the
telemetry SDK: one import-linter contract holds both. Each process is one
extra of this package (`argus-apps[web]`, `[worker]`, ...), so installing a
process installs what it runs and nothing beside it - and `guard_layering`
holds each root to the workspace packages its own extra names.
"""

from __future__ import annotations

__all__: list[str] = []
