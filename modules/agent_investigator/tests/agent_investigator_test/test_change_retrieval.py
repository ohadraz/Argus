from __future__ import annotations

from unittest.mock import Mock, create_autospec

import pytest
from agent_investigator.retrieval import fetch_change_events
from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.models.flag_change import FlagChange
from argus_testkit import Assertion, Scenario, all_of
from read_mcp_client import get_change_events
from write_mcp_client import get_recent_flag_changes

"""What changed on the service, from both systems that record a change.

A deploy is not the only thing that changes what a service does - a feature
flag flipped is a change with no commit, no pipeline and no deploy record, and
until now the Investigator could only find one by noticing that some log line
happened to mention it. A cause that is only visible when the service says so
is a cause Argus finds by luck.

The two answers arrive from different tiers, and deliberately: the provider
serves its audit log to admin credentials only, and the read process holds
none. That makes flag history a read the *write* client offers - less than the
write tier can already do, and no loosening of the claim the split actually
makes, which is that the read process cannot mutate.

Merged here rather than by either server, so neither has to know the other
exists. What reaches the model is one history in time order, because that is
what it is: the things that happened to this service, whoever recorded them.
"""

A_SERVICE = "kukibuki-service"
DONT_CARE_FLAG = "kukibuki"

SOME_WINDOW_START = "2026-08-29T20:00:00Z"
SOME_WINDOW_END = "2026-08-29T22:15:00Z"


