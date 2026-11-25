"""The feature-flag provider's port, as every adapter of it answers.

What the port promises, asked of each adapter over one seed: the Unleash
adapters against an in-process Unleash (`framework.unleash_world`), and the
in-memory double (`flag_provider_double`). A promise one of them keeps and the
other does not fails here, so the double cannot drift from the port, and the
port names nothing only Unleash's wire could answer.

The promises and nothing beyond them. Nothing of the port lands after its
answer - a write returns only once evaluation agrees with it - so every effect
is read straight after the call that made it. How each answer travels is
`test_unleash.py`'s.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Protocol

import httpx2
import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    dont_care_sleep,
    the_answer_was,
)
from core import to_iso
from core.models import FlagChange, FlagState, FlagUndo
from flag_provider import (
    FlagProviderReads,
    FlagProviderUnavailable,
    FlagProviderWrites,
    FlagWriteFailed,
)
from flag_provider.unleash import Unleash, UnleashFrontend
from flag_provider_double import InMemoryFlagProvider, ProviderState, RecordedToggle

from flag_provider_test.framework import (
    UnleashWorld,
    unleash_frontend_settings,
    unleash_settings,
)

SOME_ENVIRONMENT = "production"

SOME_FLAG = "monthly-spend-feature"
SOME_OTHER_FLAG = "recommendations-v2"
A_FLAG_THAT_IS_OFF = "kuki-checkout"
NO_SUCH_FLAG = "buki-flag"

# The name Argus is configured to recognise as its own, and the one the
# provider records Argus's writes under - the same name, spelled in another
# case, which is the drift telling them apart exists to survive.
THE_NAME_ARGUS_WRITES_UNDER = "Argus"
AS_THE_PROVIDER_RECORDS_IT = "argus"
SOMEBODY_ELSE = "buki"

# The provider's clock, read to the millisecond as its log records a change -
# so that a moment said to the second is seen to be cut there - and that
# moment, cut.
SOME_MOMENT = datetime(2026, 11, 25, 9, 30, 15, 417000, tzinfo=UTC)
THE_MOMENT_TO_THE_SECOND = SOME_MOMENT.replace(microsecond=0)

# The moment the history is asked from, between two seconds, and moments
# around it - every one before the provider's clock.
SINCE = datetime(2026, 11, 25, 9, 0, 12, 250000, tzinfo=UTC)
JUST_BEFORE_SINCE = SINCE - timedelta(milliseconds=1)
INSIDE_THE_WINDOW = SINCE + timedelta(minutes=4, seconds=38, milliseconds=33)
LATER_IN_THE_WINDOW = SINCE + timedelta(minutes=9, seconds=12, milliseconds=581)


def _a_toggle(flag: str,
              enabled: bool,
              *,
              at: datetime,
              actor: str = SOMEBODY_ELSE) -> RecordedToggle:
    """One change the provider recorded - here rather than among the helpers
    below, since the cases' parameters are built from it."""
    return RecordedToggle(flag=flag, enabled=enabled, occurred_at=at, actor=actor)


class _StandsUp(Protocol):
    def __call__(self,
                 state: ProviderState,
                 *,
                 argus_actor: str | None = ...,
                 clock: Callable[[], datetime] = ...,
                 unreachable: bool = ...) -> FlagProviderWrites:
        ...


class _StandsUpReads(Protocol):
    def __call__(self,
                 state: ProviderState,
                 *,
                 argus_actor: str | None = ...,
                 clock: Callable[[], datetime] = ...,
                 unreachable: bool = ...) -> FlagProviderReads:
        ...


def _in_memory(state: ProviderState,
               *,
               argus_actor: str | None = THE_NAME_ARGUS_WRITES_UNDER,
               clock: Callable[[], datetime] = lambda: SOME_MOMENT,
               unreachable: bool = False) -> FlagProviderWrites:
    return InMemoryFlagProvider(state, argus_actor=argus_actor, clock=clock,
                                unreachable=unreachable)


