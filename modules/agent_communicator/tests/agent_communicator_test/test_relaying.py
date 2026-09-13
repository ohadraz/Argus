from __future__ import annotations

import pytest
from agent_communicator.policy import Register
from agent_communicator.relaying import Outcome, relay_once
from argus_core.events import (
    ActionTaken,
    IncidentEvent,
    OnsetDetected,
    RetrievalChannel,
    RetrievalRequested,
    StatusChanged,
)
from argus_core.ids import new_id
from argus_core.models.incident_status import IncidentStatus
from argus_incidents.repository import events
from argus_narration import NarrationLine, a_narration_line
from argus_testkit import Assertion, Scenario, all_of, calling

"""Slack as a projection of the event log, rather than calls inside the walk.

The relay follows what was published and says it somewhere a human is: it reads
from the place it got to last time, delivers what it finds in the order it
happened, and moves its place on behind itself. Nothing in the walk calls it,
which is exactly the point - a step is reported because it was published, not
because somebody remembered to report it.

The log and the place are seams, not a database: what is decided here is what
gets said and in what order, and a test about that has no business waiting for
a container. Where those seams reach postgres is `following`, and its own test
is what says the wiring is real.

Delivery is at-least-once. A line said twice is a nuisance; a line nobody ever
says is the failure this exists to prevent, so the place only ever moves past a
line that landed - or past one nobody was ever going to be told about.
"""

AN_INCIDENT = new_id()


@pytest.mark.unit
def test_everything_since_the_place_is_delivered_in_order() -> None:
    # The order is the account: an incident whose mitigation is read before the
    # onset that prompted it is a different story from the one that happened.
    a_relay = _a_relay_that_takes_everything()

    Scenario() \
        .given(
            the_log := _a_log_holding(_three_steps_of(AN_INCIDENT)),
            the_place := _a_place_at(0)
        ) \
        .when(lambda: relay_once(the_log, the_place, a_relay)) \
        .then(all_of(
            _it_delivered(3),
            _the_lines_delivered_were(a_relay, ["onset-detected",
                                                "action-taken",
                                                "status-changed"]),
            _they_were_all_about(a_relay, AN_INCIDENT)
        ))


@pytest.mark.unit
def test_a_line_already_behind_the_place_is_not_said_again() -> None:
    # The place is the whole of the relay's memory. Reading from the beginning
    # every time would say an incident over from the top on every pass, which
    # is the failure that makes people mute a channel.
    a_relay = _a_relay_that_takes_everything()
    the_first_two = 2

    Scenario() \
        .given(
            the_log := _a_log_holding(_three_steps_of(AN_INCIDENT)),
            the_place := _a_place_at(the_first_two)
        ) \
        .when(lambda: relay_once(the_log, the_place, a_relay)) \
        .then(all_of(
            _it_delivered(1),
            _the_lines_delivered_were(a_relay, ["status-changed"])
        ))


@pytest.mark.unit
def test_the_place_moves_to_the_last_line_that_landed() -> None:
    # Behind each line rather than after the batch: a relay killed mid-pass
    # carries on from the last thing anybody actually saw.
    a_relay = _a_relay_that_takes_everything()

    Scenario() \
        .given(
            the_log := _a_log_holding(_three_steps_of(AN_INCIDENT)),
            the_place := _a_place_at(0)
        ) \
        .when(lambda: relay_once(the_log, the_place, a_relay)) \
        .then(_the_place_is_now(the_place, 3))


@pytest.mark.unit
def test_a_line_that_could_not_be_said_now_stops_the_batch_where_it_is() -> None:
    # Slack throttled it, or was not there at all. Neither says anything about
    # the line, so the place must not move past it - and the lines behind it
    # wait, because delivering them now would tell the story with its middle
    # missing and never fill the gap in.
    a_relay = _a_relay_that_cannot_say_more_now(1)

    Scenario() \
        .given(
            the_log := _a_log_holding(_three_steps_of(AN_INCIDENT)),
            the_place := _a_place_at(0)
        ) \
        .when(lambda: relay_once(the_log, the_place, a_relay)) \
        .then(all_of(
            _it_delivered(1),
            _the_lines_delivered_were(a_relay, ["onset-detected"]),
            _the_place_is_now(the_place, 1)
        ))


@pytest.mark.unit
def test_a_line_that_will_never_be_said_is_passed_over_rather_than_waited_on() -> None:
    # A renamed channel, a revoked token: as true on the next pass as on this
    # one. The line is lost and the destination writes that down where it will
    # be seen; holding the place for it would lose every line behind it too,
    # for as long as the workspace stays the way it is.
    a_relay = _a_relay_that_will_never_say_more(1)

    Scenario() \
        .given(
            the_log := _a_log_holding(_three_steps_of(AN_INCIDENT)),
            the_place := _a_place_at(0)
        ) \
        .when(lambda: relay_once(the_log, the_place, a_relay)) \
        .then(all_of(
            _it_delivered(1),
            _the_lines_delivered_were(a_relay, ["onset-detected"]),
            _the_place_is_now(the_place, 3)
        ))


