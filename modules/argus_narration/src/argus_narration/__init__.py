"""An incident's recorded events, said in words, once for every destination.

The account a reader follows is a rendering of the event stream and nothing
more: every event becomes exactly one line, and nothing here decides what an
event meant, groups two into a conclusion, or drops one it finds uninteresting.

It lives on its own rather than inside the page because the page is not the
only place an incident is read. The dashboard, Slack, and the postmortem all
say what happened, and they say it in the same words - one account rendered
once, rather than three descriptions of one incident that drift apart.

Nothing in here reaches a database or renders markup. It takes events and
values, and returns values; what puts tags around them belongs to whoever is
doing the showing.
"""

from argus_narration.clock import a_minute, a_moment, a_window, is_a_moment
from argus_narration.findings import Finding, a_finding, pointed_at
from argus_narration.flags import (
    FlagToggleRow,
    a_flag_history,
    on_or_off,
    said_as_a_state,
)
from argus_narration.logs import LogLine, a_log_line, the_minutes_logged
from argus_narration.metrics import BucketRow, a_bucket_row
from argus_narration.narrating import (
    CandidateLine,
    NarrationLine,
    a_candidate_line,
    a_narration_line,
    build_narration,
)
from argus_narration.prose import said_plainly

__all__ = [
    "BucketRow",
    "CandidateLine",
    "Finding",
    "FlagToggleRow",
    "LogLine",
    "NarrationLine",
    "a_bucket_row",
    "a_candidate_line",
    "a_finding",
    "a_flag_history",
    "a_log_line",
    "a_minute",
    "a_moment",
    "a_narration_line",
    "a_window",
    "build_narration",
    "is_a_moment",
    "on_or_off",
    "pointed_at",
    "said_as_a_state",
    "said_plainly",
    "the_minutes_logged"
]
