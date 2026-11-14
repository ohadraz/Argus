"""The postmortem as plain text: every section under its heading, in the order
a reader reads them, each line's words with nothing wrapped round them.

For a reader with no page - the grounding judge, reading an overview against
the document it was written from. Its words are the page's, worked out once
(`render`); only the markup is left out.
"""

from __future__ import annotations

import pytest
from argus_core.models import (
    ActionItem,
    ActionItemStatus,
    ActionItemType,
    AlarmClaim,
    ChainStep,
    CitedEvidence,
    Detection,
    HypothesisConsidered,
    TimelineEntry,
)
from argus_testkit import Assertion, Scenario, all_of
from postmortem_rendering.rendering import RenderedPostmortem, render
from postmortem_rendering.text import as_text

from postmortem_rendering_test.framework.builders import (
    DONT_CARE_MOMENT,
    a_change_read,
    a_person_resolved_it,
    a_postmortem,
    a_postmortem_with_every_section_filled,
    an_alert,
    the_page_of,
)
from postmortem_rendering_test.framework.reading import every_labelled_row, everything_held

SOME_ROOT_CAUSE = "An empty month divided by zero."
SOME_STEP = "The statement summed no rows."
# A row of each kind the judge cites, by its label and its own words.
SOME_LINE_LABEL, SOME_LINE = "T1", "The flag was turned off."
SOME_CANDIDATE_LABEL, SOME_CANDIDATE = "C1", "The monthly-spend flag broke checkout."
SOME_CHANGE_LABEL, SOME_CHANGE = "P1", "monthly-spend-feature turned on"
SOME_ITEM_NUMBER, SOME_ITEM = "AI-1", "Alert on a month with no rows."
# Who reported the incident over.
SOME_PERSON = "Dana"
# What an alert reporting a finding of its own found, and the label its row
# goes by.
SOME_FINDING = "Checkout errors crossed one in ten."
SOME_ALERT_LABEL = "AL1"


@pytest.mark.unit
def test_the_text_says_every_section_under_its_heading_in_the_page_s_order() -> None:
    # The timeline's heading with the zone its rows' times are in, as the
    # page says it once there rather than on every row.
    Scenario() \
        .given(
            rendered := render(a_postmortem(), an_alert(), [], the_page_of)
        ) \
        .when(
            lambda: as_text(rendered)
        ) \
        .then(
            _headed_in_order(_the_page_s_headings(rendered))
        )


@pytest.mark.unit
def test_the_text_says_what_a_section_says_under_its_own_heading() -> None:
    # Under its own: a judge told a cause stood in another section would be
    # reading a different document.
    Scenario() \
        .given(
            rendered := render(a_postmortem(root_cause=SOME_ROOT_CAUSE,
                                            causal_chain=[ChainStep(text=SOME_STEP, cites=[])]),
                               an_alert(), [], the_page_of)
        ) \
        .when(
            lambda: as_text(rendered)
        ) \
        .then(
            _said_between(rendered.headings["cause"], rendered.headings["hypotheses"],
                          [SOME_ROOT_CAUSE, SOME_STEP])
        )


@pytest.mark.unit
def test_the_text_says_every_labelled_row_with_its_label() -> None:
    # The judge cites a row by its label, and a flag citing a label the text
    # does not carry is dropped - so every label is said, beside its row.
    Scenario() \
        .given(
            rendered := render(
                a_postmortem(
                    timeline=[TimelineEntry(at=DONT_CARE_MOMENT, who=None, text=SOME_LINE,
                                            label=SOME_LINE_LABEL)],
                    hypotheses=[HypothesisConsidered(summary=SOME_CANDIDATE, confidence=None,
                                                     result="dont care",
                                                     label=SOME_CANDIDATE_LABEL)],
                    changes_read=[a_change_read(SOME_CHANGE_LABEL, SOME_CHANGE)],
                    action_items=[ActionItem(number=SOME_ITEM_NUMBER, text=SOME_ITEM,
                                             type=ActionItemType.PREVENT, owner=None,
                                             tracking=None, status=ActionItemStatus.OPEN)]),
                an_alert(), [], the_page_of)
        ) \
        .when(
            lambda: as_text(rendered)
        ) \
        .then(
            all_of(
                _said_on_one_line([SOME_LINE_LABEL, SOME_LINE]),
                _said_on_one_line([SOME_CANDIDATE_LABEL, SOME_CANDIDATE]),
                _said_on_one_line([SOME_CHANGE_LABEL, SOME_CHANGE]),
                _said_on_one_line([SOME_ITEM_NUMBER, SOME_ITEM]),
                _every_label_said(rendered.labels)
            )
        )


