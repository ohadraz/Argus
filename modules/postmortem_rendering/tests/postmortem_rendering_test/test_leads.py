"""What people told the incident: each thing a person wrote, who wrote it and
when, what the investigation made of it, and what it changed - one answer to
the person who wrote it, so the three stay together.

Each case is one lead and what the section says of it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core.models import PostmortemLead, Standing, Weighing
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.leads import LeadItem, the_leads
from postmortem_rendering.lines import Line, Role, Run

from postmortem_rendering_test.framework.builders import a_postmortem

SOME_MOMENT = datetime(2026, 10, 11, 14, 6, tzinfo=UTC)


@pytest.mark.unit
def test_a_weighed_lead_says_what_was_written_by_whom_when_its_standing_and_its_effect() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(leads=[PostmortemLead(
                person_id="U-kuki", person_name="Kuki Buki",
                text="the kuki flag was flipped at noon", written_at=SOME_MOMENT,
                weighing=Weighing(standing=Standing.SUPPORTED, reason="the flag history agrees"),
                effect="it named the flag that was reverted")])
        ) \
        .when(
            lambda: the_leads(some_postmortem)
        ) \
        .then(
            the_answer_was((LeadItem(
                person_id="U-kuki",
                said=Line(runs=(Run(text="the kuki flag was flipped at noon", role=Role.QUOTE),
                                Run(text=" - Kuki Buki, "),
                                Run.a_moment(SOME_MOMENT))),
                weighing=Line(runs=(Run(text="supported", role=Role.STATUS),
                                    Run(text=": the flag history agrees"))),
                effect=Line(runs=(Run(text="it named the flag that was reverted",
                                      role=Role.PROSE),))),)))


@pytest.mark.unit
def test_a_lead_from_somebody_unnamed_is_signed_with_their_id() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(leads=[PostmortemLead(
                person_id="U-kuki", person_name=None, text="dont care",
                written_at=SOME_MOMENT, weighing=None, effect=None)])
        ) \
        .when(
            lambda: the_leads(some_postmortem)[0].said.said
        ) \
        .then(
            the_answer_was("dont care - U-kuki, Oct 11, 2026, 14:06 UTC"))


@pytest.mark.unit
def test_a_lead_no_investigation_weighed_says_so_and_has_no_effect() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(leads=[PostmortemLead(
                person_id="dont care", person_name="dont care", text="dont care",
                written_at=SOME_MOMENT, weighing=None, effect=None)])
        ) \
        .when(
            lambda: (the_leads(some_postmortem)[0].weighing, the_leads(some_postmortem)[0].effect)
        ) \
        .then(
            the_answer_was((Line(runs=(Run(text="never weighed", role=Role.STATUS),)), None)))


@pytest.mark.unit
def test_an_incident_nobody_wrote_in_has_no_leads() -> None:
    # The one section left out rather than said empty: an incident nobody
    # wrote in has nothing to answer.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(leads=[])
        ) \
        .when(
            lambda: the_leads(some_postmortem)
        ) \
        .then(
            the_answer_was(()))