def _unleash(state: ProviderState,
             *,
             argus_actor: str | None = THE_NAME_ARGUS_WRITES_UNDER,
             clock: Callable[[], datetime] = lambda: SOME_MOMENT,
             unreachable: bool = False) -> FlagProviderWrites:
    world = UnleashWorld(state, clock=clock, unreachable=unreachable)

    return Unleash(unleash_settings(state, argus_actor), transport=httpx2.MockTransport(world),
                   sleep=dont_care_sleep)


def _unleash_frontend(state: ProviderState,
                      *,
                      argus_actor: str | None = THE_NAME_ARGUS_WRITES_UNDER,
                      clock: Callable[[], datetime] = lambda: SOME_MOMENT,
                      unreachable: bool = False) -> FlagProviderReads:
    """The read tier's adapter, which knows no name of Argus's to recognise."""
    world = UnleashWorld(state, clock=clock, unreachable=unreachable)

    return UnleashFrontend(unleash_frontend_settings(), transport=httpx2.MockTransport(world))


EVERY_ADAPTER = pytest.mark.parametrize("stand_up", [
    pytest.param(_in_memory, id="in-memory"),
    pytest.param(_unleash, id="unleash")
])

EVERY_READS_ADAPTER = pytest.mark.parametrize("stand_up", [
    pytest.param(_in_memory, id="in-memory"),
    pytest.param(_unleash, id="unleash"),
    pytest.param(_unleash_frontend, id="unleash-frontend")
])

# Both directions a flag is set in, each from the state it is not in.
EVERY_DIRECTION = pytest.mark.parametrize("enabled", [
    pytest.param(True, id="on"),
    pytest.param(False, id="off")
])


@pytest.mark.unit
@EVERY_READS_ADAPTER
def test_the_flags_on_are_those_evaluating_true_in_the_order_the_provider_lists_them(
    stand_up: _StandsUpReads
) -> None:
    # Not alphabetical, so an adapter that sorted would be caught; one flag
    # off between them, so one that read every flag as on would be.
    Scenario() \
        .given(provider := stand_up(_a_provider_holding(
            (SOME_OTHER_FLAG, True), (A_FLAG_THAT_IS_OFF, False), (SOME_FLAG, True)
        ))) \
        .when(lambda: provider.enabled()) \
        .then(the_answer_was([SOME_OTHER_FLAG, SOME_FLAG]))


@pytest.mark.unit
@EVERY_READS_ADAPTER
def test_a_provider_nothing_reaches_is_unavailable_rather_than_nothing_on(
    stand_up: _StandsUpReads
) -> None:
    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, True)), unreachable=True)) \
        .when(attempting(lambda: provider.enabled())) \
        .then(an_error_was_raised(FlagProviderUnavailable))


@pytest.mark.unit
@EVERY_ADAPTER
@EVERY_DIRECTION
def test_a_flags_state_is_what_the_provider_holds_dated_by_its_own_clock_to_the_second(
    stand_up: _StandsUp, enabled: bool
) -> None:
    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, enabled)))) \
        .when(lambda: provider.state_of(SOME_FLAG)) \
        .then(the_answer_was(FlagState(enabled=enabled, read_at=THE_MOMENT_TO_THE_SECOND)))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("flag", "unreachable"), [
    pytest.param(NO_SUCH_FLAG, False, id="a flag not held"),
    pytest.param(SOME_FLAG, True, id="a provider nothing reaches")
])
def test_a_flags_state_the_provider_cannot_give_is_unavailable(
    stand_up: _StandsUp, flag: str, unreachable: bool
) -> None:
    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, True)),
                                    unreachable=unreachable)) \
        .when(attempting(lambda: provider.state_of(flag))) \
        .then(an_error_was_raised(FlagProviderUnavailable))


