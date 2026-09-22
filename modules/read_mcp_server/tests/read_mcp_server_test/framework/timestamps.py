"""The minute a retrieval window is named by, spelled the way the tools spell it.

Two of this module's suites build the same timestamps, and the format is the
one thing about them that must not drift: a window whose bounds are written
differently from the bucket ids they are compared against is a window that
matches nothing, and the tool answers with an empty list rather than an error.
"""

from __future__ import annotations

from datetime import datetime

# What the read tier writes and reads. The same spelling `argus_core.timestamps`
# produces, restated here rather than imported so a test that builds a bound by
# hand is not built out of the code it is checking.
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def an_iso_minute(minute: datetime) -> str:
    """One instant, written to the second as the tools write it."""
    return minute.strftime(TIMESTAMP_FORMAT)
