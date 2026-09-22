from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation import Outcome, UndoAttempt, Undone, Verdict, take_action
from agent_mitigation.tools import (
    ConfigurationRoller,
    FlagSetter,
    MetricsFetcher,
    MitigationSettings,
    ServiceRestarter,
)
from agent_mitigation.trying import UndoChange
from argus_core import new_id
from argus_core.anomaly import AnomalyThresholds
from argus_core.events import AwaitingRecovery, IncidentEvent, RecoveryChecked
from argus_core.models import (
    ConfigRollbackUndo,
    MetricBucket,
    RestartedService,
    RollBackConfiguration,
    UndoDescriptor,
)
from argus_testkit import Assertion, Scenario, all_of, dont_care_sleep

from agent_mitigation_test.framework.assertions import the_verdict_is
from agent_mitigation_test.framework.builders import (
    ACTION_TIME,
    DONT_CARE_FLAG,
    a_clock_frozen_at,
    a_clock_that_runs_out_after_one_look,
    a_recovered_window,
    a_restorer_nobody_calls,
    a_still_failing_window,
    a_window_ending_at_the_action,
    a_window_where_memory_never_fell,
    a_window_where_memory_was_reclaimed,
    an_action_restarting,
    an_action_setting,
    an_undo_descriptor_for,
    dont_care_restart,
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(
                    DONT_CARE_FLAG, was_enabled=some_old_state),
                fetch_metrics=metrics_reading(the_service_recovers),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(
                    DONT_CARE_FLAG, was_enabled=some_old_state),
                fetch_metrics=metrics_reading(the_service_never_recovers),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(
                    DONT_CARE_FLAG, was_enabled=some_old_state),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                still_wanted=nobody_still_wants_it,
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(
                    DONT_CARE_FLAG, was_enabled=some_old_state),
                fetch_metrics=fetch_metrics,
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                still_wanted=nobody_wants_it_any_more(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                still_wanted=nobody_wants_it_any_more(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(
                    DONT_CARE_FLAG, was_enabled=some_old_state),
                fetch_metrics=fetch_metrics,
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(
                    some_flag, was_enabled=some_old_state),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
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
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=set_state,
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=dont_care_restart(),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
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
    # and is why the check this call carries is never consulted: the undo it
    # was given brought its own.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            some_old_state := False,
            dont_care_outside := nobody_changed_it(),
            undo := _an_undo_that_restores(some_flag)
        ) \
        .when(lambda: take_action(
            an_action_setting(some_flag, enabled=(not some_old_state)),
            settings=_some_mitigation_settings(),
            thresholds=_some_thresholds(),
            set_state=_a_flag_setter_changing_from(some_flag, was_enabled=some_old_state),
            fetch_metrics=metrics_reading(a_still_failing_window()),
            now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
            sleep=dont_care_sleep,
            restart=dont_care_restart(),
            undo=undo,
            restore_configuration=a_restorer_nobody_calls(),
            roll_back=_a_roller_nobody_calls(),
            changed_from_outside=dont_care_outside
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


@pytest.mark.unit
def test_taking_a_restart_asks_for_the_service_the_action_names() -> None:
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(restart := _a_restarter_bringing_up(some_leaking_service)) \
        .when(
            lambda: take_action(
                an_action_restarting(some_leaking_service),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True),
                fetch_metrics=metrics_reading(a_window_where_memory_was_reclaimed()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=restart,
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
            )
        ) \
        .then(
            _the_service_restarted_was(restart, some_leaking_service)
        )


@pytest.mark.unit
def test_a_service_whose_memory_was_reclaimed_confirms_the_restart() -> None:
    # Both halves of the answer. Either alone is ambiguous: traffic moving on
    # eases the symptoms of a service nothing was done to, and a heap that fell
    # says only that a process restarted, not that the incident is over.
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(
            the_heap_came_back_down := a_window_where_memory_was_reclaimed()
        ) \
        .when(
            lambda: take_action(
                an_action_restarting(some_leaking_service),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True),
                fetch_metrics=metrics_reading(the_heap_came_back_down),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=_a_restarter_bringing_up(some_leaking_service),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_detail_mentions(f"restarted [{some_leaking_service}]")
        ))


@pytest.mark.unit
def test_a_restart_whose_memory_never_fell_is_refuted_though_the_symptoms_eased() -> None:
    # The case the recovery check grew a third signal for. On latency and
    # errors alone this confirms the moment the failing traffic moves on - with
    # the heap still where the leak left it, and the process that has been
    # accumulating since before the incident still the one serving.
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(
            the_heap_stayed_up := a_window_where_memory_never_fell()
        ) \
        .when(
            lambda: take_action(
                an_action_restarting(some_leaking_service),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True),
                fetch_metrics=metrics_reading(the_heap_stayed_up),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=_a_restarter_bringing_up(some_leaking_service),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
            )
        ) \
        .then(
            the_verdict_is(Verdict.REFUTED)
        )


@pytest.mark.unit
def test_a_restart_that_could_not_be_taken_escalates_without_a_verdict() -> None:
    # Nothing was done to the service, so there is nothing to judge. A verdict
    # here would read a leak still climbing as evidence that restarting a
    # leaking service does not work.
    some_leaking_service = "kuki-service"
    some_failure = "the platform refused the action"

    Scenario() \
        .given(
            restart_could_not_be_taken := _a_restarter_that_cannot(some_failure)
        ) \
        .when(
            lambda: take_action(
                an_action_restarting(some_leaking_service),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True),
                fetch_metrics=metrics_reading(a_window_where_memory_was_reclaimed()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=restart_could_not_be_taken,
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.ESCALATED),
            _the_detail_mentions(f"restart [{some_leaking_service}]"),
            _the_detail_mentions(some_failure)
        ))


@pytest.mark.unit
def test_a_refuted_restart_puts_nothing_back_and_says_so() -> None:
    # Not "the undo failed", and not silence. A restart that did not help is a
    # hypothesis refuted cleanly, and a reader has to be able to tell that from
    # a flag Argus could not put back.
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(
            nothing_was_ever_written := _a_flag_setter_changing_from(
                DONT_CARE_FLAG, was_enabled=True)
        ) \
        .when(
            lambda: take_action(
                an_action_restarting(some_leaking_service),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=nothing_was_ever_written,
                fetch_metrics=metrics_reading(a_window_where_memory_never_fell()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=_a_restarter_bringing_up(some_leaking_service),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.REFUTED),
            _the_flag_was_written_to(nothing_was_ever_written, times=0),
            _the_detail_mentions("nothing to put back"),
            _there_is_nothing_to_put_back()
        ))


@pytest.mark.unit
def test_a_confirmed_restart_carries_no_way_back_either() -> None:
    # A withdrawal hours later reads the outcome and does what it says. There
    # is no prior value a restart could name, so the field is absent rather
    # than empty - and absent is the only state that cannot be misread.
    some_leaking_service = "kuki-service"

    Scenario() \
        .given(
            the_heap_came_back_down := a_window_where_memory_was_reclaimed()
        ) \
        .when(
            lambda: take_action(
                an_action_restarting(some_leaking_service),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True),
                fetch_metrics=metrics_reading(the_heap_came_back_down),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=_a_restarter_bringing_up(some_leaking_service),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_nobody_calls(),
                changed_from_outside=nobody_changed_it()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _there_is_nothing_to_put_back()
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
        settings=_some_mitigation_settings(),
        thresholds=_some_thresholds(),
        incident_id=incident_id,
        set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True),
        fetch_metrics=metrics_reading(metrics),
        now=clock or a_clock_frozen_at(ACTION_TIME),
        sleep=dont_care_sleep,
        restart=dont_care_restart(),
        restore_configuration=a_restorer_nobody_calls(),
        roll_back=_a_roller_nobody_calls(),
        changed_from_outside=nobody_changed_it(),
        **keywords
    )