@pytest.mark.unit
@EVERY_ADAPTER
@EVERY_DIRECTION
def test_a_set_answers_with_what_restores_the_flag_and_both_reads_then_agree_with_it(
    stand_up: _StandsUp, enabled: bool
) -> None:
    def set_then_read() -> tuple[FlagUndo, bool, bool]:
        undo = provider.set(SOME_FLAG, enabled)

        return (undo, SOME_FLAG in provider.enabled(), provider.state_of(SOME_FLAG).enabled)

    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, not enabled)))) \
        .when(set_then_read) \
        .then(the_answer_was((
            FlagUndo(flag=SOME_FLAG, was_enabled=not enabled, environment=SOME_ENVIRONMENT,
                     written_at=THE_MOMENT_TO_THE_SECOND),
            enabled,
            enabled
        )))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("flag", "unreachable"), [
    pytest.param(NO_SUCH_FLAG, False, id="a flag not held"),
    pytest.param(SOME_FLAG, True, id="a provider nothing reaches")
])
def test_a_set_the_provider_never_took_is_known_not_applied_and_left_nothing(
    stand_up: _StandsUp, flag: str, unreachable: bool
) -> None:
    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, True)),
                                    unreachable=unreachable)) \
        .when(attempting(lambda: provider.set(flag, False))) \
        .then(_it_failed_the_write(known_not_applied=True, left_behind=None))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_set_taken_and_never_evaluated_carries_what_puts_it_back(
    stand_up: _StandsUp
) -> None:
    # The provider holds the new state, and evaluation still says the old one.
    def set_then_read() -> tuple[Exception | None, bool, list[str]]:
        failure = attempting(lambda: provider.set(SOME_FLAG, False))()

        return (failure, provider.state_of(SOME_FLAG).enabled, provider.enabled())

    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, True),
                                                        evaluation_follows=False))) \
        .when(set_then_read) \
        .then(all_of(
            lambda read: _it_failed_the_write(known_not_applied=False, left_behind=FlagUndo(
                flag=SOME_FLAG, was_enabled=True, environment=SOME_ENVIRONMENT,
                written_at=THE_MOMENT_TO_THE_SECOND
            ))(read[0]),
            lambda read: the_answer_was((False, [SOME_FLAG]))(read[1:])
        ))


@pytest.mark.unit
@EVERY_ADAPTER
def test_the_changes_since_a_moment_are_those_at_or_after_it_oldest_first(
    stand_up: _StandsUp
) -> None:
    # One a millisecond before the moment asked from, left out; one at it to the
    # millisecond, kept. Recorded oldest first, read oldest first.
    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, True), history=(
            _a_toggle(SOME_FLAG, True, at=JUST_BEFORE_SINCE),
            _a_toggle(SOME_FLAG, False, at=SINCE),
            _a_toggle(SOME_FLAG, True, at=INSIDE_THE_WINDOW)
        )))) \
        .when(lambda: provider.changes_since(SINCE)) \
        .then(the_answer_was([
            _as_said(_a_toggle(SOME_FLAG, False, at=SINCE), made_by_argus=False),
            _as_said(_a_toggle(SOME_FLAG, True, at=INSIDE_THE_WINDOW), made_by_argus=False)
        ]))


@pytest.mark.unit
@EVERY_ADAPTER
def test_two_changes_at_one_moment_keep_the_order_they_were_recorded_in(
    stand_up: _StandsUp
) -> None:
    # Switched on and straight back off, which is the order that says the flag
    # ended off.
    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, False), history=(
            _a_toggle(SOME_FLAG, True, at=INSIDE_THE_WINDOW),
            _a_toggle(SOME_FLAG, False, at=INSIDE_THE_WINDOW)
        )))) \
        .when(lambda: [(change.flag, change.enabled)
                       for change in provider.changes_since(SINCE)]) \
        .then(the_answer_was([(SOME_FLAG, True), (SOME_FLAG, False)]))


