from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation import Outcome, UndoAttempt, Undone, Verdict, take_action, undo_change
from agent_mitigation.tools import fetch_recent_metrics, set_flag
from argus_core.events import AwaitingRecovery, IncidentEvent, RecoveryChecked
from argus_core.ids import new_id
from argus_core.models.metrics import MetricBucket
from argus_testkit import Assertion, Scenario, all_of

from agent_mitigation_test.framework.assertions import the_verdict_is
from agent_mitigation_test.framework.builders import (
    ACTION_TIME,
    DONT_CARE_FLAG,
    a_clock_frozen_at,
    a_clock_that_runs_out_after_one_look,
    a_recovered_window,
    a_still_failing_window,
    a_window_ending_at_the_action,
    an_action_setting,
    an_undo_descriptor_for,
    dont_care_sleep,
    metrics_reading,
    nobody_can_say,
    nobody_changed_it,
    nobody_wants_it_any_more,
    somebody_changed_it,
)

_SOME_INCIDENT_ID = new_id()
# ACTION_TIME falls at 11:10:30, so the first minute that wholly follows it is
# 11:11 - the earliest one a verdict may be read off.
_THE_FIRST_WHOLE_MINUTE_AFTER = "2026-08-20T11:11:00Z"


@pytest.mark.unit
def test_taking_an_action_sets_the_flag_to_the_state_it_names() -> None:
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            some_old_state := False,
            set_state := _a_flag_setter_changing_from(some_flag, was_enabled=some_old_state)
        ) \
        .when(
            lambda: take_action(
                an_action_setting(some_flag, enabled=(not some_old_state)),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep
            )
        ) \
        .then(
            _the_flag_was_set_to(set_state, some_flag, enabled=(not some_old_state))
        )


@pytest.mark.unit
def test_a_service_that_returns_to_baseline_confirms_the_hypothesis() -> None:
    Scenario() \
        .given(
            some_old_state := False,
            the_service_recovers := a_recovered_window()
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                set_state=_a_flag_setter_changing_from(
                    DONT_CARE_FLAG, was_enabled=some_old_state),
                fetch_metrics=metrics_reading(the_service_recovers),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep
            )
        ) \
        .then(
            the_verdict_is(Verdict.CONFIRMED)
        )


@pytest.mark.unit
def test_a_service_still_departing_when_the_time_allowed_runs_out_is_refuted() -> None:
    # An expired verification is refuted rather than an error: the action was
    # taken and did not visibly help within the time allowed, which is exactly
    # what refuted means.
    Scenario() \
        .given(
            some_old_state := False,
            the_service_never_recovers := a_still_failing_window()
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                set_state=_a_flag_setter_changing_from(
                    DONT_CARE_FLAG, was_enabled=some_old_state),
                fetch_metrics=metrics_reading(the_service_never_recovers),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                changed_from_outside=nobody_changed_it()
            )
        ) \
        .then(
            the_verdict_is(Verdict.REFUTED)
        )


@pytest.mark.unit
def test_an_action_withdrawn_mid_wait_reaches_no_verdict() -> None:
    # Withdrawn is not refuted. The action was taken and then abandoned, so
    # nothing was measured about it - and calling that "refuted" would record
    # evidence against a hypothesis that was never tested.
    Scenario() \
        .given(
            some_old_state := False,
            nobody_still_wants_it := nobody_wants_it_any_more()
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                set_state=_a_flag_setter_changing_from(
                    DONT_CARE_FLAG, was_enabled=some_old_state),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                still_wanted=nobody_still_wants_it
            )
        ) \
        .then(
            the_verdict_is(Verdict.WITHDRAWN)
        )


@pytest.mark.unit
def test_a_withdrawn_wait_ends_at_its_next_look_rather_than_at_the_deadline() -> None:
    # The window is minutes long and this loop wakes every ten seconds anyway,
    # so the check costs nothing and the wait ends within one interval of the
    # withdrawal instead of at the end of a window nobody is waiting for.
    Scenario() \
        .given(
            some_old_state := False,
            fetch_metrics := _metrics_that_never_recover()
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                set_state=_a_flag_setter_changing_from(
                    DONT_CARE_FLAG, was_enabled=some_old_state),
                fetch_metrics=fetch_metrics,
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                still_wanted=nobody_wants_it_any_more()
            )
        ) \
        .then(
            _the_service_was_looked_at(fetch_metrics, times=1)
        )