def _a_restarter_bringing_up(service: str) -> MagicMock:
    """Answers as the real restarter does - with the process that came up.

    The start time it reports is arbitrary here: what makes a restart checkable
    is that it *moved*, and the tier that performed it is the only thing in a
    position to have waited for that. By the time an outcome is being judged,
    the question is what the service did next.
    """
    dont_care_start_time = 1_756_000_600.0
    restart: MagicMock = create_autospec(ServiceRestarter, instance=True)
    restart.return_value = RestartedService(
        service=service, process_start_time_seconds=dont_care_start_time
    )

    return restart


def _a_restarter_that_cannot(failure: str) -> MagicMock:
    restart: MagicMock = create_autospec(ServiceRestarter, instance=True)
    restart.side_effect = RuntimeError(failure)

    return restart


def _a_flag_setter_changing_from(flag: str, was_enabled: bool) -> MagicMock:
    """Answers as the real `set_flag` does - with the descriptor that would put
    the change back."""
    set_state: MagicMock = create_autospec(FlagSetter, instance=True)
    set_state.return_value = an_undo_descriptor_for(flag, was_enabled)

    return set_state


def _a_flag_setter_that_cannot_write(failure: str) -> MagicMock:
    """The provider refuses the write, so the flag never moved."""
    set_state: MagicMock = create_autospec(FlagSetter, instance=True)
    set_state.side_effect = RuntimeError(failure)

    return set_state