@pytest.mark.unit
def test_a_look_with_nothing_new_says_nothing_and_stays_where_it_is() -> None:
    # The state the relay is in almost all the time: caught up, with nothing to
    # add. Nothing is not an error and not a reason to start again.
    a_relay = _a_relay_that_takes_everything()
    the_end_of_the_log = 3

    Scenario() \
        .given(
            the_log := _a_log_holding(_three_steps_of(AN_INCIDENT)),
            the_place := _a_place_at(the_end_of_the_log)
        ) \
        .when(lambda: relay_once(the_log, the_place, a_relay)) \
        .then(all_of(
            _it_delivered(0),
            _the_lines_delivered_were(a_relay, []),
            _the_place_is_now(the_place, the_end_of_the_log)
        ))


@pytest.mark.unit
def test_a_line_nobody_needs_to_hear_is_not_delivered() -> None:
    # The policy's decision, honoured here. Everything is published and
    # everything is on the dashboard; what reaches a person is what it found,
    # changed or concluded, not the reading it did to get there.
    a_relay = _a_relay_that_takes_everything()

    Scenario() \
        .given(
            the_log := _a_log_holding(_three_steps_with_a_look_between(AN_INCIDENT)),
            the_place := _a_place_at(0)
        ) \
        .when(lambda: relay_once(the_log, the_place, a_relay)) \
        .then(all_of(
            _it_delivered(3),
            _the_lines_delivered_were(a_relay, ["onset-detected",
                                                "action-taken",
                                                "status-changed"])
        ))


@pytest.mark.unit
def test_the_place_moves_past_a_line_nobody_needs_to_hear() -> None:
    # Skipped, not held. A relay whose place stopped at the first retrieval
    # would sit there forever, re-reading a line it is never going to say and
    # never reaching the ones it would.
    a_relay = _a_relay_that_takes_everything()
    the_whole_log = 4

    Scenario() \
        .given(
            the_log := _a_log_holding(_three_steps_with_a_look_between(AN_INCIDENT)),
            the_place := _a_place_at(0)
        ) \
        .when(lambda: relay_once(the_log, the_place, a_relay)) \
        .then(_the_place_is_now(the_place, the_whole_log))


@pytest.mark.unit
def test_how_loudly_each_line_is_said_travels_with_it() -> None:
    # The register is the policy's, and the destination's job is to translate
    # it - a thread reply or a channel message in Slack. A relay that decided
    # that itself would have put Slack's furniture in the one place that is
    # meant to outlast the choice of destination.
    a_relay = _a_relay_that_takes_everything()

    Scenario() \
        .given(
            the_log := _a_log_holding(_three_steps_of(AN_INCIDENT)),
            the_place := _a_place_at(0)
        ) \
        .when(lambda: relay_once(the_log, the_place, a_relay)) \
        .then(_they_were_said(a_relay, [Register.FOLLOWED,
                                        Register.FOLLOWED,
                                        Register.ANNOUNCED]))


@pytest.mark.unit
def test_the_words_delivered_are_the_ones_the_dashboard_shows() -> None:
    # One account, rendered once. A relay that wrote its own sentences would be
    # a second narrator, and the day the two disagreed there would be no way to
    # tell which of them had it right.
    a_relay = _a_relay_that_takes_everything()
    the_steps = _three_steps_of(AN_INCIDENT)

    Scenario() \
        .given(
            the_log := _a_log_holding(the_steps),
            the_place := _a_place_at(0)
        ) \
        .when(lambda: relay_once(the_log, the_place, a_relay)) \
        .then(_they_read_as_the_narration_of(a_relay, the_steps))


@pytest.mark.unit
def test_the_log_is_asked_for_no_more_than_one_batch() -> None:
    # A relay an hour behind catches up a batch at a time rather than reading
    # an hour of events into memory, and what it does not reach this time it
    # reaches next time.
    a_relay = _a_relay_that_takes_everything()
    room_for_two = 2

    Scenario() \
        .given(
            the_log := _a_log_holding(_three_steps_of(AN_INCIDENT)),
            the_place := _a_place_at(0),
            calling(lambda: relay_once(the_log, the_place, a_relay, batch=room_for_two))
        ) \
        .when(lambda: the_log.asked_for) \
        .then(_it_asked_for(room_for_two))


class _ALog:
    """The log, holding what was published and handing back what follows.

    The same arithmetic the repository does - everything after a place, oldest
    first, capped - so that a test can put the relay anywhere in a log without
    a database to put events into.
    """

    def __init__(self, published: list[IncidentEvent]) -> None:
        self._recorded = [
            events.RecordedEvent(seq=place, event=event)
            for place, event in enumerate(published, start=1)
        ]
        self.asked_for: int | None = None

    def __call__(self, since: int, batch: int, /) -> list[events.RecordedEvent]:
        self.asked_for = batch
        following = [entry for entry in self._recorded if entry.seq > since]

        return following[:batch]


