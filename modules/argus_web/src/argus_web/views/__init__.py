"""Everything the page is shown, and the builders that shape it.

One module per subject: the incident's own rows, and the story that gathers
what an incident read. The account a reader follows is not here - it is
`argus_narration`, said once for every destination that reports an incident,
and the story arranges what that module renders. Nor is the postmortem: what it
says is `postmortem_rendering`'s, worked out once for the page and the PDF.

Nothing in here reaches a database or renders HTML. A view takes rows and
returns values; `reads` fetches the rows and the templates put tags around what
comes back.
"""

from argus_web.views.incidents import (
    Attempt,
    Candidate,
    IncidentDetail,
    IncidentSummary,
    build_incident_detail,
    build_incident_summary,
)
from argus_web.views.storytelling import (
    LiveIncident,
    Story,
    build_live_incident,
    build_story,
)

__all__ = [
    "Attempt",
    "Candidate",
    "IncidentDetail",
    "IncidentSummary",
    "LiveIncident",
    "Story",
    "build_incident_detail",
    "build_incident_summary",
    "build_live_incident",
    "build_story"
]
