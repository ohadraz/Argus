from __future__ import annotations

import pytest
from argus_core.models.flag_change import FlagChange
from argus_testkit import Assertion, Scenario, all_of
from argus_web.views.flags import FlagToggleRow, a_flag_history, on_or_off, said_as_a_state

"""The flag provider's recorded changes, each said as the move it was.

A row shows a transition rather than describing one, because that is what the
page can strike through: the state the flag left beside the state it arrived
in. The state it left is never read from anywhere - the provider writes a
record when a flag's state *changes*, so a flag that arrived ON is a flag that
was OFF, and that is the meaning of the record rather than an assumption about
production.

Which flag and which moment are arbitrary throughout. What is not arbitrary is
which way a change went and which of a flag's changes is its newest, because an
action points at the newest one and a link to an older move would show a reader
the wrong reason for what Argus did.
"""

SOME_MOMENT = "2026-08-30T10:05:00Z"
A_LATER_MOMENT = "2026-08-30T10:25:00Z"


@pytest.mark.unit
def test_a_flag_that_arrived_on_is_shown_as_having_been_off() -> None:
    # Not an assumption about production but the meaning of the record: the
    # provider writes one of these when a state changes, so the state before is
    # the other one.
    some_change_that_switched_a_flag_on = _a_change(enabled=True)

    Scenario() \
        .given(some_change_that_switched_a_flag_on) \
        .when(lambda: a_flag_history([some_change_that_switched_a_flag_on])) \
        .then(_the_only_row_moved(was=on_or_off(False), now=on_or_off(True)))


@pytest.mark.unit
def test_a_flag_that_arrived_off_is_shown_as_having_been_on() -> None:
    # The other direction, said the same way. Which direction is the bad one
    # depends entirely on the flag, so neither is coloured and both are shown.
    some_change_that_switched_a_flag_off = _a_change(enabled=False)

    Scenario() \
        .given(some_change_that_switched_a_flag_off) \
        .when(lambda: a_flag_history([some_change_that_switched_a_flag_off])) \
        .then(_the_only_row_moved(was=on_or_off(True), now=on_or_off(False)))


@pytest.mark.unit
def test_a_change_is_shown_with_the_flag_and_the_actor_it_was_recorded_against() -> None:
    # Who moved it is the difference between an operator's ramp and Argus's own
    # mitigation, and the page cannot tell them apart any other way.
    some_flag = "some-ramped-flag"
    some_actor = "a-human"
    some_change = _a_change(enabled=True, flag=some_flag, actor=some_actor)

    Scenario() \
        .given(some_change) \
        .when(lambda: a_flag_history([some_change])) \
        .then(all_of(_the_only_row_is_about(some_flag), _the_only_row_credits(some_actor)))


@pytest.mark.unit
def test_a_change_nobody_was_recorded_for_credits_nobody() -> None:
    # The provider does not always say who. Left empty rather than filled in
    # with a guess, because "Argus" is exactly the wrong guess to make here.
    some_change_nobody_was_recorded_for = _a_change(enabled=True, actor=None)

    Scenario() \
        .given(some_change_nobody_was_recorded_for) \
        .when(lambda: a_flag_history([some_change_nobody_was_recorded_for])) \
        .then(_the_only_row_credits(None))


@pytest.mark.unit
def test_the_newest_change_to_a_flag_is_the_one_marked_as_its_latest() -> None:
    # The row an action points at: the change Mitigation chose to undo is by
    # definition the latest one. The history arrives in the order it happened,
    # so the newest is the last of them.
    some_flag = "some-ramped-flag"
    an_earlier_change = _a_change(enabled=True, flag=some_flag, occurred_at=SOME_MOMENT)
    the_newest_change = _a_change(enabled=False, flag=some_flag, occurred_at=A_LATER_MOMENT)

    Scenario() \
        .given(a_flag_moved_twice := [an_earlier_change, the_newest_change]) \
        .when(lambda: a_flag_history(a_flag_moved_twice)) \
        .then(_the_rows_marked_latest_are([False, True]))


@pytest.mark.unit
def test_every_flag_has_a_latest_of_its_own() -> None:
    # Marked per flag rather than per history: an action on one flag points at
    # that flag's newest change, and a single mark across the whole table would
    # leave every other flag pointing nowhere.
    some_flag = "some-ramped-flag"
    another_flag = "another-flag"
    the_newest_change_to_one = _a_change(enabled=True, flag=some_flag)
    the_newest_change_to_the_other = _a_change(enabled=False, flag=another_flag)

    Scenario() \
        .given(
            two_flags_that_each_moved_once := [
                the_newest_change_to_one, the_newest_change_to_the_other
            ]
        ) \
        .when(lambda: a_flag_history(two_flags_that_each_moved_once)) \
        .then(_the_rows_marked_latest_are([True, True]))


