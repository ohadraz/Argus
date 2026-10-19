"""Who reported an incident resolved, read off its events.

Beside the postmortem rather than in it: a document written before the report
is not rewritten, so what the person did is taken from the record each time the
document is shown. Each case is a set of events and the resolution found in
them, or none.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from argus_core import new_id
from argus_core.events import IncidentEvent, StatusChanged
from argus_core.models import IncidentStatus, ReportChannel
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.resolution import (
    Escalation,
    ReportedResolution,
    the_escalation,
    the_reported_resolution,
)

from postmortem_rendering_test.framework.builders import a_person_resolved_it


@pytest.mark.unit
def test_a_person_s_resolution_says_who_from_where_when_and_what_they_wrote() -> None:
    some_moment = datetime(2026, 10, 11, 14, 20, tzinfo=UTC)

    Scenario() \
        .given(
            some_events := [a_person_resolved_it("Kuki Buki", at=some_moment,
                                                 channel=ReportChannel.ARGUS_UI,
                                                 note="rolled the flag back by hand")]
        ) \
        .when(
            lambda: the_reported_resolution(some_events)
        ) \
        .then(
            the_answer_was(ReportedResolution(by="Kuki Buki",
                                              channel="the Argus UI",
                                              at=some_moment,
                                              note="rolled the flag back by hand"))
        )


@pytest.mark.unit
def test_an_incident_argus_ended_itself_has_no_reported_resolution() -> None:
    # Argus's own move to resolved names nobody, and a page saying "resolved
    # by" with no name would read as one lost.
    Scenario() \
        .given(
            some_events := [StatusChanged(incident_id=new_id(), to_status=IncidentStatus.RESOLVED)]
        ) \
        .when(
            lambda: the_reported_resolution(some_events)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_person_s_withdrawal_is_not_a_resolution() -> None:
    # A report moved the incident, and named a person - to withdrawn, which
    # ends an incident by saying there was none.
    Scenario() \
        .given(
            some_events := [a_person_resolved_it("Kuki Buki").model_copy(
                update={"to_status": IncidentStatus.WITHDRAWN})]
        ) \
        .when(
            lambda: the_reported_resolution(some_events)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_an_incident_with_no_events_has_no_reported_resolution() -> None:
    no_events: list[IncidentEvent] = []

    Scenario() \
        .given(
            no_events
        ) \
        .when(
            lambda: the_reported_resolution(no_events)
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_argus_s_escalation_says_when_and_why() -> None:
    some_moment = datetime(2026, 10, 11, 14, 20, tzinfo=UTC)

    Scenario() \
        .given(
            some_events := [StatusChanged(incident_id=new_id(), at=some_moment,
                                          to_status=IncidentStatus.ESCALATED,
                                          detail="a draft pull request is open")]
        ) \
        .when(
            lambda: the_escalation(some_events)
        ) \
        .then(
            the_answer_was(Escalation(at=some_moment, detail="a draft pull request is open"))
        )


@pytest.mark.unit
def test_an_incident_never_escalated_has_no_escalation() -> None:
    Scenario() \
        .given(
            some_events := [StatusChanged(incident_id=new_id(), to_status=IncidentStatus.MITIGATED)]
        ) \
        .when(
            lambda: the_escalation(some_events)
        ) \
        .then(
            the_answer_was(None)
        )
