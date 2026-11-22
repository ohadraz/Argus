"""The name every destination knows each section by: the postmortem's and the
executive synopsis's, each declared once, in the order they are read.

Each is a `StrEnum` whose values are the spellings the page has always used -
its `data-section` attributes and the template's `headings["leads"]` - since a
member hashes and compares as its string. Every map from a section to how it
is said or printed is typed by its own enum and never by `str`: the two share
"impact" and "resolution", and a synopsis's part would otherwise find a
postmortem's section of the same name.

Here rather than in the kernel because only the renderers and the page name a
section, and the page already installs this package to show one.
"""

from __future__ import annotations

from enum import StrEnum


class SectionKey(StrEnum):
    """A section of the postmortem, in the order of Google's example: what
    happened and for how long before why."""

    SUMMARY = "summary"
    IMPACT = "impact"
    CAUSE = "cause"
    HYPOTHESES = "hypotheses"
    TRIGGER = "trigger"
    RESOLUTION = "resolution"
    DETECTION = "detection"
    ACTION_ITEMS = "action-items"
    LESSONS = "lessons"
    TIMELINE = "timeline"
    LEADS = "leads"
    RESPONSE_EFFORT = "response-effort"
    SUPPORTING = "supporting"
    REVIEW = "review"


class SynopsisPartKey(StrEnum):
    """A part of the executive synopsis, in the order a reader asks: what
    happened, when, how bad, what was done, and what it cost the people who
    answered."""

    OVERVIEW = "overview"
    WHEN = "when"
    IMPACT = "impact"
    RESOLUTION = "resolution"
    HUMAN_COST = "human-cost"
