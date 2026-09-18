"""What earlier incidents were done about, kept for the ones that come after.

A cause is re-derivable. The metrics and the logs of the incident in front of
you say what broke, and an investigation given long enough will reach it without
help. What was *done* is not re-derivable at any budget: that Argus set this
flag and the service did not recover exists nowhere except in the record of the
incident that tried it.

So this is not a memory of what incidents were. It is a memory of what was
tried, and what each attempt reached - the one thing a later walk cannot work
out for itself, held where the walk that chooses the next action can read it.

Nothing depends on it. A store that is empty, unreachable or switched off leaves
every decision it informs with the answer it would have had anyway, because a
system that stalled over a cache of old incidents would be worse than one with
no memory at all.
"""

from __future__ import annotations

__all__: list[str] = []