@pytest.mark.unit
@EVERY_ADAPTER
def test_argus_s_own_set_is_among_the_changes_after_it_as_argus_s(stand_up: _StandsUp) -> None:
    # Recorded under the name the provider knows Argus's credential by, spelled
    # as the provider spells it - which is still told as Argus's.
    def set_then_read() -> list[FlagChange]:
        provider.set(SOME_FLAG, False)

        return provider.changes_since(SINCE)

    Scenario() \
        .given(provider := stand_up(_a_provider_holding(
            (SOME_FLAG, True),
            history=(_a_toggle(SOME_FLAG, True, at=INSIDE_THE_WINDOW),),
            signed_in_as=AS_THE_PROVIDER_RECORDS_IT
        ))) \
        .when(set_then_read) \
        .then(the_answer_was([
            _as_said(_a_toggle(SOME_FLAG, True, at=INSIDE_THE_WINDOW), made_by_argus=False),
            FlagChange(flag=SOME_FLAG, enabled=False, occurred_at=to_iso(SOME_MOMENT),
                       actor=AS_THE_PROVIDER_RECORDS_IT, made_by_argus=True)
        ]))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_set_to_the_state_the_flag_holds_records_no_change(stand_up: _StandsUp) -> None:
    def set_then_read() -> list[FlagChange]:
        provider.set(SOME_FLAG, True)

        return provider.changes_since(SINCE)

    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, True)))) \
        .when(set_then_read) \
        .then(the_answer_was([]))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("configured", "recorded", "made_by_argus"), [
    pytest.param(THE_NAME_ARGUS_WRITES_UNDER, THE_NAME_ARGUS_WRITES_UNDER, True,
                 id="argus-s-own"),
    pytest.param(THE_NAME_ARGUS_WRITES_UNDER, AS_THE_PROVIDER_RECORDS_IT, True,
                 id="in-another-case"),
    pytest.param(THE_NAME_ARGUS_WRITES_UNDER, SOMEBODY_ELSE, False, id="somebody-else-s"),
    pytest.param(None, THE_NAME_ARGUS_WRITES_UNDER, None, id="no-name-configured")
])
def test_whose_a_change_is_is_told_by_the_name_the_provider_recorded_it_under(
    stand_up: _StandsUp, configured: str | None, recorded: str, made_by_argus: bool | None
) -> None:
    Scenario() \
        .given(provider := stand_up(_a_provider_holding(
            (SOME_FLAG, True), history=(_a_toggle(SOME_FLAG, True, at=INSIDE_THE_WINDOW,
                                                  actor=recorded),)
        ), argus_actor=configured)) \
        .when(lambda: provider.changes_since(SINCE)[0].made_by_argus) \
        .then(the_answer_was(made_by_argus))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("history", "others_changed"), [
    pytest.param((_a_toggle(SOME_FLAG, False, at=INSIDE_THE_WINDOW,
                            actor=THE_NAME_ARGUS_WRITES_UNDER),
                  _a_toggle(SOME_FLAG, True, at=LATER_IN_THE_WINDOW,
                            actor=THE_NAME_ARGUS_WRITES_UNDER)),
                 False, id="only argus changed it"),
    pytest.param((_a_toggle(SOME_FLAG, False, at=INSIDE_THE_WINDOW,
                            actor=THE_NAME_ARGUS_WRITES_UNDER),
                  _a_toggle(SOME_FLAG, True, at=LATER_IN_THE_WINDOW, actor=SOMEBODY_ELSE)),
                 True, id="somebody else changed it later"),
    pytest.param((_a_toggle(SOME_OTHER_FLAG, True, at=INSIDE_THE_WINDOW,
                            actor=SOMEBODY_ELSE),),
                 False, id="somebody else changed another flag")
])
def test_whether_anybody_else_changed_a_flag_is_read_off_whose_each_change_was(
    stand_up: _StandsUp, history: tuple[RecordedToggle, ...], others_changed: bool
) -> None:
    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, True),
                                                        (SOME_OTHER_FLAG, False),
                                                        history=history))) \
        .when(lambda: provider.others_changed_since(SOME_FLAG, SINCE)) \
        .then(_it_answered(others_changed))


