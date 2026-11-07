"""What is kept of an incident once it is over.

Three fields do the finding and one does the telling. The description is what a
later incident is compared against, the service and the alert name are what a
search narrows to before it compares anything, and `tried` is the whole reason
any of it is stored.

Deliberately not a summary. Nothing here says what the cause turned out to be,
because a later investigation derives that from its own evidence and would be
worse off believing an earlier one's answer about a different incident.
"""

from __future__ import annotations

from argus_core.models import WhatWasTried
from pydantic import BaseModel


class RememberedIncident(BaseModel):
    """One finished incident, as a later one can use it.

    `described_as` is the text that is embedded and searched. It carries the
    alert's own words as well as what Argus observed, so one vector answers both
    how the monitoring named it and what it looked like - two incidents that
    mean the same thing are rarely spelled the same way, and the alert name
    alone is the spelling.

    `service` and `alert_name` are kept beside it as themselves rather than only
    inside the description, because narrowing to them is an exact question and a
    vector store answers exact questions badly.
    """

    incident_id: str
    described_as: str
    service: str
    alert_name: str
    tried: list[WhatWasTried]
