"""The postmortem as a reader reads it: each section said in words, once, and the
PDF those words are printed into.

It lives on its own because more than one thing shows a postmortem. The
dashboard's page and the file a manager is sent must say the same things in
the same words, and the page is served by a process that may not install an
agent, while the Communicator that will send the file may not import another.
So the wording is worked out here, from the stored row and the incident's
values, and each destination decides only what to wrap around it.

Nothing in here reaches a database. It takes values and returns values - and,
for the PDF, bytes.
"""

from postmortem_rendering.action_items import ActionItemsSection, ItemRow, the_action_items
from postmortem_rendering.actions_taken import (
    ActionsTakenSection,
    StepRow,
    the_actions_taken,
    the_person_who_resolved,
)
from postmortem_rendering.cause import CauseSection, ChainLink, Factor, the_cause
from postmortem_rendering.cost import the_cost
from postmortem_rendering.detection import DetectionSection, the_detection
from postmortem_rendering.formatting import (
    as_money,
    as_revision,
    as_span,
    in_utc,
    on_the_clock,
)
from postmortem_rendering.head import Head, a_head, a_title
from postmortem_rendering.hypotheses import HypothesesSection, HypothesisRow, the_hypotheses
from postmortem_rendering.impact import Card, ImpactSection, the_impact
from postmortem_rendering.leads import LeadItem, the_leads
from postmortem_rendering.lessons import LessonList, the_lessons
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.pdf import as_pdf
from postmortem_rendering.rendering import RenderedPostmortem, render
from postmortem_rendering.resolution import ReportedResolution, the_reported_resolution
from postmortem_rendering.review import ReviewRow, ReviewSection, the_review
from postmortem_rendering.supporting import SupportingSection, the_supporting_information
from postmortem_rendering.timeline import TimelineRow, TimelineSection, the_timeline
from postmortem_rendering.trigger import TriggerSection, the_trigger

__all__ = [
    "ActionItemsSection",
    "ActionsTakenSection",
    "Card",
    "CauseSection",
    "ChainLink",
    "DetectionSection",
    "Factor",
    "Head",
    "HypothesesSection",
    "HypothesisRow",
    "ImpactSection",
    "ItemRow",
    "LeadItem",
    "LessonList",
    "Line",
    "RenderedPostmortem",
    "ReportedResolution",
    "ReviewRow",
    "ReviewSection",
    "Role",
    "Run",
    "StepRow",
    "SupportingSection",
    "TimelineRow",
    "TimelineSection",
    "TriggerSection",
    "a_head",
    "a_title",
    "as_money",
    "as_pdf",
    "as_revision",
    "as_span",
    "in_utc",
    "on_the_clock",
    "render",
    "the_action_items",
    "the_actions_taken",
    "the_cause",
    "the_cost",
    "the_detection",
    "the_hypotheses",
    "the_impact",
    "the_leads",
    "the_lessons",
    "the_person_who_resolved",
    "the_reported_resolution",
    "the_review",
    "the_supporting_information",
    "the_timeline",
    "the_trigger"
]