@pytest.mark.unit
def test_a_withdrawn_action_is_left_where_it_is_carrying_its_undo() -> None:
    # Not undone here. Putting it back is the withdrawal's own job, done once
    # for every action the incident took and only where the flag still holds
    # what Argus wrote - a second undo in this function would be a second
    # opinion about that.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            some_old_state := False,
            set_state := _a_flag_setter_changing_from(some_flag, was_enabled=some_old_state)
        ) \
        .when(
            lambda: take_action(
                an_action_setting(some_flag, enabled=(not some_old_state)),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                still_wanted=nobody_wants_it_any_more()
            )
        ) \
        .then(all_of(
            _the_flag_was_set_to(set_state, some_flag, enabled=(not some_old_state)),
            _the_undo_carried_is(an_undo_descriptor_for(some_flag, was_enabled=some_old_state))
        ))


@pytest.mark.unit
def test_the_verdict_waits_for_a_minute_that_began_after_the_action() -> None:
    # The newest bucket covers the minute in progress, aggregated over the
    # seconds elapsed so far - mostly pre-action seconds. A verdict read off
    # that minute describes the incident, not the mitigation.
    Scenario() \
        .given(
            some_old_state := False,
            fetch_metrics := _metrics_recovering_only_after_the_action()
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                set_state=_a_flag_setter_changing_from(
                    DONT_CARE_FLAG, was_enabled=some_old_state),
                fetch_metrics=fetch_metrics,
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep
            )
        ) \
        .then(all_of(
            _the_service_was_looked_at(fetch_metrics, times=2),
            the_verdict_is(Verdict.CONFIRMED)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("some_old_state", [False, True])
def test_a_refuted_action_is_undone_in_whichever_direction_it_went(
        some_old_state: bool) -> None:
    # The flag was not the cause, so leaving it changed means production state
    # was altered for nothing and the next person to look finds an environment
    # Argus quietly changed. Undoing a switch-off means switching it back off.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            some_old_state,
            set_state := _a_flag_setter_changing_from(some_flag, was_enabled=some_old_state)
        ) \
        .when(
            lambda: take_action(
                an_action_setting(some_flag, enabled=(not some_old_state)),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                changed_from_outside=nobody_changed_it()
            )
        ) \
        .then(
            _the_flag_was_set_to(set_state, some_flag, enabled=some_old_state)
        )


@pytest.mark.unit
def test_a_confirmed_action_is_left_in_place() -> None:
    Scenario() \
        .given(
            some_old_state := False,
            set_state := _a_flag_setter_changing_from(
                DONT_CARE_FLAG, was_enabled=some_old_state)
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_flag_was_written_to(set_state, times=1)
        ))


@pytest.mark.unit
def test_an_undo_that_fails_escalates_carrying_both_facts() -> None:
    # An environment left in a state Argus cannot account for is precisely
    # what a human needs paging for - and the page has to say both what was
    # changed and that putting it back did not work.
    some_flag = "monthly-spend-feature"
    some_undo_failure = "flag [monthly-spend-feature] was accepted as on but still reads off"

    Scenario() \
        .given(
            set_state := _a_flag_setter_that_cannot_put_it_back(some_flag, some_undo_failure)
        ) \
        .when(
            lambda: take_action(
                an_action_setting(some_flag, enabled=False),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                changed_from_outside=nobody_changed_it()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.ESCALATED),
            _the_detail_mentions(some_flag),
            _the_detail_mentions(some_undo_failure)
        ))


@pytest.mark.unit
def test_a_flag_changed_from_outside_is_left_as_found() -> None:
    # Somebody changed the flag after Argus did. Putting it back would replace
    # a deliberate human change with a state nobody chose - and would do it
    # while claiming to be tidying up after itself.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            some_old_state := False,
            set_state := _a_flag_setter_changing_from(some_flag, was_enabled=some_old_state)
        ) \
        .when(
            lambda: take_action(
                an_action_setting(some_flag, enabled=(not some_old_state)),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                changed_from_outside=somebody_changed_it()
            )
        ) \
        .then(all_of(
            _the_flag_was_written_to(set_state, times=1),
            _the_flag_was_set_to(set_state, some_flag, enabled=(not some_old_state))
        ))


