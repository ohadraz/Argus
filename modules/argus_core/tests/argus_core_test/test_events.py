from __future__ import annotations

import pytest
from argus_core.events import (
    AgentInvoked,
    IncidentEvent,
    LogsRetrieved,
    Publisher,
    RetrievalChannel,
    RetrievalRequested,
    VerdictReached,
    parse_event,
    publish,
)
from argus_core.ids import new_id
from argus_core.models.action import Verdict
from argus_core.models.actor import Actor
from argus_testkit import Assertion, Scenario, all_of, attempting
from pydantic import ValidationError

"""What Argus says about its own work, and the one rule that says on it.

An event is an account of something that happened - it names the incident, the
moment, and enough of the values involved that somebody reading it months later
needs nothing but the event. The rule is that publishing one can never change
what Argus decides, which here means it cannot fail a caller either.

Where an event carries a word from a vocabulary this system already names, it
carries the value rather than the spelling: a reader that has to know which of
four words means "it worked" is a reader that will one day match none of them.
"""

SOME_WINDOW_START = "2026-08-30T10:02:00Z"
SOME_WINDOW_END = "2026-08-30T10:12:00Z"


@pytest.mark.unit
def test_an_event_names_the_incident_it_belongs_to() -> None:
    # An event that cannot be attributed to an incident is a line in a log
    # file, which is what the system already had and could not read.
    some_incident_id = new_id()

    Scenario() \
        .given(some_incident_id) \
        .when(lambda: AgentInvoked(incident_id=some_incident_id,
                                   agent=Actor.INVESTIGATOR)) \
        .then(_it_belongs_to(some_incident_id))


@pytest.mark.unit
def test_an_event_knows_when_it_happened_without_being_told() -> None:
    # The moment is the event's own, taken where it is built - a caller that
    # had to supply it could supply the wrong one, and a narration ordered by
    # when rows were written is a narration of the database's day.
    Scenario() \
        .given(dont_care_incident := new_id()) \
        .when(lambda: AgentInvoked(incident_id=dont_care_incident,
                                   agent=Actor.INVESTIGATOR)) \
        .then(_it_is_stamped())


@pytest.mark.unit
def test_a_retrieval_names_its_channel_and_both_bounds_of_its_window() -> None:
    # "Argus looked at the logs" is not readable; "Argus looked at the logs
    # between 10:02 and 10:12" is. A window with one bound is a window nobody
    # can check the answer against.
    Scenario() \
        .given(dont_care_incident := new_id()) \
        .when(lambda: RetrievalRequested(
            incident_id=dont_care_incident,
            channel=RetrievalChannel.LOGS,
            window_start=SOME_WINDOW_START,
            window_end=SOME_WINDOW_END
        )) \
        .then(all_of(_it_asked_about(RetrievalChannel.LOGS),
                     _it_asked_between(SOME_WINDOW_START, SOME_WINDOW_END)))


@pytest.mark.unit
def test_a_retrieval_that_returned_carries_what_came_back() -> None:
    # The whole point of storing the payload: the page shows what Argus read,
    # not what the log store happens to hold when somebody opens the page.
    the_lines_it_read = [
        "2026-08-30T10:03:00Z ERROR io-shop: division by zero",
        "2026-08-30T10:03:00Z INFO io-shop: monthly-spend-feature=on"
    ]

    Scenario() \
        .given(the_lines_it_read) \
        .when(lambda: LogsRetrieved(
            incident_id=new_id(),
            window_start=SOME_WINDOW_START,
            window_end=SOME_WINDOW_END,
            lines=the_lines_it_read
        )) \
        .then(_it_carries(the_lines_it_read))


@pytest.mark.unit
def test_an_event_read_back_is_the_event_that_was_published() -> None:
    # It is written to a table and read out again, and what comes back has to
    # be the same kind of thing it went in as - otherwise every reader is left
    # matching on strings to work out what it is holding.
    Scenario() \
        .given(
            published := LogsRetrieved(
                incident_id=new_id(),
                window_start=SOME_WINDOW_START,
                window_end=SOME_WINDOW_END,
                lines=["some log line"]
            )
        ) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(_it_is(published))


@pytest.mark.unit
def test_a_verdict_is_one_of_the_answers_mitigation_gives() -> None:
    # The vocabulary already has a name in this codebase. Carried as the value,
    # an outcome nobody defined is refused where it is published rather than
    # reaching a page that compares spellings and quietly matches none of them.
    some_word_that_is_not_a_verdict = "probably"

    Scenario() \
        .given(some_word_that_is_not_a_verdict) \
        .when(attempting(lambda: VerdictReached.model_validate({
            "incident_id": new_id(),
            "hypothesis_id": None,
            "outcome": some_word_that_is_not_a_verdict
        }))) \
        .then(_it_was_refused())


@pytest.mark.unit
def test_a_verdict_read_back_is_the_answer_it_was_published_as() -> None:
    # Written as its own spelling and read back as the value, so what a reader
    # holds can be compared rather than recognised.
    Scenario() \
        .given(
            published := VerdictReached(incident_id=new_id(),
                                        hypothesis_id=None,
                                        outcome=Verdict.CONFIRMED)
        ) \
        .when(lambda: parse_event(published.model_dump(mode="json"))) \
        .then(all_of(_it_is(published), _its_verdict_is(Verdict.CONFIRMED)))


