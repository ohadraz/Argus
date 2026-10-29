"""The whole postmortem as a reader reads it: its title, its head, and every
section under its heading, in the order of Google's example postmortem - what
happened and for how long before why.

What is read off the record rather than the document - a person's resolution -
is read here, once, and handed to every part that says it.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import date
from typing import Any, Final

from argus_core import said_short
from argus_core.events import IncidentEvent
from argus_core.models import Alert, Postmortem
from argus_narration import as_shown
from pydantic import BaseModel, ConfigDict

from postmortem_rendering.action_items import ActionItemsSection, the_action_items
from postmortem_rendering.actions_taken import ActionsTakenSection, the_actions_taken
from postmortem_rendering.cause import CauseSection, the_cause
from postmortem_rendering.cost import the_response_effort
from postmortem_rendering.detection import DetectionSection, the_detection
from postmortem_rendering.formatting import on_the_clock_of
from postmortem_rendering.head import Head, a_head, a_title, the_day_it_is_dated_by
from postmortem_rendering.hypotheses import HypothesesSection, the_hypotheses
from postmortem_rendering.impact import (
    Card,
    ImpactSection,
    the_alert_s_own_finding,
    the_impact,
)
from postmortem_rendering.leads import LeadItem, the_leads
from postmortem_rendering.lessons import LessonList, the_lessons
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.resolution import the_escalation, the_reported_resolution
from postmortem_rendering.review import ReviewSection, the_review
from postmortem_rendering.supporting import (
    SupportingSection,
    the_short_forms,
    the_supporting_information,
)
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
    "response-effort": "Response effort",
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
        log message, what a deployment changed, what Code-Fix read or a file
        as it ran, a lead,
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
                          *(row.label for row in self.supporting.as_it_ran),
                          *(row.label for row in self.supporting.uses_outside),
                          *(lead.label for lead in self.leads),
                          *((self.detection.said.label,) if self.detection.said else ()),
                          *((self.impact.finding_label,) if self.impact.finding_label else ())})


def render(postmortem: Postmortem,
           alert: Alert,
           events: Sequence[IncidentEvent],
           address_of: Callable[[str], str]) -> RenderedPostmortem:
    """A written postmortem as it is read, with a person's resolution taken
    from the incident's `events` and every link to an incident written from
    `address_of`, which gives an incident's page by its full address - this
    one's, and any earlier one a line of its timeline is about."""
    resolution = the_reported_resolution(events)
    leads = the_leads(postmortem)
    day = the_day_it_is_dated_by(postmortem)
    hypotheses = the_hypotheses(postmortem, day)
    actions_taken = the_actions_taken(postmortem, resolution, day)
    action_items = the_action_items(postmortem)
    timeline = the_timeline(postmortem, address_of)
    supporting = the_supporting_information(postmortem, address_of(postmortem.incident_id))
    detection = the_detection(postmortem, alert)
    impact = the_impact(postmortem, alert)
    rows = _the_rows(hypotheses, actions_taken, action_items, timeline, leads, supporting,
                     detection, _the_lines_cited_at(postmortem, day))
    # What the alert said, where Impact is the one place it is said.
    found = the_alert_s_own_finding(alert)
    if impact.finding_label and found:
        rows[impact.finding_label] = Line(runs=(Run(text=found),))

    rendered = RenderedPostmortem(
        incident_id=postmortem.incident_id,
        title=a_title(postmortem, alert),
        head=a_head(postmortem, alert, resolution, the_escalation(events)),
        headings={key: heading for key, heading in _HEADINGS.items()
                  if key != "leads" or leads},
        summary=_the_summary(postmortem),
        summary_absent=None if postmortem.executive_summary else "No summary was written.",
        impact=impact,
        cause=the_cause(postmortem, rows),
        hypotheses=hypotheses,
        trigger=the_trigger(postmortem, alert),
        actions_taken=actions_taken,
        detection=detection,
        action_items=action_items,
        lessons=the_lessons(postmortem),
        timeline=timeline,
        leads=leads,
        cost=the_response_effort(postmortem),
        supporting=supporting,
        review=the_review(postmortem))

    if day is None:
        return rendered

    return rendered.model_copy(update={
        name: _said_on(getattr(rendered, name), day)
        for name in RenderedPostmortem.model_fields if name not in _WHERE_THE_DAY_IS_SAID
    })


