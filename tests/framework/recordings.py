from __future__ import annotations

"""The recordings the cross-module suites replay, by the names they are stored
under in modules/anthropic_double/recordings/.

Here rather than in each file because two suites now answer from the same one
and mean the same thing by it: any real tool-use turn, for a test whose subject
is the pipeline around the answer rather than the answer.

Deliberately not shared with `tests/e2e/framework/argus.py`, which names the
same string. There it means "the recording that answers for the flag-toggle
scenario" and is chosen to match what the Target Service was seeded with; here
it means "a turn the model actually took". Same value, two facts - and the day
one of them needs a different recording, a shared constant would silently move
the other.
"""

RECORDED_TOOL_USE_TURN = "feature-flag-toggle"