@pytest.mark.unit
def test_a_flag_changed_from_outside_is_reported_rather_than_restored() -> None:
    # The verdict is still refuted - the service did not recover - but what was
    # left behind is different, and only the detail can say so.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            some_old_state := False
        ) \
        .when(
            lambda: take_action(
                an_action_setting(some_flag, enabled=(not some_old_state)),
                set_state=_a_flag_setter_changing_from(
                    some_flag, was_enabled=some_old_state),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                changed_from_outside=somebody_changed_it()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.REFUTED),
            _the_detail_mentions(some_flag),
            _the_detail_mentions("changed")
        ))


@pytest.mark.unit
def test_a_record_that_cannot_be_read_is_not_written_over() -> None:
    # Not established is not the same as unchanged. Writing on a reading that
    # never came back is the blind restore this check exists to prevent.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            some_old_state := False,
            set_state := _a_flag_setter_changing_from(some_flag, was_enabled=some_old_state)
        ) \
        .when(
            lambda: take_action(
                an_action_setting(some_flag, enabled=(not some_old_state)),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                changed_from_outside=nobody_can_say()
            )
        ) \
        .then(all_of(
            _the_flag_was_written_to(set_state, times=1),
            the_verdict_is(Verdict.ESCALATED)
        ))


@pytest.mark.unit
def test_an_action_that_could_not_be_taken_escalates_without_a_verdict() -> None:
    # Nothing was changed, so there is nothing to judge and nothing to undo. A
    # verdict formed here would describe an experiment that never ran.
    Scenario() \
        .given(
            set_state := _a_flag_setter_that_cannot_write("the provider could not be reached")
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.ESCALATED),
            _the_flag_was_written_to(set_state, times=1)
        ))


@pytest.mark.unit
def test_a_refuted_action_is_put_back_by_the_undo_it_was_given() -> None:
    # Taking an action decides *that* a refuted change is put back; how one is
    # put back belongs to `undo_change` and is tested there. Reaching for it
    # directly is what makes a verdict here depend on the provider's world -
    # and is why this call carries no `changed_from_outside` of its own.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            some_old_state := False,
            undo := _an_undo_that_restores(some_flag)
        ) \
        .when(lambda: take_action(
            an_action_setting(some_flag, enabled=(not some_old_state)),
            set_state=_a_flag_setter_changing_from(some_flag, was_enabled=some_old_state),
            fetch_metrics=metrics_reading(a_still_failing_window()),
            now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
            sleep=dont_care_sleep,
            undo=undo
        )) \
        .then(all_of(
            _the_change_was_put_back_through(undo),
            the_verdict_is(Verdict.REFUTED)
        ))


@pytest.mark.unit
def test_the_wait_is_announced_when_the_action_has_been_taken() -> None:
    # The flag has moved by this point and production is in its new state. A
    # page that said nothing until a verdict arrived would leave a reader
    # unable to tell a slow verification from a stuck one.
    Scenario() \
        .given(
            published := _a_page_listening()
        ) \
        .when(
            lambda: _an_action_is_taken(
                publisher=published.append, metrics=a_recovered_window()
            )
        ) \
        .then(
            _the_wait_was_announced(published, times=1)
        )


@pytest.mark.unit
def test_the_wait_says_which_minute_it_will_judge_from() -> None:
    # Not the minute the action fell inside: that one is aggregated over
    # seconds either side of the change and can only blur the two states
    # together. Saying which minute counts is what makes the wait checkable.
    Scenario() \
        .given(
            published := _a_page_listening()
        ) \
        .when(
            lambda: _an_action_is_taken(
                publisher=published.append, metrics=a_recovered_window()
            )
        ) \
        .then(
            _the_wait_will_judge_from(published, _THE_FIRST_WHOLE_MINUTE_AFTER)
        )


