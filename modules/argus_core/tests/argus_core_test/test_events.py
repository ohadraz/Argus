from __future__ import annotations

import pytest
from argus_core.events import (
    AgentInvoked,
    IncidentEvent,
    LogsRetrieved,
    Publisher,
    RetrievalChannel,
    RetrievalRequested,
    parse_event,
    publish,
)
from argus_core.ids import new_id
from argus_core.models.actor import Actor

"""What Argus says about its own work, and the one rule that says on it.

An event is an account of something that happened - it names the incident, the
moment, and enough of the values involved that somebody reading it months later
needs nothing but the event. The rule is that publishing one can never change
what Argus decides, which here means it cannot fail a caller either.
"""


@pytest.mark.unit
def test_an_event_names_the_incident_it_belongs_to() -> None:
    # An event that cannot be attributed to an incident is a line in a log
    # file, which is what the system already had and could not read.
    some_incident_id = new_id()

    invoked = AgentInvoked(incident_id=some_incident_id, agent=Actor.INVESTIGATOR)

    assert invoked.incident_id == some_incident_id


@pytest.mark.unit
def test_an_event_knows_when_it_happened_without_being_told() -> None:
    # The moment is the event's own, taken where it is built - a caller that
    # had to supply it could supply the wrong one, and a narration ordered by
    # when rows were written is a narration of the database's day.
    an_event = AgentInvoked(incident_id=new_id(), agent=Actor.INVESTIGATOR)

    assert an_event.at is not None


@pytest.mark.unit
def test_a_retrieval_names_its_channel_and_both_bounds_of_its_window() -> None:
    # "Argus looked at the logs" is not readable; "Argus looked at the logs
    # between 10:02 and 10:12" is. A window with one bound is a window nobody
    # can check the answer against.
    requested = RetrievalRequested(
        incident_id=new_id(),
        channel=RetrievalChannel.LOGS,
        window_start="2026-08-30T10:02:00Z",
        window_end="2026-08-30T10:12:00Z",
    )

    assert requested.channel == RetrievalChannel.LOGS
    assert requested.window_start == "2026-08-30T10:02:00Z"
    assert requested.window_end == "2026-08-30T10:12:00Z"


@pytest.mark.unit
def test_a_retrieval_that_returned_carries_what_came_back() -> None:
    # The whole point of storing the payload: the page shows what Argus read,
    # not what the log store happens to hold when somebody opens the page.
    the_lines_it_read = [
        "2026-08-30T10:03:00Z ERROR io-shop: division by zero",
        "2026-08-30T10:03:00Z INFO io-shop: monthly-spend-feature=on",
    ]

    retrieved = LogsRetrieved(
        incident_id=new_id(),
        window_start="2026-08-30T10:02:00Z",
        window_end="2026-08-30T10:12:00Z",
        lines=the_lines_it_read,
    )

    assert retrieved.lines == the_lines_it_read


@pytest.mark.unit
def test_an_event_read_back_is_the_event_that_was_published() -> None:
    # It is written to a table and read out again, and what comes back has to
    # be the same kind of thing it went in as - otherwise every reader is left
    # matching on strings to work out what it is holding.
    published = LogsRetrieved(
        incident_id=new_id(),
        window_start="2026-08-30T10:02:00Z",
        window_end="2026-08-30T10:12:00Z",
        lines=["some log line"],
    )

    read_back = parse_event(published.model_dump(mode="json"))

    assert read_back == published


@pytest.mark.unit
def test_an_event_reaches_the_publisher_it_was_given() -> None:
    published: list[IncidentEvent] = []
    an_event = AgentInvoked(incident_id=new_id(), agent=Actor.MITIGATION)

    publish(an_event, publisher=published.append)

    assert published == [an_event]


@pytest.mark.unit
def test_a_publisher_that_fails_does_not_fail_the_work_it_was_describing() -> None:
    # The account of the work is never part of the work. An incident that
    # would have resolved must resolve even when nobody could write down that
    # it was resolving.
    def a_publisher_that_raises(dont_care_event: IncidentEvent) -> None:
        raise RuntimeError("the subscriber is having a bad day")

    a_failing_publisher: Publisher = a_publisher_that_raises

    publish(
        AgentInvoked(incident_id=new_id(), agent=Actor.INVESTIGATOR),
        publisher=a_failing_publisher,
    )


@pytest.mark.unit
def test_publishing_reaches_nobody_by_default() -> None:
    # A component publishes whether or not anything is listening, and nothing
    # about its behaviour changes either way. The default is where that is
    # true by construction.
    publish(AgentInvoked(incident_id=new_id(), agent=Actor.INVESTIGATOR))
