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
        taken, an action item, a labelled line of the timeline, a change, a
        log message, what a deployment changed or what Code-Fix read, a lead,
        what the alert said - and so every label the prose can cite with a row
        to lead to."""
        return frozenset({*(label for row in self.hypotheses.rows for label in row.labels),
                          *(step.label for step in self.actions_taken.steps if step.label),
                          *(row.number for row in self.action_items.rows),
                          *(row.label for row in self.timeline.rows if row.label),
                          *(row.label for row in self.supporting.changes),
                          *(row.label for row in self.supporting.log_messages),
                          *(row.label for row in self.supporting.deployment_changes),
                          *(row.label for row in self.supporting.code_read),
                          *(lead.label for lead in self.leads),
                          *((self.detection.said.label,) if self.detection.said else ())})


def render(postmortem: Postmortem,
           alert: Alert,
           events: Sequence[IncidentEvent],
           incident_address: str) -> RenderedPostmortem:
    """A written postmortem as it is read, with a person's resolution taken
    from the incident's `events` and every link to the incident written from
    `incident_address`, its page's full address."""
    resolution = the_reported_resolution(events)
    leads = the_leads(postmortem)
    hypotheses = the_hypotheses(postmortem)
    actions_taken = the_actions_taken(postmortem, resolution)
    action_items = the_action_items(postmortem)
    timeline = the_timeline(postmortem)
    supporting = the_supporting_information(postmortem, incident_address)
    detection = the_detection(postmortem, alert)
    rows = _the_rows(hypotheses, actions_taken, action_items, timeline, leads, supporting,
                     detection)

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
        cause=the_cause(postmortem, rows),
        hypotheses=hypotheses,
        trigger=the_trigger(postmortem, alert),
        actions_taken=actions_taken,
        detection=detection,
        action_items=action_items,
        lessons=the_lessons(postmortem),
        timeline=timeline,
        leads=leads,
        cost=the_cost(postmortem),
        supporting=supporting,
        review=the_review(postmortem))


def _the_rows(hypotheses: HypothesesSection,
              actions_taken: ActionsTakenSection,
              action_items: ActionItemsSection,
              timeline: TimelineSection,
              leads: Sequence[LeadItem],
              supporting: SupportingSection,
              detection: DetectionSection) -> dict[str, Line]:
    """Each label a row of the document goes by, and the line it says itself
    in - so an item the causal chain cites is said the way its own row says
    it, not in the words the model was briefed in.

    A candidate goes by every label it stands for. A step taken has its
    outcome after a colon, the outcome having dashes of its own. A diff is
    named by its first line and what Code-Fix read by its heading: either row
    can run to pages, and the label leads to it."""
    rows: dict[str, Line] = {}
    for candidate in hypotheses.rows:
        said = Line(runs=(*candidate.summary.runs, Run(text=" - "),
                          Run(text=candidate.result)))
        rows |= {label: said for label in (candidate.label, *candidate.also)}

    rows |= {step.label: Line(runs=(Run(text=step.at), Run(text=" "), *step.action.runs,
                                    Run(text=": "), Run(text=step.outcome)))
             for step in actions_taken.steps if step.label}
    rows |= {item.number: item.text for item in action_items.rows}
    rows |= {line.label: Line(runs=(Run(text=line.at), Run(text=" "),
                                    *((Run(text=line.who), Run(text=": ")) if line.who else ()),
                                    *line.text.runs))
             for line in timeline.rows if line.label}
    rows |= {lead.label: lead.said for lead in leads}
    rows |= {row.label: row.said for row in (*supporting.changes, *supporting.log_messages)}
    rows |= {row.label: _its_first_line(row.said) for row in supporting.deployment_changes}
    rows |= {row.label: Line(runs=(Run(text=supporting.code_read_heading),))
             for row in supporting.code_read}
    if detection.said is not None:
        rows[detection.said.label] = detection.said.said
    return rows


def _its_first_line(line: Line) -> Line:
    """A line's runs up to its first line break."""
    runs: list[Run] = []
    for run in line.runs:
        before, broken, _ = run.text.partition("\n")
        if before:
            runs.append(run.model_copy(update={"text": before}))
        if broken:
            break

    return Line(runs=tuple(runs))