@pytest.mark.unit
def test_each_look_at_the_service_is_published_with_what_it_saw() -> None:
    # The narration of a wait is the looking, not the waiting - a line per
    # check is what turns a blank two minutes into a page that is visibly
    # working.
    Scenario() \
        .given(
            published := _a_page_listening()
        ) \
        .when(
            lambda: _an_action_is_taken(
                publisher=published.append, metrics=a_recovered_window()
            )
        ) \
        .then(
            _each_look_reported(published, True)
        )


@pytest.mark.unit
def test_a_service_that_has_not_recovered_yet_is_published_as_not_recovered() -> None:
    # "Checked, and it is still bad" is the ordinary case for most of a wait,
    # and reporting only recovery would make a refuted action's whole
    # verification invisible.
    Scenario() \
        .given(
            published := _a_page_listening()
        ) \
        .when(
            lambda: _an_action_is_taken(
                publisher=published.append,
                metrics=a_still_failing_window(),
                clock=a_clock_that_runs_out_after_one_look(ACTION_TIME)
            )
        ) \
        .then(
            _each_look_reported(published, False)
        )


@pytest.mark.unit
def test_an_action_taken_outside_an_incident_narrates_nothing() -> None:
    # `Action` is not incident-scoped and nor is this call. An action taken
    # without one is not an error; it is an action with nothing to attribute
    # its story to, and inventing an incident to hang it on would be worse.
    Scenario() \
        .given(
            published := _a_page_listening()
        ) \
        .when(
            lambda: _an_action_is_taken(
                publisher=published.append,
                metrics=a_recovered_window(),
                incident_id=None
            )
        ) \
        .then(
            _nothing_was_narrated(published)
        )


@pytest.mark.unit
def test_the_verdict_is_the_same_whether_or_not_anybody_is_listening() -> None:
    # The account is never part of the work, here as everywhere else.
    Scenario() \
        .given(
            unheard := _an_action_is_taken(metrics=a_recovered_window())
        ) \
        .when(
            lambda: _an_action_is_taken(
                publisher=_a_page_listening().append, metrics=a_recovered_window()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_verdict_matches(unheard)
        ))


def _an_action_is_taken(metrics: list[MetricBucket],
                        publisher: Any = None,
                        clock: Callable[[], datetime] | None = None,
                        incident_id: str | None = _SOME_INCIDENT_ID) -> Outcome:
    """One action taken, with only the narration left to vary.

    The publisher is passed only when a test supplies one, so that the default
    - narrating to nobody - is the real default rather than one this rewrites.
    """
    keywords = {"publisher": publisher} if publisher is not None else {}

    return take_action(
        an_action_setting(DONT_CARE_FLAG, enabled=False),
        incident_id=incident_id,
        set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True),
        fetch_metrics=metrics_reading(metrics),
        now=clock or a_clock_frozen_at(ACTION_TIME),
        sleep=dont_care_sleep,
        **keywords
    )


def _a_flag_setter_changing_from(flag: str, was_enabled: bool) -> MagicMock:
    """Answers as the real `set_flag` does - with the descriptor that would put
    the change back. It has to be a real dict: `take_action` hands it to
    `Outcome`, which refuses anything else."""
    set_state: MagicMock = create_autospec(set_flag)
    set_state.return_value = an_undo_descriptor_for(flag, was_enabled)

    return set_state


def _a_flag_setter_that_cannot_write(failure: str) -> MagicMock:
    """The provider refuses the write, so the flag never moved."""
    set_state: MagicMock = create_autospec(set_flag)
    set_state.side_effect = RuntimeError(failure)

    return set_state


def _a_flag_setter_that_cannot_put_it_back(flag: str, failure: str) -> MagicMock:
    """Setting the flag works; putting it back is what fails."""
    set_state: MagicMock = create_autospec(set_flag)
    set_state.side_effect = [an_undo_descriptor_for(flag), RuntimeError(failure)]

    return set_state


def _an_undo_that_restores(flag: str) -> MagicMock:
    undo: MagicMock = create_autospec(undo_change)
    undo.return_value = UndoAttempt(
        flag=flag, outcome=Undone.RESTORED, detail=f"flag [{flag}] was put back"
    )

    return undo


