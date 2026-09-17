"""The recordings the cross-module suites replay, by the names they are stored
under in modules/anthropic_double/recordings/.

Here rather than in each file because two suites now answer from the same one
and mean the same thing by it: any real tool-use turn, for a test whose subject
is the pipeline around the answer rather than the answer.

The `grep-` prefix is the mode the walk that produced it was captured under -
every recording carries one, since a mode decides which tools the walk was
offered and so what it answered. Which mode this is does not matter here: what
these suites want is a real Anthropic body with a real tool-use block in it, and
every mode's recordings are that. It is spelled out rather than composed from
settings for the same reason the name is: this is a file on disk, chosen once,
and a suite that picked its evidence from an environment variable would pass or
fail by how the machine was configured.

Deliberately not shared with `tests/e2e/framework/argus.py`, which names the
same case. There it means "the recording that answers for the flag-toggle
scenario", is chosen to match what the Target Service was seeded with, and is
prefixed by the mode the stack is running; here it means "a turn the model
actually took". Same value, two facts - and the day one of them needs a
different recording, a shared constant would silently move the other.
"""

from __future__ import annotations

RECORDED_TOOL_USE_TURN = "grep-feature-flag-toggle"
