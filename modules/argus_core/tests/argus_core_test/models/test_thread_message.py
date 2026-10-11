"""Which of an incident's leads an agent has not yet been shown, and what each
is called.

Every agent a lead reaches asks the thread before each turn, and is answered
with every lead the incident has - so what is new to it is worked out against
what it was already shown. Said once here, because two agents working it out
apart would come to disagree about when a lead counts as the same lead.

The label is said once here for the same reason: it is what a model names a
lead back by, and the Investigator and the postmortem numbering their leads
apart would come to disagree about which lead L2 is.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core import new_id
from argus_core.models import (
    Meaning,
    ReportChannel,
    Standing,
    ThreadMessage,
    Weighing,
    a_chat_message,
    labelled,
    not_yet_shown,
)
from argus_testkit import Assertion, Scenario

SOME_TS = "1760000100.000200"
ANOTHER_TS = "1760000200.000300"
A_THIRD_TS = "1760000300.000400"


@pytest.mark.unit
def test_a_lead_already_shown_is_not_shown_again() -> None:
    # However often the thread is asked, a lead reaches the model once: shown
    # again on every turn, it would read as somebody saying it again.
    a_lead_shown = _a_lead("the kuki flag was flipped at noon", ts=SOME_TS)

    Scenario() \
        .given(a_lead_shown) \
        .when(lambda: not_yet_shown([a_lead_shown], shown=[a_lead_shown])) \
        .then(_the_leads_are([]))


@pytest.mark.unit
def test_leads_not_yet_shown_come_in_the_order_they_were_written() -> None:
    # The order the thread answers in, which is the order people wrote - and
    # the order a label counts by, so a lead numbered out of it would be named
    # by another lead's number.
    a_lead_shown = _a_lead("the kuki flag was flipped at noon", ts=SOME_TS)
    a_later_lead = _a_lead("it is the database again", ts=ANOTHER_TS)
    the_latest_lead = _a_lead("the buki deploy went out at noon too", ts=A_THIRD_TS)

    Scenario() \
        .given(a_lead_shown) \
        .when(lambda: not_yet_shown([a_lead_shown, a_later_lead, the_latest_lead],
                                    shown=[a_lead_shown])) \
        .then(_the_leads_are([a_later_lead, the_latest_lead]))


@pytest.mark.unit
def test_a_lead_weighed_since_it_was_shown_is_still_the_lead_that_was_shown() -> None:
    # A lead is the message the chat platform names, not its current standing:
    # one weighed while the agent worked comes back from the thread changed,
    # and is still something the agent has already read.
    a_lead_shown = _a_lead("the kuki flag was flipped at noon", ts=SOME_TS)
    the_same_lead_weighed = a_lead_shown.model_copy(update={
        "weighing": Weighing(standing=Standing.SUPPORTED, reason="the flag history agrees")
    })

    Scenario() \
        .given(the_same_lead_weighed) \
        .when(lambda: not_yet_shown([the_same_lead_weighed], shown=[a_lead_shown])) \
        .then(_the_leads_are([]))


@pytest.mark.unit
def test_leads_are_labelled_from_one_in_the_order_they_were_written() -> None:
    # What a model is shown each lead as, and names it back by.
    a_lead = _a_lead("the kuki flag was flipped at noon", ts=SOME_TS)
    a_later_lead = _a_lead("it is the database again", ts=ANOTHER_TS)

    Scenario() \
        .given(a_lead) \
        .when(lambda: labelled([a_lead, a_later_lead])) \
        .then(_the_labels_are([("L1", a_lead), ("L2", a_later_lead)]))


@pytest.mark.unit
def test_leads_written_since_are_labelled_on_from_those_already_shown() -> None:
    # A lead written mid-investigation is the next one, not a second L1: the
    # model already holds L1 and L2, and a weighing of "L1" must not be able to
    # mean either of two leads.
    the_latest_lead = _a_lead("the buki deploy went out at noon too", ts=A_THIRD_TS)

    Scenario() \
        .given(the_latest_lead) \
        .when(lambda: labelled([the_latest_lead], first=3)) \
        .then(_the_labels_are([("L3", the_latest_lead)]))


def _a_lead(words: str, ts: str) -> ThreadMessage:
    """Something a person told the incident, understood as information - the
    message named by `ts`."""
    return ThreadMessage(incident_id=new_id(),
                         message=a_chat_message(ReportChannel.SLACK, "C-some-channel", ts),
                         person_id="U-some-person",
                         text=words,
                         written_at=datetime(2026, 8, 20, 11, 5, tzinfo=UTC),
                         meaning=Meaning.INFORMATION)


def _the_leads_are(expected: list[ThreadMessage]) -> Assertion[list[ThreadMessage]]:
    def assertion(leads: list[ThreadMessage]) -> bool:
        if leads != expected:
            raise AssertionError(
                f"Expected the leads not yet shown to be "
                f"{[lead.text for lead in expected]}, and they were "
                f"{[lead.text for lead in leads]}."
            )

        return True

    return assertion


def _the_labels_are(
        expected: list[tuple[str, ThreadMessage]]
) -> Assertion[list[tuple[str, ThreadMessage]]]:
    def assertion(found: list[tuple[str, ThreadMessage]]) -> bool:
        if found != expected:
            raise AssertionError(
                f"Expected the leads labelled "
                f"{[(label, lead.text) for label, lead in expected]}, and they were "
                f"{[(label, lead.text) for label, lead in found]}."
            )

        return True

    return assertion
