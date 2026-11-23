"""The executive synopsis (spec §7.6): the incident in one paragraph, for a reader
who will read nothing else.

Written from the stored postmortem rather than beside it - in `synopsis_writing`,
which asks the model once, in `synopsis_conversation`, under the policy and the
ask in `synopsis_prompting`, and checks what comes back in `synopsis_checking`.
Its figures are written, and its claims judged, by the Postmortem Writer's own
engine and judge (`postmortem_writing`), which never knows this package.
"""

from __future__ import annotations

from executive_synopsis.synopsis_prompting import (
    OVERVIEW_FIELD,
    OVERVIEW_TOOL_NAME,
    synopsis_policy,
)
from executive_synopsis.synopsis_writing import write_executive_synopsis

__all__ = [
    "OVERVIEW_FIELD",
    "OVERVIEW_TOOL_NAME",
    "synopsis_policy",
    "write_executive_synopsis"
]