def _metrics_that_never_recover() -> MagicMock:
    """A reader that would go on answering "still failing" for as long as it
    is asked - so what a test measures is how many times it was asked."""
    fetch_metrics: MagicMock = create_autospec(fetch_recent_metrics)
    fetch_metrics.side_effect = [a_still_failing_window(), a_still_failing_window()]

    return fetch_metrics


def _metrics_recovering_only_after_the_action() -> MagicMock:
    """The first look ends at the action, so no whole minute has followed it
    yet; the second carries one, and only then can a verdict be read."""
    fetch_metrics: MagicMock = create_autospec(fetch_recent_metrics)
    fetch_metrics.side_effect = [a_window_ending_at_the_action(), a_recovered_window()]

    return fetch_metrics


def _a_page_listening() -> list[IncidentEvent]:
    """Somewhere for the narration to land, so a test can read it back."""
    return []


def _the_verdict_matches(other: Outcome) -> Assertion[Outcome]:
    def assertion(outcome: Outcome) -> bool:
        if outcome.verdict is not other.verdict:
            raise AssertionError(
                f"Expected the same verdict either way, got [{outcome.verdict}] "
                f"with a listener and [{other.verdict}] without."
            )

        return True

    return assertion


def _the_flag_was_set_to(set_state: MagicMock,
                         flag: str,
                         enabled: bool) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        if set_state.call_args.args != (flag, enabled):
            raise AssertionError(
                f"Expected flag [{flag}] to be set to [{enabled}], "
                f"got {set_state.call_args.args}."
            )

        return True

    return assertion


def _the_flag_was_written_to(set_state: MagicMock, times: int) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        if set_state.call_count != times:
            raise AssertionError(
                f"Expected the flag to be written [{times}] times, "
                f"got [{set_state.call_count}]."
            )

        return True

    return assertion


def _the_undo_carried_is(expected: dict[str, Any]) -> Assertion[Outcome]:
    def assertion(outcome: Outcome) -> bool:
        if outcome.undo_descriptor != expected:
            raise AssertionError(
                f"Expected the outcome to carry [{expected}], "
                f"got [{outcome.undo_descriptor}]."
            )

        return True

    return assertion


def _the_change_was_put_back_through(undo: MagicMock) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        if undo.call_count != 1:
            raise AssertionError(
                f"Expected the refuted change to be put back once through the "
                f"undo given, got [{undo.call_count}] calls."
            )

        return True

    return assertion


def _the_detail_mentions(expected: str) -> Assertion[Outcome]:
    def assertion(outcome: Outcome) -> bool:
        if expected not in outcome.detail:
            raise AssertionError(
                f"Expected the detail to mention [{expected}], "
                f"got [{outcome.detail}]."
            )

        return True

    return assertion


def _the_service_was_looked_at(fetch_metrics: MagicMock, times: int) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        if fetch_metrics.call_count != times:
            raise AssertionError(
                f"Expected the service to be looked at [{times}] times, "
                f"got [{fetch_metrics.call_count}]."
            )

        return True

    return assertion


def _the_wait_was_announced(published: list[IncidentEvent], times: int) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        announced = [event for event in published if isinstance(event, AwaitingRecovery)]
        if len(announced) != times:
            raise AssertionError(
                f"Expected [{times}] announcements of the wait, got [{len(announced)}]."
            )

        return True

    return assertion


def _the_wait_will_judge_from(published: list[IncidentEvent],
                              minute: str) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        announced = next(
            event for event in published if isinstance(event, AwaitingRecovery)
        )
        if announced.from_minute != minute:
            raise AssertionError(
                f"Expected the wait to judge from [{minute}], "
                f"got [{announced.from_minute}]."
            )

        return True

    return assertion


def _each_look_reported(published: list[IncidentEvent],
                        *recoveries: bool) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        checked = [event for event in published if isinstance(event, RecoveryChecked)]
        reported = tuple(event.recovered for event in checked)

        if reported != recoveries:
            raise AssertionError(
                f"Expected the looks to report {recoveries}, got {reported}."
            )

        return True

    return assertion


def _nothing_was_narrated(published: list[IncidentEvent]) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        if published:
            raise AssertionError(
                f"Expected nothing to be narrated, got {published}."
            )

        return True

    return assertion
