"""Everything the page is shown, and the builders that shape it.

One module per subject: the incident's own rows, the postmortem, the narration
a reader follows, the story that gathers what it read, and the tables that
story is made of. The two at the bottom - `clock` and `prose` - are how a
recorded value is said out loud, and every other module here goes through them
so that one instant is not written two ways on one screen.

Nothing in here reaches a database or renders HTML. A view takes rows and
returns values; `reads` fetches the rows and the templates put tags around what
comes back.
"""

from argus_web.views.findings import Finding
from argus_web.views.flags import FlagToggleRow
from argus_web.views.incidents import (
    Attempt,
    Candidate,
    IncidentDetail,
    IncidentSummary,
    TimelineEntry,
    build_incident_detail,
    build_incident_summary,
)
from argus_web.views.logs import LogLine
from argus_web.views.metrics import BucketRow
from argus_web.views.narrating import CandidateLine, NarrationLine, build_narration
from argus_web.views.postmortems import PostmortemView, build_postmortem_view
from argus_web.views.storytelling import (
    LiveIncident,
    Story,
    build_live_incident,
    build_story,
)

__all__ = [
    "Attempt",
    "BucketRow",
    "Candidate",
    "CandidateLine",
    "Finding",
    "FlagToggleRow",
    "IncidentDetail",
    "IncidentSummary",
    "LiveIncident",
    "LogLine",
    "NarrationLine",
    "PostmortemView",
    "Story",
    "TimelineEntry",
    "build_incident_detail",
    "build_incident_summary",
    "build_live_incident",
    "build_narration",
    "build_postmortem_view",
    "build_story",
]