# What says the incident's day, and so keeps every moment's date: the rest of
# the document says a moment of that day by its time alone.
_WHERE_THE_DAY_IS_SAID: Final = frozenset({"title", "head"})


def _said_on(value: Any, day: date) -> Any:
    """`value` with every moment in it that falls on `day` said by its time
    alone, however deep in a section it sits.

    Here, once, rather than in each section: every section says its moments
    with `Run.a_moment`, and a section that forgot to pass the day on would
    say its moments as though on another one - which is the defect this ends.
    """
    if isinstance(value, Run):
        return value.said_on(day)

    if isinstance(value, BaseModel):
        return value.model_copy(update={name: _said_on(getattr(value, name), day)
                                        for name in type(value).model_fields})

    if isinstance(value, tuple):
        return tuple(_said_on(each, day) for each in value)

    if isinstance(value, list):
        return [_said_on(each, day) for each in value]

    if isinstance(value, dict):
        return {key: _said_on(each, day) for key, each in value.items()}

    return value


def _the_summary(postmortem: Postmortem) -> Line | None:
    """The summary as prose, every name it quotes in brackets said as code - a
    candidate's result it carries is the walk's words, quoted as the walk
    quotes them - and a revision said short and bare, as the timeline says it.
    `None` where none was written."""
    if not postmortem.executive_summary:
        return None

    shorts = the_short_forms(postmortem.changes_read)
    said = as_shown(said_short(postmortem.executive_summary, shorts),
                    bare=frozenset(shorts.values()))

    return Line(runs=(Run(text=said, role=Role.PROSE),))


def _the_rows(hypotheses: HypothesesSection,
              actions_taken: ActionsTakenSection,
              action_items: ActionItemsSection,
              timeline: TimelineSection,
              leads: Sequence[LeadItem],
              supporting: SupportingSection,
              detection: DetectionSection,
              lines_cited_at: Mapping[str, str]) -> dict[str, Line]:
    """Each label a row of the document goes by, and the line it says itself
    in - so an item the causal chain cites is said the way its own row says
    it, not in the words the model was briefed in. A line of the timeline is
    said at `lines_cited_at`'s time for it rather than its row's, which leaves
    the day to the rows above it.

    A candidate goes by every label it stands for. A step taken has its
    outcome after a colon, the outcome having dashes of its own. A diff and a
    file as it ran are named by their first line and what Code-Fix read by its
    heading: each row can run to pages, and the label leads to it."""
    rows: dict[str, Line] = {}
    for candidate in hypotheses.rows:
        said = Line(runs=(*candidate.summary.runs, Run(text=" - "), *candidate.result.runs))
        rows |= {label: said for label in (candidate.label, *candidate.also)}

    rows |= {step.label: Line(runs=(Run(text=step.at), Run(text=" "), *step.action.runs,
                                    Run(text=": "), Run(text=step.outcome)))
             for step in actions_taken.steps if step.label}
    rows |= {item.number: item.text for item in action_items.rows}
    rows |= {line.label: Line(runs=(Run(text=lines_cited_at.get(line.label, line.at)),
                                    Run(text=" "),
                                    *((Run(text=line.who), Run(text=": ")) if line.who else ()),
                                    *line.text.runs))
             for line in timeline.rows if line.label}
    rows |= {lead.label: lead.said for lead in leads}
    rows |= {row.label: row.said for row in (*supporting.changes, *supporting.log_messages,
                                              *supporting.uses_outside)}
    rows |= {row.label: _its_first_line(row.said)
             for row in (*supporting.deployment_changes, *supporting.as_it_ran)}
    rows |= {row.label: Line(runs=(Run(text=supporting.code_read_heading),))
             for row in supporting.code_read}
    if detection.said is not None:
        rows[detection.said.label] = detection.said.said
    return rows


def _the_lines_cited_at(postmortem: Postmortem, day: date | None) -> dict[str, str]:
    """Each labelled line of the timeline's time as a citation says it, away
    from the rows above it: alone on `day`, the day the head names, and with
    its day on any other. Empty where the document names no day, and each is
    said as its row says it."""
    if day is None:
        return {}

    return {entry.label: on_the_clock_of(entry.at, day)
            for entry in postmortem.timeline if entry.label}


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