@pytest.mark.unit
def test_a_flag_toggle_is_offered_as_a_change() -> None:
    # The point of the whole channel: a toggle is a change to what the service
    # does, and the model cannot weigh it against a deploy unless it arrives as
    # one - with its own kind, so the two stay distinguishable, and naming the
    # flag, because something acts on that name afterwards.
    some_flag = "monthly-spend-feature"
    some_flag_was_switched_on = _a_flag_change(some_flag, enabled=True)

    Scenario() \
        .given(
            some_flag_was_switched_on
        ) \
        .when(
            lambda: _the_changes_read(flags=[some_flag_was_switched_on])
        ) \
        .then(
            all_of(
                _the_changes_were([ChangeKind.FLAG_TOGGLE]),
                _the_change_names(some_flag)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(("enabled", "direction"), [(True, "on"), (False, "off")])
def test_a_flag_switch_says_which_way_it_went(enabled: bool, direction: str) -> None:
    some_flag_was_switched = _a_flag_change(enabled=enabled)

    Scenario() \
        .given(
            some_flag_was_switched
        ) \
        .when(
            lambda: _the_changes_read(flags=[some_flag_was_switched])
        ) \
        .then(
            _the_change_says_it_was_switched(direction)
        )


@pytest.mark.unit
def test_a_deploy_is_still_offered_when_nothing_was_toggled() -> None:
    # The channel a second source is being added to, and the thing that
    # addition is most likely to break. Every other test here either supplies a
    # toggle or expects nothing back, so a merge that dropped the deploys - or
    # rebuilt them into something almost right - would pass all of them.
    some_minute_inside_the_window = "2026-08-29T20:20:00Z"
    some_deploy = _a_deploy_at(some_minute_inside_the_window)

    Scenario() \
        .given(
            some_deploy
        ) \
        .when(
            lambda: _the_changes_read(deploys=[some_deploy])
        ) \
        .then(
            _the_changes_returned_were([some_deploy])
        )


@pytest.mark.unit
def test_deploys_and_toggles_arrive_as_one_history_in_time_order() -> None:
    # One history, because that is what happened: the model is weighing which
    # of them accounts for the symptoms, and two lists would make it weigh them
    # against the order they were fetched in rather than the order they
    # occurred in.
    some_earlier_minute = "2026-08-29T20:10:00Z"
    some_later_minute = "2026-08-29T20:20:00Z"
    some_deploy_at_the_later_minute = _a_deploy_at(some_later_minute)
    some_toggle_at_the_earlier_minute = _a_flag_change(at=some_earlier_minute)

    Scenario() \
        .given(
            some_deploy_at_the_later_minute,
            some_toggle_at_the_earlier_minute
        ) \
        .when(
            lambda: _the_changes_read(
                deploys=[some_deploy_at_the_later_minute],
                flags=[some_toggle_at_the_earlier_minute]
            )
        ) \
        .then(
            _the_changes_were([ChangeKind.FLAG_TOGGLE, ChangeKind.DEPLOY])
        )


@pytest.mark.unit
def test_a_toggle_outside_the_window_is_not_offered() -> None:
    # The flag provider is asked what happened since a moment, never what
    # happened between two - so the far end of the window is this caller's to
    # apply. Without it, a toggle made after the incident began would be
    # offered as something that might have caused it.
    some_minute_after_the_window_closed = "2026-08-29T23:30:00Z"
    some_toggle_after_the_window_closed = _a_flag_change(at=some_minute_after_the_window_closed)

    Scenario() \
        .given(
            some_toggle_after_the_window_closed
        ) \
        .when(
            lambda: _the_changes_read(flags=[some_toggle_after_the_window_closed])
        ) \
        .then(
            _the_changes_were([])
        )


@pytest.mark.unit
def test_a_flag_history_that_cannot_be_read_is_a_failure_of_the_investigation() -> None:
    # The same rule the deploy source already follows, and for the same reason:
    # "nothing changed" is a conclusion something acts on, so a source that was
    # never read must not arrive looking like one that was read and found
    # empty. Silence here would let an outage become evidence of absence.
    some_provider_failure = RuntimeError("the flag provider could not be reached")

    Scenario() \
        .given(
            some_provider_failure
        ) \
        .when(
            lambda: _what_was_raised_reading_changes(some_provider_failure)
        ) \
        .then(
            _the_same_failure_reached_the_caller(some_provider_failure)
        )


@pytest.mark.unit
def test_the_flag_history_is_asked_about_the_window_it_was_given() -> None:
    # The provider takes a `since` and nothing else, so this is the only bound
    # it is told about - and getting it wrong is invisible in every other test
    # here, which asserts on what came back rather than on what was asked for.
    some_window_starting_at = SOME_WINDOW_START
    asked = create_autospec(get_recent_flag_changes, return_value=[])

    Scenario() \
        .given(
            some_window_starting_at
        ) \
        .when(
            lambda: _the_changes_read(reads_flags=asked, window_start=some_window_starting_at)
        ) \
        .then(
            _the_flag_history_was_asked_since(asked, some_window_starting_at)
        )


@pytest.mark.unit
def test_a_toggle_keeps_the_actor_the_provider_named() -> None:
    # Load-bearing rather than decorative: Argus writes under a credential of
    # its own, and the actor is what tells its own revert from a human's. A
    # toggle that arrives unattributed is one Argus can offer as a cause of the
    # incident it was taking action on.
    some_actor = "a-human"
    some_flag_a_human_switched = _a_flag_change(actor=some_actor)

    Scenario() \
        .given(
            some_flag_a_human_switched
        ) \
        .when(
            lambda: _the_changes_read(flags=[some_flag_a_human_switched])
        ) \
        .then(
            _the_change_is_attributed_to(some_actor)
        )


def _a_flag_change(flag: str = DONT_CARE_FLAG,
                   enabled: bool = True,
                   at: str = "2026-08-29T21:00:00Z",
                   actor: str | None = "a-human") -> FlagChange:
    return FlagChange(flag=flag, enabled=enabled, occurred_at=at, actor=actor)


def _a_deploy_at(occurred_at: str) -> ChangeEvent:
    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=occurred_at,
        reference="dont-care-revision",
        summary="dont care what was deployed"
    )


def _the_changes_read(deploys: list[ChangeEvent] | None = None,
                      flags: list[FlagChange] | None = None,
                      reads_flags: Mock | None = None,
                      window_start: str = SOME_WINDOW_START,
                      window_end: str = SOME_WINDOW_END) -> list[ChangeEvent]:
    """Both sources answering, over one window.

    Each defaults to nothing, so a test naming one source cannot pass because
    of the other. `reads_flags` is for the one test that asks what the flag
    source was asked, rather than what it answered.
    """
    return fetch_change_events(
        A_SERVICE,
        SOME_WINDOW_START,
        SOME_WINDOW_END,
        get_change_events=create_autospec(get_change_events, return_value=deploys or []),
        get_recent_flag_changes=reads_flags or create_autospec(
            get_recent_flag_changes, return_value=flags or []
        )
    )


def _the_flag_history_was_asked_since(asked: Mock, since: str) -> Assertion[object]:
    def assertion(_changes: object) -> bool:
        asked.assert_called_once_with(since)

        return True

    return assertion


def _the_change_is_attributed_to(actor: str) -> Assertion[list[ChangeEvent]]:
    def assertion(changes: list[ChangeEvent]) -> bool:
        attributed = [change.actor for change in changes]

        if attributed != [actor]:
            raise AssertionError(f"Expected the change attributed to [{actor}], got {attributed}.")

        return True

    return assertion


def _what_was_raised_reading_changes(failure: Exception) -> Exception | None:
    """Runs the read and hands back whatever came out of it.

    Returned rather than allowed to escape, so the assertion can say which
    failure arrived rather than merely that one did.
    """
    try:
        fetch_change_events(
            A_SERVICE,
            SOME_WINDOW_START,
            SOME_WINDOW_END,
            get_change_events=create_autospec(get_change_events, return_value=[]),
            get_recent_flag_changes=create_autospec(
                get_recent_flag_changes, side_effect=failure
            )
        )
    except Exception as error:
        return error

    return None


def _the_changes_were(kinds: list[ChangeKind]) -> Assertion[list[ChangeEvent]]:
    """What came back, by kind and in order - which is the whole shape of the
    answer this channel gives."""
    def assertion(changes: list[ChangeEvent]) -> bool:
        actual = [change.kind for change in changes]

        if actual != kinds:
            raise AssertionError(f"Expected changes {kinds}, got {actual}.")

        return True

    return assertion


def _the_changes_returned_were(changes: list[ChangeEvent]) -> Assertion[list[ChangeEvent]]:
    """What came back, whole - not merely what kind of thing it was.

    A deploy passes through this channel untouched, so the strongest statement
    available is that it is the same change: a merge that carried the kind and
    lost the revision would satisfy every other assertion here.
    """
    def assertion(returned: list[ChangeEvent]) -> bool:
        if returned != changes:
            raise AssertionError(f"Expected {changes!r} back, got {returned!r}.")

        return True

    return assertion


def _the_change_names(reference: str) -> Assertion[list[ChangeEvent]]:
    """The flag's own name, verbatim: something acts on it afterwards, and a
    name that is not the provider's identifies nothing."""
    def assertion(changes: list[ChangeEvent]) -> bool:
        named = [change.reference for change in changes]

        if named != [reference]:
            raise AssertionError(f"Expected the change to name [{reference}], got {named}.")

        return True

    return assertion


def _the_change_says_it_was_switched(direction: str) -> Assertion[list[ChangeEvent]]:
    def assertion(changes: list[ChangeEvent]) -> bool:
        said = changes[0].summary

        if direction not in said.split():
            raise AssertionError(f"Expected the summary to say [{direction}], got [{said}].")

        return True

    return assertion


def _the_same_failure_reached_the_caller(
    failure: Exception
) -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if raised is not failure:
            raise AssertionError(f"Expected [{failure!r}] to reach the caller, got [{raised!r}].")

        return True

    return assertion