class _APlace:
    """Where a reader got to, remembered for as long as the test runs."""

    def __init__(self, at: int) -> None:
        self._at = at

    def where(self) -> int:
        return self._at

    def move_to(self, seq: int, /) -> None:
        self._at = seq


class _ARelay:
    """A destination that remembers what it was told, and can refuse.

    Hand-written rather than a mock because every test here asks the same three
    questions - what was said, how loudly, and in what order - and a recorder
    answers them in the language of the subject rather than in call tuples.
    """

    def __init__(self,
                 gives_up_after: int | None = None,
                 gives_up_with: Outcome = Outcome.NOT_NOW) -> None:
        self.told: list[tuple[str, NarrationLine, Register]] = []
        self._gives_up_after = gives_up_after
        self._gives_up_with = gives_up_with

    def __call__(self,
                 incident_id: str,
                 line: NarrationLine,
                 register: Register, /) -> Outcome:
        if (self._gives_up_after is not None
                and len(self.told) >= self._gives_up_after):
            return self._gives_up_with

        self.told.append((incident_id, line, register))

        return Outcome.SAID


def _a_log_holding(published: list[IncidentEvent]) -> _ALog:
    return _ALog(published)


def _a_place_at(seq: int) -> _APlace:
    return _APlace(seq)


def _a_relay_that_takes_everything() -> _ARelay:
    return _ARelay()


def _a_relay_that_cannot_say_more_now(landed: int) -> _ARelay:
    return _ARelay(gives_up_after=landed, gives_up_with=Outcome.NOT_NOW)


def _a_relay_that_will_never_say_more(landed: int) -> _ARelay:
    return _ARelay(gives_up_after=landed, gives_up_with=Outcome.NEVER)


def _three_steps_of(incident_id: str) -> list[IncidentEvent]:
    """An incident's onset, the action taken for it, and where it ended.

    Three things a human is meant to hear, so that what these tests measure is
    the reading, the order and the place rather than the policy.
    """
    return [
        OnsetDetected(incident_id=incident_id, onset="2026-08-30T10:03:00Z"),
        ActionTaken(
            incident_id=incident_id,
            hypothesis_id=None,
            action_type="revert-feature-flag",
            subject="monthly-spend-feature",
            enabled=False
        ),
        StatusChanged(incident_id=incident_id, to_status=IncidentStatus.RESOLVED)
    ]


def _three_steps_with_a_look_between(incident_id: str) -> list[IncidentEvent]:
    """The same three, with a retrieval in the middle that nobody hears."""
    onset, action, ending = _three_steps_of(incident_id)

    return [
        onset,
        RetrievalRequested(
            incident_id=incident_id,
            channel=RetrievalChannel.LOGS,
            window_start="2026-08-30T10:02:00Z",
            window_end="2026-08-30T10:12:00Z"
        ),
        action,
        ending
    ]


def _it_delivered(expected: int) -> Assertion[int]:
    def assertion(delivered: int) -> bool:
        if delivered != expected:
            raise AssertionError(
                f"Expected {expected} lines to be delivered, it reported {delivered}."
            )

        return True

    return assertion


def _it_asked_for(expected: int) -> Assertion[int | None]:
    def assertion(batch: int | None) -> bool:
        if batch != expected:
            raise AssertionError(
                f"Expected the log to be asked for {expected} at a time, "
                f"it was asked for {batch}."
            )

        return True

    return assertion


def _the_place_is_now(place: _APlace, expected: int) -> Assertion[object]:
    def assertion(_: object) -> bool:
        if place.where() != expected:
            raise AssertionError(
                f"Expected the place to be {expected}, it is {place.where()}."
            )

        return True

    return assertion


def _the_lines_delivered_were(relay: _ARelay, expected: list[str]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        kinds = [line.kind for _, line, _ in relay.told]
        if kinds != expected:
            raise AssertionError(f"Expected the lines {expected}, got {kinds}.")

        return True

    return assertion


def _they_were_said(relay: _ARelay, expected: list[Register]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        registers = [register for _, _, register in relay.told]
        if registers != expected:
            raise AssertionError(
                f"Expected them said {expected}, they were said {registers}."
            )

        return True

    return assertion


def _they_were_all_about(relay: _ARelay, expected: str) -> Assertion[object]:
    def assertion(_: object) -> bool:
        about = {incident_id for incident_id, _, _ in relay.told}
        if about != {expected}:
            raise AssertionError(
                f"Expected every line to be about [{expected}], got {about}."
            )

        return True

    return assertion


def _they_read_as_the_narration_of(relay: _ARelay,
                                   published: list[IncidentEvent]) -> Assertion[object]:
    def assertion(_: object) -> bool:
        said = [line.text for _, line, _ in relay.told]
        the_narration = [a_narration_line(event).text for event in published]
        if said != the_narration:
            raise AssertionError(
                f"Expected the narration's own words {the_narration}, got {said}."
            )

        return True

    return assertion
