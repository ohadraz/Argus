"""One look at the log, from the intent agent's side of it.

The intent agent follows everything published, as the relay does, and acts on one
kind of event: a person writing in an incident's thread. Everything else is
passed over, and the place moves past it all the same - an intent agent that stopped
at the first retrieval would sit there for ever.

A message that could not be understood - the model unreachable, the database gone -
stops the look where it is, and the place stays in front of it. The next look
tries it again, because a person's words skipped are words Argus never took in,
and the messages behind it wait rather than being read out of order.

The log and the place are stood in for: they are `argus_incidents`' and tested
there.
"""

from __future__ import annotations

import logging

import pytest
from agent_intent.watching import watch_once
from argus_core import new_id
from argus_core.events import (
    AgentInvoked,
    IncidentEvent,
    PersonWrote,
    RecordedEvent,
)
from argus_core.models import Actor, ReportChannel, a_chat_message
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged

SOME_INCIDENT = new_id()


@pytest.mark.unit
def test_each_message_a_person_wrote_is_heard_in_the_order_it_was_written() -> None:
    first, second = _a_person_writing("first"), _a_person_writing("second")
    a_log = _a_log(first, second)
    understood: list[PersonWrote] = []

    Scenario() \
        .when(lambda: watch_once(a_log.backlog, a_log, understood.append)) \
        .then(all_of(_it_understood(understood, [first, second]), _the_place_is(a_log, 2)))


@pytest.mark.unit
def test_everything_else_is_passed_over_and_the_place_moves_past_it() -> None:
    a_log = _a_log(AgentInvoked(incident_id=SOME_INCIDENT, agent=Actor.INVESTIGATOR))
    understood: list[PersonWrote] = []

    Scenario() \
        .when(lambda: watch_once(a_log.backlog, a_log, understood.append)) \
        .then(all_of(_it_understood(understood, []), _the_place_is(a_log, 1)))


@pytest.mark.unit
def test_a_message_that_could_not_be_heard_stops_the_look_in_front_of_it(
        caplog: pytest.LogCaptureFixture) -> None:
    first, second = _a_person_writing("first"), _a_person_writing("second")
    a_log = _a_log(first, second)

    def understanding_fails(written: PersonWrote) -> None:
        raise ConnectionError("the model could not be reached")

    Scenario() \
        .when(lambda: watch_once(a_log.backlog, a_log, understanding_fails)) \
        .then(all_of(
            _the_place_is(a_log, 0),
            one_record_was_logged(caplog, "agent_intent.watching", logging.WARNING,
                                  "message not understood", failure=ConnectionError)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("published", "looked_at"), [(0, 0), (3, 3)])
def test_a_look_says_how_many_events_it_dealt_with(published: int, looked_at: int) -> None:
    # What the process waits on: a look that found nothing waits before the
    # next, and one that found something looks again at once.
    a_log = _a_log(*(_a_person_writing(f"message {n}") for n in range(published)))

    Scenario() \
        .when(lambda: watch_once(a_log.backlog, a_log, lambda _: None)) \
        .then(_it_answers(looked_at))


def _a_person_writing(words: str) -> PersonWrote:
    return PersonWrote(incident_id=SOME_INCIDENT,
                       message=a_chat_message(ReportChannel.SLACK, "C-some-channel", words),
                       person_id="U-some-person",
                       text=words)


class _ALog:
    """A log holding these events at places 1, 2, 3..., and a place in it."""

    def __init__(self, *events: IncidentEvent) -> None:
        self._recorded = [RecordedEvent(seq=seq, event=event)
                          for seq, event in enumerate(events, start=1)]
        self.place = 0

    def backlog(self, since: int, batch: int, /) -> list[RecordedEvent]:
        return [recorded for recorded in self._recorded if recorded.seq > since][:batch]

    def where(self) -> int:
        return self.place

    def move_to(self, seq: int, /) -> None:
        self.place = seq


def _a_log(*events: IncidentEvent) -> _ALog:
    return _ALog(*events)


def _it_understood(understood: list[PersonWrote], expected: list[PersonWrote]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if understood != expected:
            raise AssertionError(
                f"Expected to understand {[w.text for w in expected]}, "
                f"understood {[w.text for w in understood]}."
            )

        return True

    return assertion


def _the_place_is(a_log: _ALog, expected: int) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if a_log.place != expected:
            raise AssertionError(f"Expected the place {expected}, got {a_log.place}.")

        return True

    return assertion


def _it_answers(expected: int) -> Assertion[int]:
    def assertion(looked_at: int) -> bool:
        if looked_at != expected:
            raise AssertionError(f"Expected {expected} events dealt with, got {looked_at}.")

        return True

    return assertion