@pytest.mark.unit
def test_an_event_reaches_the_publisher_it_was_given() -> None:
    everything_published: list[IncidentEvent] = []
    an_event = AgentInvoked(incident_id=new_id(), agent=Actor.MITIGATION)

    Scenario() \
        .given(everything_published) \
        .when(lambda: publish(an_event, publisher=everything_published.append)) \
        .then(_what_was_published(everything_published, [an_event]))


@pytest.mark.unit
def test_a_publisher_that_fails_does_not_fail_the_work_it_was_describing() -> None:
    # The account of the work is never part of the work. An incident that
    # would have resolved must resolve even when nobody could write down that
    # it was resolving.
    Scenario() \
        .given(a_failing_publisher := _a_publisher_having_a_bad_day()) \
        .when(attempting(lambda: publish(
            AgentInvoked(incident_id=new_id(), agent=Actor.INVESTIGATOR),
            publisher=a_failing_publisher
        ))) \
        .then(_nothing_was_raised())


@pytest.mark.unit
def test_publishing_reaches_nobody_by_default() -> None:
    # A component publishes whether or not anything is listening, and nothing
    # about its behaviour changes either way. The default is where that is
    # true by construction.
    Scenario() \
        .given(dont_care_incident := new_id()) \
        .when(attempting(lambda: publish(
            AgentInvoked(incident_id=dont_care_incident, agent=Actor.INVESTIGATOR)
        ))) \
        .then(_nothing_was_raised())


def _a_publisher_having_a_bad_day() -> Publisher:
    """A subscriber that throws on everything it is handed."""
    def raise_on_everything(dont_care_event: IncidentEvent) -> None:
        raise RuntimeError("the subscriber is having a bad day")

    return raise_on_everything


def _a_verdict_in(read_back: object) -> VerdictReached:
    """What came back, as the type it was published as - or the failure to be.

    Read here rather than asserted in three places: every claim below about a
    verdict starts by holding one, and a reader that got something else has
    already learned the only thing worth reporting.
    """
    if not isinstance(read_back, VerdictReached):
        raise AssertionError(f"expected a verdict, got [{type(read_back).__name__}]")

    return read_back


def _it_belongs_to(incident_id: str) -> Assertion[IncidentEvent]:
    def assertion(event: IncidentEvent) -> bool:
        if event.incident_id != incident_id:
            raise AssertionError(
                f"expected it about [{incident_id}], it is about [{event.incident_id}]"
            )

        return True

    return assertion


def _it_is_stamped() -> Assertion[IncidentEvent]:
    def assertion(event: IncidentEvent) -> bool:
        if event.at is None:
            raise AssertionError("expected the event to know when it happened, it has no moment")

        return True

    return assertion


def _it_asked_about(channel: RetrievalChannel) -> Assertion[RetrievalRequested]:
    def assertion(requested: RetrievalRequested) -> bool:
        if requested.channel is not channel:
            raise AssertionError(
                f"expected it to ask about [{channel}], it asked about [{requested.channel}]"
            )

        return True

    return assertion


def _it_asked_between(start: str, end: str) -> Assertion[RetrievalRequested]:
    def assertion(requested: RetrievalRequested) -> bool:
        asked = (requested.window_start, requested.window_end)
        if asked != (start, end):
            raise AssertionError(f"expected the window {(start, end)}, got {asked}")

        return True

    return assertion


def _it_carries(lines: list[str]) -> Assertion[LogsRetrieved]:
    def assertion(retrieved: LogsRetrieved) -> bool:
        if retrieved.lines != lines:
            raise AssertionError(f"expected it to carry {lines}, it carries {retrieved.lines}")

        return True

    return assertion


def _it_is(published: IncidentEvent) -> Assertion[object]:
    def assertion(read_back: object) -> bool:
        if read_back != published:
            raise AssertionError(f"expected [{published}], got [{read_back}]")

        return True

    return assertion


def _its_verdict_is(expected: Verdict) -> Assertion[object]:
    def assertion(read_back: object) -> bool:
        outcome = _a_verdict_in(read_back).outcome
        if outcome is not expected:
            raise AssertionError(f"expected [{expected!r}], got [{outcome!r}]")

        return True

    return assertion


def _it_was_refused() -> Assertion[Exception | None]:
    """An unknown verdict does not become an event.

    Refused where it is built rather than where it is read: an event that
    reached the log carrying a word nothing recognises is one every reader
    afterwards has to decide what to do about.
    """
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, ValidationError):
            raise AssertionError(f"expected the verdict refused, got [{raised}]")

        return True

    return assertion


def _what_was_published(published: list[IncidentEvent],
                        expected: list[IncidentEvent]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if published != expected:
            raise AssertionError(f"expected {expected} published, got {published}")

        return True

    return assertion


def _nothing_was_raised() -> Assertion[Exception | None]:
    """Publishing answers rather than throwing, whatever the subscriber does."""
    def assertion(raised: Exception | None) -> bool:
        if raised is not None:
            raise AssertionError(
                f"expected the work to survive, got [{type(raised).__name__}]: {raised}"
            )

        return True

    return assertion