@pytest.mark.unit
def test_a_history_nobody_recorded_anything_in_is_empty() -> None:
    # The flag provider answering with nothing is a finding of its own - it is
    # what rules a toggle out - and it arrives here as an empty history rather
    # than as an absence.
    nothing_was_recorded: list[FlagChange] = []

    Scenario() \
        .given(nothing_was_recorded) \
        .when(lambda: a_flag_history(nothing_was_recorded)) \
        .then(_there_are_no_rows())


@pytest.mark.unit
def test_a_flag_position_the_model_wrote_is_said_the_way_the_table_says_it() -> None:
    # The page has one spelling for a flag's position, and the model writes
    # another. Mapped here, on a field, rather than by re-casing the word
    # wherever it appears in a sentence - which cannot tell a state from prose
    # that merely uses the word "off".
    Scenario() \
        .given(some_state_as_the_model_wrote_it := "off") \
        .when(lambda: said_as_a_state(some_state_as_the_model_wrote_it)) \
        .then(_it_reads("OFF"))


@pytest.mark.unit
def test_a_state_that_is_not_a_flag_position_is_left_exactly_as_it_came() -> None:
    # A deployment moves between versions, and `V2.3.1` is not a version. Only
    # the two words this page has a house style for are touched; everything
    # else is the evidence's own and is shown as the evidence wrote it.
    Scenario() \
        .given(some_version_a_deployment_moved_from := "v2.3.1") \
        .when(lambda: said_as_a_state(some_version_a_deployment_moved_from)) \
        .then(_it_reads("v2.3.1"))


@pytest.mark.unit
def test_a_cause_that_moved_between_no_states_says_nothing() -> None:
    # Not every cause is a transition. Empty rather than a word standing in for
    # one, because the template shows the move only where there is one.
    Scenario() \
        .given(nothing_was_stated := None) \
        .when(lambda: said_as_a_state(nothing_was_stated)) \
        .then(_it_reads(""))


def _a_change(enabled: bool,
              flag: str = "some-ramped-flag",
              occurred_at: str = SOME_MOMENT,
              actor: str | None = "a-human") -> FlagChange:
    """One recorded move of one flag.

    `enabled` has no default because it is the only field any of these turns
    on: it is the state the flag arrived in, and the state it left is read back
    out of it.
    """
    return FlagChange(flag=flag, enabled=enabled, occurred_at=occurred_at, actor=actor)


def _the_only_row_moved(was: str, now: str) -> Assertion[list[FlagToggleRow]]:
    def assertion(history: list[FlagToggleRow]) -> bool:
        row = _the_only(history)

        if (row.was, row.now) != (was, now):
            raise AssertionError(
                f"expected a move from [{was}] to [{now}], "
                f"got [{row.was}] to [{row.now}]"
            )

        return True

    return assertion


def _the_only_row_is_about(expected: str) -> Assertion[list[FlagToggleRow]]:
    def assertion(history: list[FlagToggleRow]) -> bool:
        row = _the_only(history)

        if row.flag != expected:
            raise AssertionError(f"expected a row about [{expected}], got [{row.flag}]")

        return True

    return assertion


def _the_only_row_credits(expected: str | None) -> Assertion[list[FlagToggleRow]]:
    def assertion(history: list[FlagToggleRow]) -> bool:
        row = _the_only(history)

        if row.actor != expected:
            raise AssertionError(f"expected [{expected}] credited, got [{row.actor}]")

        return True

    return assertion


def _the_rows_marked_latest_are(expected: list[bool]) -> Assertion[list[FlagToggleRow]]:
    """Which rows carry the mark, asserted as the whole list.

    A row marked that should not be is as wrong as one that should be and is
    not - it is the row an action links to - and naming only what is expected
    cannot see the first kind.
    """
    def assertion(history: list[FlagToggleRow]) -> bool:
        marked = [row.latest_for_flag for row in history]

        if marked != expected:
            raise AssertionError(f"expected {expected} marked latest, got {marked}")

        return True

    return assertion


def _there_are_no_rows() -> Assertion[list[FlagToggleRow]]:
    def assertion(history: list[FlagToggleRow]) -> bool:
        if history:
            raise AssertionError(f"expected no rows, got {len(history)}")

        return True

    return assertion


def _the_only(history: list[FlagToggleRow]) -> FlagToggleRow:
    """The single row a one-change history becomes.

    Asserted here rather than by indexing inline, so a history that shaped into
    two rows fails saying so instead of quietly passing on its first.
    """
    if len(history) != 1:
        raise AssertionError(f"expected one row, got {len(history)}")

    return history[0]


def _it_reads(expected: str) -> Assertion[str]:
    def assertion(said: str) -> bool:
        if said != expected:
            raise AssertionError(f"expected [{expected}], got [{said}]")

        return True

    return assertion
