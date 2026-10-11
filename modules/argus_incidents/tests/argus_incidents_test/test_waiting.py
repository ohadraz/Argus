"""A walk waiting on a person who said the incident was over.

Argus asked them to confirm. Until they answer - or until they have had long
enough to - a step started is work they may be about to make pointless, so the
walk starts none. A step already running is not cut off; the wait is asked
between steps, and this is what is asked.

What is asked of is the incident's record of what people wrote, never the event
log: an account that could hold a walk would be a participant. An expiry is
kept on the record first and told after, for the same reason.

The clock and the sleep are handed in, so every case here runs on a clock that
moves only when the wait sleeps on it, and none of them waits on a real one.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from argus_core import connect_from_env, new_id
from argus_core.events import OfferExpired
from argus_core.models import (
    Alert,
    IncidentStatus,
    Meaning,
    Offer,
    Reference,
    ThreadMessage,
)
from argus_incidents.ending import EndedByAPerson
from argus_incidents.publishing import events_into
from argus_incidents.repository import conversation, events, incidents
from argus_incidents.waiting import (
    HOW_LONG_A_PERSON_IS_WAITED_FOR,
    WaitForPeople,
    waiting_for_people,
    waiting_for_people_via,
)
from argus_testkit import Assertion, Scenario, all_of, calling, one_record_was_logged

SOME_MOMENT = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
SOME_MESSAGE = Reference(source="some-chat", kind="chat-message", value="C1/1.000001")
ANOTHER_MESSAGE = Reference(source="some-chat", kind="chat-message", value="C1/1.000002")


class _AClock:
    """A clock that moves only when somebody sleeps on it."""

    def __init__(self, starting_at: datetime) -> None:
        self.reading = starting_at
        self.sleeps = 0

    def now(self) -> datetime:
        return self.reading

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        self.reading += timedelta(seconds=seconds)


@dataclass(frozen=True)
class _ExpiryKept:
    """The record told an offer expired."""

    message: Reference


@pytest.mark.unit
def test_an_incident_nobody_wrote_about_is_not_waited_on() -> None:
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(_reading([]), a_clock, happened)(new_id())) \
        .then(all_of(_it_did_not_wait(a_clock), _nothing_was_expired(happened),
                     _the_walk_is_told_to_ask_again(False)))


@pytest.mark.unit
@pytest.mark.parametrize("meaning", [Meaning.QUESTION, Meaning.INFORMATION, Meaning.OTHER])
def test_a_message_that_asks_for_no_ending_is_not_waited_on(meaning: Meaning) -> None:
    # Nothing was offered, so there is nothing for anybody to answer. A walk
    # that stopped for "thanks" would be a walk any message could stall.
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(
            _reading([_understood(some_incident, SOME_MESSAGE, meaning, at=SOME_MOMENT)]),
            a_clock, happened
        )(some_incident)) \
        .then(all_of(_it_did_not_wait(a_clock), _nothing_was_expired(happened),
                     _the_walk_is_told_to_ask_again(False)))


@pytest.mark.unit
def test_a_message_not_yet_classified_is_waited_on_until_it_is() -> None:
    # Stored, and not yet read for what it means. The walk does not get to
    # pass the moment between a message arriving and its offer being made: it
    # waits from the message, not from the button.
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(
            _reading([_written(some_incident, SOME_MESSAGE, at=SOME_MOMENT)],
                     [_understood(some_incident, SOME_MESSAGE, Meaning.QUESTION,
                                  at=SOME_MOMENT)]),
            a_clock, happened
        )(some_incident)) \
        .then(all_of(_it_waited(a_clock), _nothing_was_expired(happened),
                     _the_walk_is_told_to_ask_again(True)))


@pytest.mark.unit
@pytest.mark.parametrize("ending", [IncidentStatus.RESOLVED, IncidentStatus.WITHDRAWN])
def test_an_offer_is_waited_on_until_a_person_ends_the_incident(ending: IncidentStatus) -> None:
    # The press is the answer, and it reaches the walk as the incident's
    # ending. So does anybody else's ending meanwhile: an incident somebody
    # took back is no longer waiting on a confirmation either.
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(
            _reading([_offered_on(some_incident, SOME_MESSAGE, at=SOME_MOMENT)]),
            a_clock, happened,
            ended_by_a_person=_ended_after(2, ending)
        )(some_incident)) \
        .then(all_of(_it_waited(a_clock), _nothing_was_expired(happened),
                     _the_walk_is_told_to_ask_again(True)))


@pytest.mark.unit
def test_a_request_to_stand_down_is_waited_on_until_the_person_withdraws_the_incident() -> None:
    # A step started while somebody is about to take the incident back is a
    # change they will watch Argus put back a minute later.
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(
            _reading([_withdrawal_offered_on(some_incident, SOME_MESSAGE, at=SOME_MOMENT)]),
            a_clock, happened,
            ended_by_a_person=_ended_after(2, IncidentStatus.WITHDRAWN)
        )(some_incident)) \
        .then(all_of(_it_waited(a_clock), _nothing_was_expired(happened),
                     _the_walk_is_told_to_ask_again(True)))


@pytest.mark.unit
def test_a_withdrawal_offer_nobody_pressed_expires_as_a_resolution_offer_does() -> None:
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(
            _reading([_withdrawal_offered_on(some_incident, SOME_MESSAGE, at=SOME_MOMENT)]),
            a_clock, happened
        )(some_incident)) \
        .then(all_of(
            _these_were_expired(happened, [SOME_MESSAGE]),
            _the_clock_reads_no_earlier_than(a_clock,
                                             SOME_MOMENT + HOW_LONG_A_PERSON_IS_WAITED_FOR),
            _the_walk_is_told_to_ask_again(True)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("asked_for", "status"), [
    ("withdrawal-offered", IncidentStatus.MITIGATED),
    ("withdrawal-not-offered", IncidentStatus.MITIGATED),
    ("resolution-not-offered", IncidentStatus.DISPROVEN)
])
def test_a_message_asking_for_an_ending_the_incident_no_longer_accepts_is_not_waited_on(
        asked_for: str, status: IncidentStatus) -> None:
    # Code-Fix finished with the incident mitigated, and the walk has its
    # write-up still to do. Nobody can confirm a withdrawal of a mitigated
    # incident, so a wait for the press is five minutes spent on a button that
    # does nothing - offered or not, since an offer the agent declined to make
    # is no more answerable than one it made too early.
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []
    some_incident = new_id()
    askings = {
        "withdrawal-offered": _withdrawal_offered_on(some_incident, SOME_MESSAGE,
                                                     at=SOME_MOMENT),
        "withdrawal-not-offered": _understood(some_incident, SOME_MESSAGE, Meaning.WITHDRAW,
                                              at=SOME_MOMENT),
        "resolution-not-offered": _understood(some_incident, SOME_MESSAGE, Meaning.RESOLVE,
                                              at=SOME_MOMENT)
    }
    asking = askings[asked_for]

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(_reading([asking]), a_clock, happened,
                              status=status)(some_incident)) \
        .then(all_of(_it_did_not_wait(a_clock), _nothing_was_expired(happened),
                     _the_walk_is_told_to_ask_again(False)))


@pytest.mark.unit
def test_a_resolution_offer_on_a_mitigated_incident_is_still_waited_on() -> None:
    # Mitigated still accepts a resolution - a person who finished the job is
    # reporting exactly that - so the offer can still be confirmed, and is
    # waited on, while a withdrawal offer beside it would not be.
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(
            _reading([_offered_on(some_incident, SOME_MESSAGE, at=SOME_MOMENT)]),
            a_clock, happened, status=IncidentStatus.MITIGATED
        )(some_incident)) \
        .then(all_of(_it_waited(a_clock), _these_were_expired(happened, [SOME_MESSAGE])))


@pytest.mark.unit
def test_an_offer_nobody_pressed_expires_once_the_person_has_had_long_enough() -> None:
    # Counted from the message: that is when the person said it, and a slow
    # classification is Argus's delay, not theirs to make up.
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(
            _reading([_offered_on(some_incident, SOME_MESSAGE, at=SOME_MOMENT)]),
            a_clock, happened
        )(some_incident)) \
        .then(all_of(
            _these_were_expired(happened, [SOME_MESSAGE]),
            _the_clock_reads_no_earlier_than(a_clock,
                                             SOME_MOMENT + HOW_LONG_A_PERSON_IS_WAITED_FOR),
            _the_walk_is_told_to_ask_again(True)
        ))


@pytest.mark.unit
def test_an_expiry_is_kept_before_it_is_told() -> None:
    # What decides on an offer - this wait, the press - reads the record. Told
    # first, the timeline could say an offer expired that a press could still
    # confirm.
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(
            _reading([_offered_on(some_incident, SOME_MESSAGE, at=SOME_MOMENT)]),
            a_clock, happened
        )(some_incident)) \
        .then(_the_expiry_was_kept_before_it_was_told(happened))


@pytest.mark.unit
def test_a_later_message_puts_every_offer_s_expiry_off() -> None:
    # Somebody said it again, or somebody else said it too. The question is
    # being asked afresh, so the walk waits afresh - and the offers expire
    # together, as one decision to carry on.
    # Written while the first offer still stands, so it is the later message
    # and not the clock that decides when both expire.
    the_last_message_at = SOME_MOMENT + HOW_LONG_A_PERSON_IS_WAITED_FOR - timedelta(minutes=1)
    a_clock = _AClock(the_last_message_at)
    happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(
            _reading([_offered_on(some_incident, SOME_MESSAGE, at=SOME_MOMENT),
                      _offered_on(some_incident, ANOTHER_MESSAGE, at=the_last_message_at)]),
            a_clock, happened
        )(some_incident)) \
        .then(all_of(
            _these_were_expired(happened, [SOME_MESSAGE, ANOTHER_MESSAGE]),
            _the_clock_reads_no_earlier_than(
                a_clock, the_last_message_at + HOW_LONG_A_PERSON_IS_WAITED_FOR)
        ))


@pytest.mark.unit
def test_an_offer_that_already_expired_is_not_waited_on_again() -> None:
    # The walk carried on without it once. Every step after that would stop
    # for it again otherwise, and a walk that carried on would never get far.
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(
            _reading([_an_expired_offer_on(some_incident, SOME_MESSAGE, at=SOME_MOMENT)]),
            a_clock, happened
        )(some_incident)) \
        .then(all_of(_it_did_not_wait(a_clock), _nothing_was_expired(happened),
                     _the_walk_is_told_to_ask_again(False)))


@pytest.mark.unit
def test_a_message_never_classified_in_time_is_carried_on_from_and_expires_nothing() -> None:
    # The intent agent is down. There is no offer to take away, so nothing is
    # said to have expired - but the walk does not wait on it for ever.
    a_clock = _AClock(SOME_MOMENT)
    happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(a_clock) \
        .when(lambda: _a_wait(
            _reading([_written(some_incident, SOME_MESSAGE, at=SOME_MOMENT)]),
            a_clock, happened
        )(some_incident)) \
        .then(all_of(
            _nothing_was_expired(happened),
            _the_clock_reads_no_earlier_than(a_clock,
                                             SOME_MOMENT + HOW_LONG_A_PERSON_IS_WAITED_FOR)
        ))


@pytest.mark.unit
def test_waiting_on_a_person_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # The longest a walk ever stands still on purpose, so it is said once,
    # as it starts - an operator watching a walk go quiet finds why here.
    a_clock = _AClock(SOME_MOMENT)
    dont_care_happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: _a_wait(
            _reading([_offered_on(some_incident, SOME_MESSAGE, at=SOME_MOMENT)]),
            a_clock, dont_care_happened
        )(some_incident)) \
        .then(one_record_was_logged(caplog, "argus_incidents.waiting", logging.INFO,
                                    "waiting for a person", values={"messages": 1}))


@pytest.mark.unit
def test_carrying_on_without_an_answer_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    a_clock = _AClock(SOME_MOMENT)
    dont_care_happened: list[object] = []
    some_incident = new_id()

    Scenario() \
        .given(calling(lambda: caplog.set_level(logging.INFO))) \
        .when(lambda: _a_wait(
            _reading([_offered_on(some_incident, SOME_MESSAGE, at=SOME_MOMENT)]),
            a_clock, dont_care_happened
        )(some_incident)) \
        .then(one_record_was_logged(caplog, "argus_incidents.waiting", logging.INFO,
                                    "offers not confirmed in time", values={"offers": 1}))


@pytest.mark.component
def test_an_expiry_is_kept_on_the_incident_and_told_among_its_events() -> None:
    # The real record and the real publisher: what the walk waited on is read
    # from the incident's record of what people wrote, the expiry is kept
    # there, and it is told among the incident's events, where the page, the
    # relay and the postmortem read it.
    a_clock = _AClock(SOME_MOMENT)

    with connect_from_env() as conn:
        incident_id = incidents.create(conn, Alert(service="io-shop",
                                                   alert_name="HighErrorRate"))
        conn.commit()
        conversation.write(conn, _written(incident_id, SOME_MESSAGE, at=SOME_MOMENT))
        conn.commit()
        conversation.understood(conn, SOME_MESSAGE, Meaning.RESOLVE)
        conversation.offered(conn, SOME_MESSAGE, IncidentStatus.RESOLVED)

    Scenario() \
        .given(incident_id) \
        .when(lambda: waiting_for_people_via(connect_from_env,
                                             events_into(connect_from_env),
                                             now=a_clock.now,
                                             sleep=a_clock.sleep)(incident_id)) \
        .then(all_of(_the_record_keeps_the_offer_expired(SOME_MESSAGE),
                     _the_incident_tells_of_the_expiry_of(incident_id, SOME_MESSAGE)))


def _a_wait(messages_of: Callable[[str], list[ThreadMessage]],
            clock: _AClock,
            happened: list[object],
            ended_by_a_person: EndedByAPerson | None = None,
            status: IncidentStatus = IncidentStatus.INVESTIGATING) -> WaitForPeople:
    """The wait over these reads, on an incident Argus is still working on
    unless `status` says otherwise, keeping and telling into `happened`."""
    return waiting_for_people(messages_of,
                              ended_by_a_person or _ended_after(None, None),
                              lambda _incident_id: status,
                              lambda message: happened.append(_ExpiryKept(message)),
                              happened.append,
                              now=clock.now,
                              sleep=clock.sleep)


def _reading(*snapshots: list[ThreadMessage]) -> Callable[[str], list[ThreadMessage]]:
    """The incident's messages, one snapshot per look, the last one for good."""
    remaining = list(snapshots)

    def messages_of(_incident_id: str) -> list[ThreadMessage]:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return messages_of


