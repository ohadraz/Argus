"""The whole postmortem as a reader reads it: its title, its head, and every
section under its heading, in the order of Google's example postmortem - what
happened and for how long before why.

What is read off the record rather than the document - a person's resolution -
is read here, once, and handed to every part that says it.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final

from argus_core.events import IncidentEvent
from argus_core.models import Alert, Postmortem
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.action_items import ActionItemsSection, the_action_items
from postmortem_rendering.actions_taken import ActionsTakenSection, the_actions_taken
from postmortem_rendering.cause import CauseSection, the_cause
from postmortem_rendering.cost import the_cost
from postmortem_rendering.detection import DetectionSection, the_detection
from postmortem_rendering.head import Head, a_head, a_title
from postmortem_rendering.hypotheses import HypothesesSection, the_hypotheses
from postmortem_rendering.impact import Card, ImpactSection, the_impact
from postmortem_rendering.leads import LeadItem, the_leads
from postmortem_rendering.lessons import LessonList, the_lessons
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.resolution import the_reported_resolution
from postmortem_rendering.review import ReviewSection, the_review
from postmortem_rendering.supporting import SupportingSection, the_supporting_information
from postmortem_rendering.timeline import TimelineSection, the_timeline
from postmortem_rendering.trigger import TriggerSection, the_trigger

# Every section by the name a destination knows it by, and the heading it is
# shown under, in the order it is read.
_HEADINGS: Final = {
    "summary": "Summary",
    "impact": "Impact",
    "cause": "Root cause and contributing factors",
    "hypotheses": "Hypotheses considered",
    "trigger": "Trigger",
    "resolution": "Resolution",
    "detection": "Detection",
    "action-items": "Action items",
    "lessons": "Lessons learned",
    "timeline": "Timeline",
    "leads": "What people told Argus",
    "response-cost": "Cost of the response",
    "supporting": "Supporting information",
    "review": "Review checklist"
}


class RenderedPostmortem(BaseModel):
    """Everything a postmortem says, worked out once for every destination.

    `headings` names each section shown, in order, by the key a destination
    knows it by - every section but what people told Argus, which an incident
    nobody wrote in has none of.
    """

    model_config = ConfigDict(frozen=True)

    incident_id: str
    title: Line
    head: Head
    headings: dict[str, str]
    summary: Line | None
    summary_absent: str | None
    impact: ImpactSection
    cause: CauseSection
    hypotheses: HypothesesSection
    trigger: TriggerSection
    actions_taken: ActionsTakenSection
    detection: DetectionSection
    action_items: ActionItemsSection
    lessons: tuple[LessonList, ...]
    timeline: TimelineSection
    leads: tuple[LeadItem, ...]
    cost: tuple[Card, ...]
    supporting: SupportingSection
    review: ReviewSection

    @property
    def labels(self) -> frozenset[str]:
        """Every label a row of the document goes by - a hypothesis, a step
        taken, an action item, a labelled line of the timeline, a change or a
        log message read, a lead - and so every label the prose can cite with
        a row to lead to."""
        return frozenset({*(row.label for row in self.hypotheses.rows),
                          *(step.label for step in self.actions_taken.steps if step.label),
                          *(row.number for row in self.action_items.rows),
                          *(row.label for row in self.timeline.rows if row.label),
                          *(row.label for row in self.supporting.changes),
                          *(row.label for row in self.supporting.log_messages),
                          *(lead.label for lead in self.leads)})


def render(postmortem: Postmortem,
           alert: Alert,
           events: Sequence[IncidentEvent],
           incident_address: str) -> RenderedPostmortem:
    """A written postmortem as it is read, with a person's resolution taken
    from the incident's `events` and every link to the incident written from
    `incident_address`, its page's full address."""
    resolution = the_reported_resolution(events)
    leads = the_leads(postmortem)

    return RenderedPostmortem(
        incident_id=postmortem.incident_id,
        title=a_title(postmortem, alert),
        head=a_head(postmortem, alert, resolution),
        headings={key: heading for key, heading in _HEADINGS.items()
                  if key != "leads" or leads},
        summary=(Line(runs=(Run(text=postmortem.executive_summary, role=Role.PROSE),))
                 if postmortem.executive_summary else None),
        summary_absent=None if postmortem.executive_summary else "No summary was written.",
        impact=the_impact(postmortem, alert),
        cause=the_cause(postmortem),
        hypotheses=the_hypotheses(postmortem),
        trigger=the_trigger(postmortem, alert),
        actions_taken=the_actions_taken(postmortem, resolution),
        detection=the_detection(postmortem, alert),
        action_items=the_action_items(postmortem),
        lessons=the_lessons(postmortem),
        timeline=the_timeline(postmortem),
        leads=leads,
        cost=the_cost(postmortem),
        supporting=the_supporting_information(postmortem, incident_address),
        review=the_review(postmortem))