def _a_flag_setter_that_cannot_put_it_back(flag: str, failure: str) -> MagicMock:
    """Setting the flag works; putting it back is what fails."""
    set_state: MagicMock = create_autospec(FlagSetter, instance=True)
    set_state.side_effect = [an_undo_descriptor_for(flag), RuntimeError(failure)]

    return set_state


def _an_undo_that_restores(flag: str) -> MagicMock:
    undo: MagicMock = create_autospec(UndoChange, instance=True)
    undo.return_value = UndoAttempt(
        subject=flag, outcome=Undone.RESTORED, detail=f"flag [{flag}] was put back"
    )

    return undo


def _metrics_that_never_recover() -> MagicMock:
    """A reader that would go on answering "still failing" for as long as it
    is asked - so what a test measures is how many times it was asked."""
    fetch_metrics: MagicMock = create_autospec(MetricsFetcher, instance=True)
    fetch_metrics.side_effect = [a_still_failing_window(), a_still_failing_window()]

    return fetch_metrics


def _metrics_recovering_only_after_the_action() -> MagicMock:
    """The first look ends at the action, so no whole minute has followed it
    yet; the second carries one, and only then can a verdict be read."""
    fetch_metrics: MagicMock = create_autospec(MetricsFetcher, instance=True)
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


def _the_service_restarted_was(restart: MagicMock, service: str) -> Assertion[Outcome]:
    def assertion(dont_care_outcome: Outcome) -> bool:
        restarted = restart.call_args.args[0] if restart.call_args else None
        if restarted != service:
            raise AssertionError(
                f"Expected [{service}] to be restarted, and [{restarted}] was."
            )

        return True

    return assertion