@pytest.mark.unit
@EVERY_ADAPTER
@pytest.mark.parametrize(("argus_actor", "unreachable"), [
    pytest.param(None, False, id="no name configured"),
    pytest.param(THE_NAME_ARGUS_WRITES_UNDER, True, id="a provider nothing reaches")
])
def test_whether_anybody_else_changed_a_flag_is_not_answered_where_nobody_can_say(
    stand_up: _StandsUp, argus_actor: str | None, unreachable: bool
) -> None:
    # Somebody else's change in the window, so an adapter that answered at all
    # would answer `True`.
    Scenario() \
        .given(provider := stand_up(_a_provider_holding(
            (SOME_FLAG, True),
            history=(_a_toggle(SOME_FLAG, True, at=INSIDE_THE_WINDOW, actor=SOMEBODY_ELSE),)
        ), argus_actor=argus_actor, unreachable=unreachable)) \
        .when(lambda: provider.others_changed_since(SOME_FLAG, SINCE)) \
        .then(_it_answered(None))


@pytest.mark.unit
@EVERY_ADAPTER
def test_the_changes_from_a_provider_nothing_reaches_are_unavailable_rather_than_none(
    stand_up: _StandsUp
) -> None:
    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, True)), unreachable=True)) \
        .when(attempting(lambda: provider.changes_since(SINCE))) \
        .then(an_error_was_raised(FlagProviderUnavailable))


@pytest.mark.unit
@EVERY_ADAPTER
def test_a_person_s_change_followed_by_a_hundred_others_still_counts(
    stand_up: _StandsUp
) -> None:
    # Somebody's change, and then as many of Argus's as the newest a capped log
    # answers with - so a read of the newest alone would see Argus's changes and
    # nothing else, and answer that nobody else changed the flag.
    as_many_as_a_capped_log_answers = 100
    somebodys = _a_toggle(SOME_FLAG, False, at=INSIDE_THE_WINDOW, actor=SOMEBODY_ELSE)
    argus_s = tuple(
        _a_toggle(SOME_FLAG, count % 2 == 1, at=INSIDE_THE_WINDOW + timedelta(seconds=count),
                  actor=THE_NAME_ARGUS_WRITES_UNDER)
        for count in range(1, as_many_as_a_capped_log_answers + 1)
    )

    Scenario() \
        .given(provider := stand_up(_a_provider_holding((SOME_FLAG, False),
                                                        history=(somebodys, *argus_s)))) \
        .when(lambda: (provider.others_changed_since(SOME_FLAG, SINCE),
                       provider.changes_since(SINCE)[0])) \
        .then(the_answer_was((True, _as_said(somebodys, made_by_argus=False))))


def _a_provider_holding(*flags: tuple[str, bool],
                        history: tuple[RecordedToggle, ...] = (),
                        signed_in_as: str = THE_NAME_ARGUS_WRITES_UNDER,
                        evaluation_follows: bool = True) -> ProviderState:
    return ProviderState(environment=SOME_ENVIRONMENT, flags=flags, history=history,
                         signed_in_as=signed_in_as, evaluation_follows=evaluation_follows)


def _as_said(toggle: RecordedToggle, *, made_by_argus: bool | None) -> FlagChange:
    """`toggle` as the port says a change, told as `made_by_argus` says."""
    return FlagChange(flag=toggle.flag, enabled=toggle.enabled,
                      occurred_at=to_iso(toggle.occurred_at), actor=toggle.actor,
                      made_by_argus=made_by_argus)


def _it_answered(expected: bool | None) -> Assertion[bool | None]:
    """`is` rather than `==`: `None` and `False` are the whole distinction here."""
    def assertion(answer: bool | None) -> bool:
        if answer is not expected:
            raise AssertionError(f"Expected the answer [{expected}], got [{answer}].")

        return True

    return assertion


def _it_failed_the_write(known_not_applied: bool,
                         left_behind: FlagUndo | None) -> Assertion[Exception | None]:
    """The write's failure, and both things it says of the flag, every wrong
    one reported together."""
    def assertion(error: Exception | None) -> bool:
        if not isinstance(error, FlagWriteFailed):
            raise AssertionError(
                f"Expected the write to fail as FlagWriteFailed, got [{error!r}]."
            )

        said = (error.known_not_applied, error.left_behind)

        if said != (known_not_applied, left_behind):
            raise AssertionError(
                f"Expected the failure to say known not applied [{known_not_applied}] and "
                f"left behind [{left_behind}], got [{said[0]}] and [{said[1]}]: [{error}]."
            )

        return True

    return assertion
