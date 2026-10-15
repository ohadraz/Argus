"""The whole postmortem as a reader reads it: its title, its head, and every
section under its heading, in Google's order.

Each section's words are tested where they are worked out; these check what
only the whole has - which sections there are, in what order, and that what is
read off the record reaches every part that says it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    CitedEvidence,
    HypothesisConsidered,
    PostmortemLead,
    ResolutionStep,
    TimelineEntry,
)
from argus_testkit import Assertion, Scenario, all_of, the_answer_was
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.rendering import RenderedPostmortem, render

from postmortem_rendering_test.framework.builders import (
    DONT_CARE_MOMENT,
    a_person_resolved_it,
    a_postmortem,
    an_alert,
)

SOME_ADDRESS = "http://argus.example/incidents/0b1c"

EVERY_HEADING = ("Summary", "Impact", "Root cause and contributing factors",
                 "Hypotheses considered", "Trigger", "Resolution", "Detection", "Action items",
                 "Lessons learned", "Timeline", "What people told Argus", "Cost of the response",
                 "Supporting information", "Review checklist")


@pytest.mark.unit
def test_an_incident_people_wrote_in_has_every_section_in_google_s_order() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(leads=[_a_lead()])
        ) \
        .when(
            lambda: tuple(render(some_postmortem, an_alert(), [], SOME_ADDRESS).headings.values())
        ) \
        .then(
            the_answer_was(EVERY_HEADING))


@pytest.mark.unit
def test_an_incident_nobody_wrote_in_has_no_section_for_what_people_said() -> None:
    # Every other section with nothing in it says so; this one has nothing to
    # answer, and a heading over nothing would read as an answer lost.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(leads=[])
        ) \
        .when(
            lambda: tuple(render(some_postmortem, an_alert(), [], SOME_ADDRESS).headings.values())
        ) \
        .then(
            the_answer_was(tuple(heading for heading in EVERY_HEADING
                                 if heading != "What people told Argus")))


@pytest.mark.unit
def test_the_summary_is_the_model_s_prose() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(executive_summary="Account pages failed, per C1.")
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS).summary
        ) \
        .then(
            the_answer_was(Line(runs=(Run(text="Account pages failed, per C1.",
                                          role=Role.PROSE),))))


@pytest.mark.unit
def test_a_document_with_no_summary_says_none_was_written() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(executive_summary=None)
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS).summary_absent
        ) \
        .then(
            the_answer_was("No summary was written."))


@pytest.mark.unit
def test_the_document_is_titled_and_names_its_incident() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(symptom=None)
        ) \
        .when(
            lambda: render(some_postmortem, an_alert("HighErrorRate", "io-shop"), [], SOME_ADDRESS)
        ) \
        .then(all_of(
            _it_is_about(some_postmortem.incident_id),
            _it_is_titled("HighErrorRate on io-shop")))


@pytest.mark.unit
def test_a_person_s_resolution_on_the_record_reaches_the_head_and_the_resolution() -> None:
    # Read off the events each time the document is shown: one written before
    # the person reported the incident over is not rewritten.
    Scenario() \
        .given(
            some_events := [a_person_resolved_it("Kuki Buki")]
        ) \
        .when(
            lambda: render(a_postmortem(), an_alert(), some_events, SOME_ADDRESS)
        ) \
        .then(
            _it_was_ended_everywhere_by("Kuki Buki"))


@pytest.mark.unit
def test_the_incident_s_address_is_what_the_document_links_it_by() -> None:
    Scenario() \
        .given(
            SOME_ADDRESS
        ) \
        .when(
            lambda: render(a_postmortem(), an_alert(), [], SOME_ADDRESS).supporting.links[0].said
        ) \
        .then(
            the_answer_was(f"The incident's walk: {SOME_ADDRESS}"))


@pytest.mark.unit
def test_the_labels_prose_may_cite_are_those_of_the_rows_the_document_has() -> None:
    # A hypothesis, a step taken, an action item, a labelled line of the
    # timeline, a change and a log message read, and a lead each have a row to
    # lead to; an unlabelled line has no name.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                hypotheses=[HypothesisConsidered(summary="dont care", confidence=None,
                                                 result="dont care", label="C1")],
                resolution=[ResolutionStep(at=DONT_CARE_MOMENT, action="dont care",
                                           by="dont care", reversible=True,
                                           outcome="dont care", label="M1")],
                action_items=[ActionItem(number="AI-1", text="dont care",
                                         type=ActionItemType.PROCESS, owner=None,
                                         tracking=None, status=ActionItemStatus.OPEN)],
                timeline=[TimelineEntry(at=DONT_CARE_MOMENT, who=None, text="dont care",
                                        label="T1"),
                          TimelineEntry(at=DONT_CARE_MOMENT, who=None, text="dont care")],
                changes_read=[CitedEvidence(label="P1", text="dont care")],
                log_messages_read=[CitedEvidence(label="G3fa2", text="dont care")],
                leads=[_a_lead()])
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS).labels
        ) \
        .then(
            the_answer_was(frozenset({"C1", "M1", "AI-1", "T1", "P1", "G3fa2", "L1"})))


def _a_lead() -> PostmortemLead:
    return PostmortemLead(label="L1", person_id="dont care", person_name="dont care",
                          text="dont care", written_at=datetime(2026, 10, 11, 14, 6, tzinfo=UTC),
                          weighing=None, effect=None)


def _it_is_about(expected: str) -> Assertion[RenderedPostmortem]:
    def assertion(rendered: RenderedPostmortem) -> bool:
        if rendered.incident_id != expected:
            raise AssertionError(f"Expected the document about incident [{expected}], "
                                 f"got [{rendered.incident_id}].")

        return True

    return assertion


def _it_is_titled(expected: str) -> Assertion[RenderedPostmortem]:
    def assertion(rendered: RenderedPostmortem) -> bool:
        if rendered.title.said != expected:
            raise AssertionError(f"Expected the document titled [{expected}], "
                                 f"got [{rendered.title.said}].")

        return True

    return assertion


def _it_was_ended_everywhere_by(expected: str) -> Assertion[RenderedPostmortem]:
    def assertion(rendered: RenderedPostmortem) -> bool:
        said = (rendered.head.ended_by_whom, rendered.actions_taken.resolved_by)

        if said != (expected, expected):
            raise AssertionError(f"Expected the head and the resolution both to name "
                                 f"[{expected}], got {said}.")

        return True

    return assertion