def _ended_after(looks: int | None, ending: IncidentStatus | None) -> EndedByAPerson:
    """Nobody's ending for `looks` questions, then `ending` - or never, for `None`."""
    asked = 0

    def ended_by_a_person(_incident_id: str, /) -> IncidentStatus | None:
        nonlocal asked
        asked += 1

        return ending if looks is not None and asked > looks else None

    return ended_by_a_person


def _written(incident_id: str, message: Reference, at: datetime) -> ThreadMessage:
    return ThreadMessage(incident_id=incident_id, message=message,
                         person_id="some-person-id", text="it's over", written_at=at)


def _understood(incident_id: str,
                message: Reference,
                meaning: Meaning,
                at: datetime) -> ThreadMessage:
    return _written(incident_id, message, at).model_copy(update={"meaning": meaning})


def _offered_on(incident_id: str, message: Reference, at: datetime) -> ThreadMessage:
    """A person saying it is over, read as such, and asked to confirm."""
    return _understood(incident_id, message, Meaning.RESOLVE, at).model_copy(update={
        "offer": Offer(ending=IncidentStatus.RESOLVED)
    })


def _an_expired_offer_on(incident_id: str, message: Reference, at: datetime) -> ThreadMessage:
    """A person saying it is over, asked to confirm, and the walk carried on
    without an answer."""
    return _understood(incident_id, message, Meaning.RESOLVE, at).model_copy(update={
        "offer": Offer(ending=IncidentStatus.RESOLVED, expired=True)
    })


