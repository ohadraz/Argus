"""What people told the incident: each thing a person wrote, who and when, what
the investigation made of it, and what it changed - one answer to the person
who wrote it, so the three stay together.

The one section left out rather than said empty: an incident nobody wrote in
has nothing to answer.
"""

from __future__ import annotations

from argus_core.models import PostmortemDocument
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.lines import Line, Role, Run


class LeadItem(BaseModel):
    """One lead. `person_id` names who wrote it, for a destination that marks
    the item with them; `effect` is `None` where the model said nothing of it."""

    model_config = ConfigDict(frozen=True)

    person_id: str
    said: Line
    weighing: Line
    effect: Line | None


def the_leads(postmortem: PostmortemDocument) -> tuple[LeadItem, ...]:
    """Every lead in the order it was written, signed with the writer's name -
    or their id, where the chat platform could not name them."""
    return tuple(
        LeadItem(person_id=lead.person_id,
                 said=Line(runs=(Run(text=lead.text, role=Role.QUOTE),
                                 Run(text=f" - {lead.person_name or lead.person_id}, "),
                                 Run.a_moment(lead.written_at))),
                 weighing=(Line(runs=(Run(text=lead.weighing.standing.value, role=Role.STATUS),
                                      Run(text=f": {lead.weighing.reason}")))
                           if lead.weighing
                           else Line(runs=(Run(text="never weighed", role=Role.STATUS),))),
                 effect=(Line(runs=(Run(text=lead.effect, role=Role.PROSE),))
                         if lead.effect else None))
        for lead in postmortem.leads)
