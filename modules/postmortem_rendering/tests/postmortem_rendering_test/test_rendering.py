"""The whole postmortem as a reader reads it: its title, its head, and every
section under its heading, in Google's order.

Each section's words are tested where they are worked out; these check what
only the whole has - which sections there are, in what order, and that what is
read off the record reaches every part that says it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core import new_id
from argus_core.events import StatusChanged
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    ChainStep,
    CitedEvidence,
    Detection,
    HypothesisConsidered,
    IncidentStatus,
    PostmortemLead,
    ResolutionStep,
    TimelineEntry,
)
from argus_testkit import Assertion, Scenario, all_of, the_answer_was
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.rendering import RenderedPostmortem, render

from postmortem_rendering_test.framework.builders import (
    DONT_CARE_MOMENT,
    a_change_read,
    a_person_resolved_it,
    a_postmortem,
    an_alert,
)

SOME_ADDRESS = "http://argus.example/incidents/0b1c"
SOME_MOMENT = datetime(2026, 10, 11, 14, 3, 7, tzinfo=UTC)

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
def test_argus_s_escalation_on_the_record_reaches_the_head() -> None:
    # Read off the events, as a person's resolution is.
    Scenario() \
        .given(
            some_events := [StatusChanged(incident_id=new_id(), at=DONT_CARE_MOMENT,
                                          to_status=IncidentStatus.ESCALATED, detail=None)]
        ) \
        .when(
            lambda: render(a_postmortem(resolution=[]), an_alert(), some_events,
                           SOME_ADDRESS).head.ended_by_whom
        ) \
        .then(
            the_answer_was("Argus"))


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
                changes_read=[a_change_read("P1")],
                log_messages_read=[CitedEvidence(label="G3fa2", text="dont care")],
                leads=[_a_lead()])
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS).labels
        ) \
        .then(
            the_answer_was(frozenset({"C1", "M1", "AI-1", "T1", "P1", "G3fa2", "L1"})))


@pytest.mark.unit
def test_every_label_a_row_goes_by_may_be_cited() -> None:
    # A row standing for two candidates goes by both labels, and prose citing
    # the second has the row to lead to.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                hypotheses=[HypothesisConsidered(summary="dont care", confidence=None,
                                                 result="dont care", label="C1", also=["C2"])])
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS).labels
        ) \
        .then(
            the_answer_was(frozenset({"C1", "C2"})))


@pytest.mark.unit
def test_a_cited_line_of_the_timeline_reads_as_its_row() -> None:
    # Its time as the timeline says it, who said it, and the line without the
    # narration's brackets.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                timeline=[TimelineEntry(at=SOME_MOMENT, who="Investigator Agent",
                                        text="Placed the start [here]", label="T1")],
                causal_chain=_a_step_citing("T1"))
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS)
        ) \
        .then(
            _the_first_step_rests_on(
                "T1 Oct 11 14:03:07 Investigator Agent: Placed the start here"))


@pytest.mark.unit
def test_a_cited_line_of_the_timeline_nobody_is_named_for_reads_as_its_row() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                timeline=[TimelineEntry(at=SOME_MOMENT, who=None, text="The flag went on",
                                        label="T1")],
                causal_chain=_a_step_citing("T1"))
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS)
        ) \
        .then(
            _the_first_step_rests_on("T1 Oct 11 14:03:07 The flag went on"))


@pytest.mark.unit
def test_a_cited_step_taken_reads_as_its_row() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                resolution=[ResolutionStep(at=SOME_MOMENT, action="Turned the flag off",
                                           by="dont care", reversible=True,
                                           outcome="recovered", label="M1")],
                causal_chain=_a_step_citing("M1"))
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS)
        ) \
        .then(
            _the_first_step_rests_on("M1 14:03:07 Turned the flag off: recovered"))


@pytest.mark.unit
def test_a_cited_candidate_reads_as_its_row_under_whichever_label_it_goes_by() -> None:
    # Two candidates shown as one row: the second's label leads to that row,
    # and reads as it.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                hypotheses=[HypothesisConsidered(summary="A flag change", confidence=None,
                                                 result="confirmed", label="C1", also=["C2"])],
                causal_chain=_a_step_citing("C1", "C2"))
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS)
        ) \
        .then(
            _the_first_step_rests_on("C1 A flag change - confirmed",
                                     "C2 A flag change - confirmed"))


@pytest.mark.unit
def test_a_cited_change_log_message_lead_and_action_item_read_as_their_rows() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                changes_read=[a_change_read("P1", summary="A deploy switched the model.")],
                log_messages_read=[CitedEvidence(label="G3fa2", text="ERROR divide by zero")],
                leads=[_a_lead()],
                action_items=[ActionItem(number="AI-1", text="Guard the divisor.",
                                         type=ActionItemType.PREVENT, owner=None,
                                         tracking=None, status=ActionItemStatus.OPEN)],
                causal_chain=_a_step_citing("P1", "G3fa2", "L1", "AI-1"))
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS)
        ) \
        .then(
            _the_first_step_rests_on(
                "P1 Oct 11, 2026, 14:00 UTC flag toggle dont-care by someone unnamed: "
                "A deploy switched the model.",
                "G3fa2 ERROR divide by zero",
                "L1 dont care - dont care, Oct 11, 2026, 14:06 UTC",
                "AI-1 Guard the divisor."))


@pytest.mark.unit
def test_a_cited_diff_is_named_by_its_first_line() -> None:
    # The row is the whole diff, which the label leads to.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                deployment_changes_read=[CitedEvidence(
                    label="D1", text="Deployment of revision x.\n  +  key: value")],
                causal_chain=_a_step_citing("D1"))
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS)
        ) \
        .then(
            _the_first_step_rests_on("D1 Deployment of revision x."))


@pytest.mark.unit
def test_what_code_fix_read_is_named_by_its_heading_when_cited() -> None:
    # The row can run to pages, which the label leads to.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                code_read=[CitedEvidence(label="F1", text="The categoriser does not lowercase.")],
                causal_chain=_a_step_citing("F1"))
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS)
        ) \
        .then(
            _the_first_step_rests_on(
                "F1 What Code-Fix read in the source - a static reading, nothing ran it"))


@pytest.mark.unit
def test_what_the_alert_said_may_be_cited_and_reads_as_its_row() -> None:
    # The one label the chain could cite that led nowhere.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(
                detection=Detection(alerted_at=SOME_MOMENT, rule="dont care", onset_at=None,
                                    gap=None,
                                    said=CitedEvidence(label="AL1", text="240 totals are off")),
                causal_chain=_a_step_citing("AL1"))
        ) \
        .when(
            lambda: render(some_postmortem, an_alert(), [], SOME_ADDRESS)
        ) \
        .then(all_of(
            _it_may_cite("AL1"),
            _the_first_step_rests_on("AL1 240 totals are off")))


def _it_may_cite(label: str) -> Assertion[RenderedPostmortem]:
    def assertion(rendered: RenderedPostmortem) -> bool:
        if label not in rendered.labels:
            raise AssertionError(f"Expected [{label}] among the labels the prose may cite, "
                                 f"got {sorted(rendered.labels)}.")

        return True

    return assertion


def _a_lead() -> PostmortemLead:
    return PostmortemLead(label="L1", person_id="dont care", person_name="dont care",
                          text="dont care", written_at=datetime(2026, 10, 11, 14, 6, tzinfo=UTC),
                          weighing=None, effect=None)


def _a_step_citing(*labels: str) -> list[ChainStep]:
    """A chain of one step, citing each label in words that are not its row's."""
    return [ChainStep(text="dont care",
                      cites=[CitedEvidence(label=label, text="as briefed") for label in labels])]


def _the_first_step_rests_on(*expected: str) -> Assertion[RenderedPostmortem]:
    def assertion(rendered: RenderedPostmortem) -> bool:
        said = tuple(cited.said for cited in rendered.cause.chain[0].evidence)

        if said != expected:
            raise AssertionError(f"Expected the first step to rest on {expected}, "
                                 f"got {said}.")

        return True

    return assertion


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