def _withdrawal_offered_on(incident_id: str, message: Reference, at: datetime) -> ThreadMessage:
    """A person telling Argus to stand down, read as such, and asked to confirm."""
    return _understood(incident_id, message, Meaning.WITHDRAW, at).model_copy(update={
        "offer": Offer(ending=IncidentStatus.WITHDRAWN)
    })


def _the_walk_is_told_to_ask_again(expected: bool) -> Assertion[bool]:
    """Whether the wait tells the walk something happened it has to ask about -
    a person waited on, or the incident ended."""
    def assertion(told: bool) -> bool:
        if told is not expected:
            raise AssertionError(
                f"Expected the walk {'' if expected else 'not '}told to ask again how "
                f"the incident stands, it was told [{told}]."
            )

        return True

    return assertion


def _it_waited(clock: _AClock) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if clock.sleeps == 0:
            raise AssertionError("Expected the walk to wait, it went straight on.")

        return True

    return assertion


def _it_did_not_wait(clock: _AClock) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if clock.sleeps != 0:
            raise AssertionError(
                f"Expected the walk to go straight on, it slept {clock.sleeps} time(s)."
            )

        return True

    return assertion


def _nothing_was_expired(happened: list[object]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if happened:
            raise AssertionError(f"Expected no offer expired, got {happened}.")

        return True

    return assertion


def _these_were_expired(happened: list[object],
                        messages: list[Reference]) -> Assertion[object]:
    """Each of these offers kept as expired and told as expired, and nothing
    else kept or told."""
    def assertion(_: object) -> bool:
        kept = [entry.message for entry in happened if isinstance(entry, _ExpiryKept)]
        told = [entry.message for entry in happened if isinstance(entry, OfferExpired)]
        wanted = sorted(messages, key=str)

        if (len(kept) + len(told) != len(happened)
                or sorted(kept, key=str) != wanted or sorted(told, key=str) != wanted):
            raise AssertionError(
                f"Expected the offers about {messages} kept and told as expired, got "
                f"{happened}."
            )

        return True

    return assertion


def _the_expiry_was_kept_before_it_was_told(happened: list[object]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        order = [type(entry).__name__ for entry in happened]

        if order != [_ExpiryKept.__name__, OfferExpired.__name__]:
            raise AssertionError(f"Expected the expiry kept, then told, got {order}.")

        return True

    return assertion


def _the_clock_reads_no_earlier_than(clock: _AClock, moment: datetime) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if clock.reading < moment:
            raise AssertionError(
                f"Expected the walk to wait until [{moment}], it stopped at [{clock.reading}]."
            )

        return True

    return assertion


def _the_record_keeps_the_offer_expired(message: Reference) -> Assertion[object]:
    def assertion(_: object) -> bool:
        with connect_from_env() as conn:
            kept = conversation.get(conn, message)

        offer = kept.offer if kept is not None else None

        if offer is None or not offer.expired:
            raise AssertionError(
                f"Expected the record to keep the offer about [{message}] expired, it "
                f"keeps {offer}."
            )

        return True

    return assertion


def _the_incident_tells_of_the_expiry_of(incident_id: str,
                                         message: Reference) -> Assertion[object]:
    def assertion(_: object) -> bool:
        with connect_from_env() as conn:
            recorded = events.get_by_incident(conn, incident_id)

        expiries = [event.message for event in recorded if isinstance(event, OfferExpired)]

        if expiries != [message]:
            raise AssertionError(
                f"Expected the incident to tell of the offer about [{message}] expired, "
                f"it tells of {expiries}."
            )

        return True

    return assertion