@pytest.mark.unit
def test_every_section_says_what_the_document_holds() -> None:
    # The text twin of the PDF's: a part the text left out is a part the
    # judge never read, and an overview faithful to it would be flagged.
    # Resolved by a person, so the resolution says who.
    Scenario() \
        .given(
            rendered := render(a_postmortem_with_every_section_filled(), an_alert(),
                               [a_person_resolved_it(by=SOME_PERSON)], the_page_of)
        ) \
        .when(
            lambda: as_text(rendered)
        ) \
        .then(
            all_of(
                _it_reads_in_order(*everything_held(rendered)),
                *(_said_on_one_line([label, words])
                  for label, words in every_labelled_row(rendered))
            )
        )


@pytest.mark.unit
def test_what_the_alert_found_is_said_in_impact_with_its_label() -> None:
    # Said there alone, so a citation of its label has that line to lead to.
    Scenario() \
        .given(
            rendered := render(
                a_postmortem(detection=Detection(
                    alerted_at=DONT_CARE_MOMENT, rule=None, onset_at=None, gap=None,
                    said=CitedEvidence(label=SOME_ALERT_LABEL, text=SOME_FINDING))),
                an_alert(summary=SOME_FINDING, claim=AlarmClaim.ITS_OWN_FINDING),
                [], the_page_of)
        ) \
        .when(
            lambda: as_text(rendered)
        ) \
        .then(
            _said_between(rendered.headings["impact"], rendered.headings["cause"],
                          [f"{SOME_ALERT_LABEL}: {rendered.impact.finding}"])
        )


def _the_page_s_headings(rendered: RenderedPostmortem) -> tuple[str, ...]:
    """Every heading as the page says it - the timeline's with its zone."""
    return tuple(f"{heading} {rendered.timeline.zone}" if key == "timeline" else heading
                 for key, heading in rendered.headings.items())


def _headed_in_order(headings: tuple[str, ...]) -> Assertion[str]:
    def assertion(text: str) -> bool:
        lines = text.splitlines()
        found = [line for line in lines if line in headings]

        if found != list(headings):
            raise AssertionError(
                f"Expected the headings {list(headings)} each on a line of their own, in "
                f"order, and found {found}.")

        return True

    return assertion


def _said_between(heading: str, next_heading: str, expected: list[str]) -> Assertion[str]:
    def assertion(text: str) -> bool:
        lines = text.splitlines()
        under = "\n".join(lines[lines.index(heading) + 1:lines.index(next_heading)])
        missing = [words for words in expected if words not in under]

        if missing:
            raise AssertionError(
                f"Expected {expected} under [{heading}], and {missing} were not in "
                f"[{under}].")

        return True

    return assertion


def _said_on_one_line(expected: list[str]) -> Assertion[str]:
    def assertion(text: str) -> bool:
        if not any(all(words in line for words in expected) for line in text.splitlines()):
            raise AssertionError(
                f"Expected a line saying each of {expected}, and none did in [{text}].")

        return True

    return assertion


def _it_reads_in_order(*expected: str) -> Assertion[str]:
    """Each in turn, found after the one before - so words a part says twice
    are found where the later part says them."""
    def assertion(text: str) -> bool:
        position = 0

        for said in expected:
            found = text.find(said, position)
            if found < 0:
                raise AssertionError(
                    f"Expected [{said}] after position {position} in the order "
                    f"{expected}, and the text reads: {text}")
            position = found + len(said)

        return True

    return assertion


def _every_label_said(labels: frozenset[str]) -> Assertion[str]:
    def assertion(text: str) -> bool:
        missing = sorted(label for label in labels if label not in text)

        if missing:
            raise AssertionError(
                f"Expected every label the document's rows go by in the text, and "
                f"{missing} were not in [{text}].")

        return True

    return assertion