def _there_is_nothing_to_put_back() -> Assertion[Outcome]:
    """No descriptor at all, rather than one nobody can act on.

    A withdrawal hours later reads this field and does what it says. An empty
    descriptor would be a hole every reader had to interpret; an absent one
    cannot be misread.
    """
    def assertion(outcome: Outcome) -> bool:
        if outcome.undo_descriptor is not None:
            raise AssertionError(
                f"Expected the outcome to carry no way back, and it carried "
                f"[{outcome.undo_descriptor}]."
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


def _the_undo_carried_is(expected: UndoDescriptor) -> Assertion[Outcome]:
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


# How long the verification waits. Short, because every test here would
# otherwise sit through it - the clock and the sleeper are injected, so what
# this bounds is the arithmetic rather than any real wait.
A_SHORT_WAIT_IN_SECONDS = 180.0


def _some_mitigation_settings() -> MitigationSettings:
    """How Mitigation behaves, as this suite sets it.

    The lookback and the actor are named because the attribution tests turn on
    them; the wait is named because the expiry tests do. The cap is named only
    because the slice requires one - how many attempts a subject is allowed is
    the gate's question, and nothing taken here ever asks it twice.
    """
    return MitigationSettings(
        flag_change_lookback_minutes=60,
        unleash_actor="argus",
        mitigation_verification_timeout_seconds=A_SHORT_WAIT_IN_SECONDS,
        mitigation_attempts_per_subject=1
    )


def _some_thresholds() -> AnomalyThresholds:
    """Where recovery is judged from - the defaults, stated rather than read."""
    return AnomalyThresholds(
        deviations_from_baseline=3.0,
        persistence_minutes=2,
        recovery_fraction_of_the_rise=0.8
    )


SOME_APPLICATION = "io-shop"
THE_REVISION_IT_WAS_ON = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"


def _a_rollback_of(application: str) -> RollBackConfiguration:
    return RollBackConfiguration(application=application)


def _a_rollback_descriptor_for(application: str,
                               was_syncing_itself: bool = True) -> ConfigRollbackUndo:
    return ConfigRollbackUndo(
        application=application,
        was_on_history_id=2,
        was_on_revision=THE_REVISION_IT_WAS_ON,
        was_syncing_itself=was_syncing_itself
    )


def _a_roller_nobody_calls() -> MagicMock:
    """The third write, wired but not exercised.

    Every case here has to supply one because the collaborator is required -
    an agent that could be built without a way to perform an action it may
    propose is an agent that discovers it at the worst moment - and most cases
    are about a different kind of action entirely.
    """
    roll_back: MagicMock = create_autospec(ConfigurationRoller, instance=True)

    return roll_back


def _a_roller_returning(application: str) -> MagicMock:
    """Answers as the real roller does - with the descriptor recording both
    things it changed.

    Both, because rolling a deployment back means suspending the platform's
    own reconciliation first: it refuses otherwise, and would re-apply the
    revision being rolled away from at the next pass.
    """
    roll_back: MagicMock = create_autospec(ConfigurationRoller, instance=True)
    roll_back.return_value = _a_rollback_descriptor_for(application)

    return roll_back


@pytest.mark.unit
def test_taking_a_rollback_asks_for_the_application_and_the_entry() -> None:
    # The entry rather than a commit. A commit found in a diff is not
    # necessarily a revision this application ever ran, and rolling onto one
    # would be shipping an untested state under the name of a rollback.
    Scenario() \
        .given(roll_back := _a_roller_returning(SOME_APPLICATION)) \
        .when(
            lambda: take_action(
                _a_rollback_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=_a_restarter_bringing_up("dont-care-service"),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=roll_back,
                changed_from_outside=nobody_changed_it()
            )
        ) \
            .then(
            _the_rollback_asked_for(roll_back, SOME_APPLICATION)
        )


@pytest.mark.unit
def test_a_deployment_that_recovered_after_a_rollback_confirms_it() -> None:
    Scenario() \
        .given(_a_roller_returning(SOME_APPLICATION)) \
        .when(
            lambda: take_action(
                _a_rollback_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=_a_restarter_bringing_up("dont-care-service"),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_returning(SOME_APPLICATION),
                changed_from_outside=nobody_changed_it()
            )
        ) \
            .then(
            the_verdict_is(Verdict.CONFIRMED)
        )


@pytest.mark.unit
def test_a_rollback_carries_a_way_back_where_a_restart_carries_none() -> None:
    # The difference the record has to keep. A restart leaves nothing behind
    # and says so by carrying no descriptor; a rollback changed two things,
    # and a withdrawal hours later has to be able to put both of them back.
    Scenario() \
        .given(_a_roller_returning(SOME_APPLICATION)) \
        .when(
            lambda: take_action(
                _a_rollback_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                restart=_a_restarter_bringing_up("dont-care-service"),
                restore_configuration=a_restorer_nobody_calls(),
                roll_back=_a_roller_returning(SOME_APPLICATION),
                changed_from_outside=nobody_changed_it(),
                undo=_an_undo_that_restores(SOME_APPLICATION)
            )
        ) \
            .then(
            _it_carries_a_way_back()
        )


def _the_rollback_asked_for(roll_back: MagicMock,
                            application: str) -> Assertion[Outcome]:
    """Named by application alone.

    Which entry to return to is the platform's to resolve - the immediately
    preceding deployment - because nothing here holds a deployment history to
    choose from.
    """
    def assertion(dont_care_outcome: Outcome) -> bool:
        asked = roll_back.call_args.args if roll_back.call_args else ()

        if asked != (application,):
            raise AssertionError(
                f"Expected a rollback of [{application}], and it asked for "
                f"{asked}."
            )

        return True

    return assertion


def _it_carries_a_way_back() -> Assertion[Outcome]:
    def assertion(outcome: Outcome) -> bool:
        if outcome.undo_descriptor is None:
            raise AssertionError(
                "Expected the outcome to carry the way back the rollback left, "
                "and it carried none."
            )

        return True

    return assertion
