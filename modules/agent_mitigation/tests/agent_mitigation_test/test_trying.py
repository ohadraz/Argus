from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation import Outcome, UndoAttempt, Undone, Verdict, take_action
from agent_mitigation.tools import (
    AutoscalerPinner,
    DeploymentRoller,
    DeploymentScaler,
    FlagSetter,
    MetricsFetcher,
    MitigationSettings,
    ServiceRestarter,
)
from agent_mitigation.trying import UndoChange
from argus_core import new_id
from argus_core.anomaly import AnomalyThresholds
from argus_core.events import AwaitingRecovery, IncidentEvent, RecoveryChecked, RetrievalUnanswered
from argus_core.mcp_transport import (
    EXHAUSTED_ACTION_MARKER,
    LEFT_BEHIND_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    ActionExhausted,
    McpToolError,
    PlatformUnreachable,
    an_exhausted_action,
    an_unreachable_platform,
)
from argus_core.models import (
    DEPLOYMENT_PLATFORM,
    AutoscalerUndo,
    DeploymentRollbackUndo,
    MetricBucket,
    PinAutoscaler,
    ReplicaUndo,
    RestartedService,
    RollBackDeployment,
    ScaleOut,
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
    a_still_failing_window,
    a_window_ending_at_the_action,
    a_window_where_memory_never_fell,
    a_window_where_memory_was_reclaimed,
    an_action_restarting,
    an_action_setting,
    an_undo_descriptor_for,
    an_undo_nobody_calls,
    an_undo_putting_flags_back,
    metrics_reading,
    nobody_can_say,
    nobody_changed_it,
    nobody_wants_it_any_more,
    somebody_changed_it,
    the_writes,
)

_SOME_INCIDENT_ID = new_id()
# ACTION_TIME falls at 11:10:30, so the first minute that wholly follows it is
# 11:11 - the earliest one a verdict may be read off.
_THE_FIRST_WHOLE_MINUTE_AFTER = "2026-08-20T11:11:00Z"

SOME_COUNT_IT_WAS_RUNNING = 3
SOME_APPLICATION = "io-shop"
THE_REVISION_IT_WAS_ON = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"

# The ceiling's refusal, in the words the write tier raises it with. Quoted
# rather than paraphrased, because what these cases are about is that those
# words reach the walk: a test inventing its own sentence would go on passing
# while the reason was being dropped somewhere between the tier and the record,
# and an escalation with no reason on it is indistinguishable from a platform
# that fell over.
THE_CEILING_REFUSED = (
    f"[{SOME_APPLICATION}] is running [12] replicas, which is as large as Argus "
    f"may make it ([12])"
)
# The two refusals a pin can meet, in the words the write tier raises them with,
# and quoted for the reason the ceiling's are. The pair is the point: one is an
# estate with nothing left to hold still, the other a platform that would not
# make the change - and they are told apart by the marker rather than by their
# wording, so a case matching on the words would pass whichever verdict it got.
THE_AUTOSCALER_HAS_NO_ROOM_LEFT = (
    f"[{SOME_APPLICATION}]'s autoscaler may fall to [6] replicas and rise to "
    f"[6], and the highest floor Argus may ask for is [6] - so there is no room "
    f"left between the two and nothing here for a pin to stop"
)
THE_PATCH_WAS_REFUSED = (
    f"the platform would not patch [{SOME_APPLICATION}]'s autoscaler"
)
# What the tier says when the platform was not there to be asked, and what it
# says when the platform answered and said no. Two constants because the pair of
# tests they belong to exists precisely to keep the two apart - a suite that used
# one string for both would pass with the branches swapped.
THE_PLATFORM_DID_NOT_ANSWER = "the deployment platform did not answer"
THE_ROLLBACK_WAS_REFUSED = (
    f"the platform would not roll [{SOME_APPLICATION}] back"
)
# What a rollback leaves behind when the platform goes after the suspension
# landed: reconciliation suspended, the revision unmoved. A real descriptor
# rather than an invented shape, because what is asserted is that this exact
# value reaches the outcome.
WHAT_THE_ROLLBACK_LEFT = DeploymentRollbackUndo(
    application=SOME_APPLICATION,
    was_on_history_id=41,
    was_on_revision="0f1e2d3",
    was_syncing_itself=True
)

# The two floors a pin moves between. Named separately from the replica counts
# above because they are a different claim: those are how large the deployment is,
# these are how small it is allowed to become.
SOME_FLOOR_IT_COULD_FALL_TO = 3
THE_FLOOR_IT_WAS_HELD_AT = 6

# How long the verification waits. Short, because every test here would
# otherwise sit through it - the clock and the sleeper are injected, so what
# this bounds is the arithmetic rather than any real wait.
A_SHORT_WAIT_IN_SECONDS = 180.0


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
                writes=the_writes(set_state=set_state),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=some_old_state
                    )
                ),
                fetch_metrics=metrics_reading(the_service_recovers),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(
                    set_state=(set_state := _a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=some_old_state
                    ))
                ),
                fetch_metrics=metrics_reading(the_service_never_recovers),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_putting_flags_back(set_state, nobody_changed_it())
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
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=some_old_state
                    )
                ),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                still_wanted=nobody_still_wants_it,
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=some_old_state
                    )
                ),
                fetch_metrics=fetch_metrics,
                now=a_clock_frozen_at(ACTION_TIME),
                still_wanted=nobody_wants_it_any_more(),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(set_state=set_state),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                still_wanted=nobody_wants_it_any_more(),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=some_old_state
                    )
                ),
                fetch_metrics=fetch_metrics,
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(set_state=set_state),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_putting_flags_back(set_state, nobody_changed_it())
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
                writes=the_writes(set_state=set_state),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(set_state=set_state),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_putting_flags_back(set_state, nobody_changed_it())
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
                writes=the_writes(set_state=set_state),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_putting_flags_back(set_state, somebody_changed_it())
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
                writes=the_writes(
                    set_state=(set_state := _a_flag_setter_changing_from(
                        some_flag, was_enabled=some_old_state
                    ))
                ),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_putting_flags_back(set_state, somebody_changed_it())
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
                writes=the_writes(set_state=set_state),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_putting_flags_back(set_state, nobody_can_say())
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
                writes=the_writes(set_state=set_state),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
            undo := _an_undo_that_restores(some_flag)
        ) \
        .when(lambda: take_action(
            an_action_setting(some_flag, enabled=(not some_old_state)),
            settings=_some_mitigation_settings(),
            thresholds=_some_thresholds(),
            writes=the_writes(
                set_state=_a_flag_setter_changing_from(
                    some_flag, was_enabled=some_old_state
                )
            ),
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
def test_a_read_that_could_not_be_answered_costs_one_pass_and_not_the_incident() -> None:
    # The verification loop is a poll with a deadline, and a read that raises
    # inside it used to end the incident rather than the pass: nothing catches
    # it, so `take_action` never returns, no verdict is recorded, and the walk
    # leaves the incident wherever it was. Twice observed against the real
    # stack, both times a metrics read timing out seconds after a flag was
    # reverted, and both times the shop had in fact recovered - so the incident
    # that was stranded was one whose mitigation had worked.
    #
    # Two claims, and they belong together because either alone is the wrong
    # behaviour. The pass is *said*, so a person reading the incident can see
    # why the verdict took longer than the window; and the loop carries on, so
    # the reading it could not take costs one pass of a poll that already has a
    # deadline. Carrying on silently would be the same incident with a gap
    # nobody can account for.
    #
    # Deliberately not a verdict of its own. The action here worked - the next
    # read finds the service recovered - and a loop that gave up on the first
    # unreadable pass would report a working mitigation as refuted, which is
    # worse than the stranding it replaced.
    Scenario() \
        .given(
            published := _a_page_listening()
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                incident_id=_SOME_INCIDENT_ID,
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=True
                    )
                ),
                fetch_metrics=_a_read_that_fails_once_then_answers(
                    a_recovered_window()
                ),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls(),
                publisher=published.append
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_unanswered_read_was_said(
                published, _THE_FIRST_WHOLE_MINUTE_AFTER
            ),
            _each_look_reported(published, True)
        ))


@pytest.mark.unit
def test_a_wait_that_never_read_the_service_reaches_no_verdict() -> None:
    # A verdict is a measurement, and here there is none. Every read failing is
    # not a rare shape: the load that makes the read tier time out is the
    # polling that feeds this loop, so it lasts as long as the window does, and
    # the window can run out with not one reading taken in it.
    #
    # Not `REFUTED`, and not only because the word is wrong. `REFUTED` marks the
    # hypothesis tested, puts the change back and hands the walk to the next
    # candidate - so a mitigation that worked is undone, the shop is broken
    # again, and the explanation that was right is struck off, all on nothing
    # anybody measured. Both times this was seen against the real stack the
    # service had in fact recovered.
    #
    # `ESCALATED` already means what happened: no verdict was reached at all.
    # The change stays where the action left it, carrying what would put it
    # back, exactly as a withdrawn action's does - because what to do about a
    # service nobody could read is a person's decision, and the one thing that
    # must not happen is Argus making it by default.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            some_old_state := False,
            set_state := _a_flag_setter_changing_from(some_flag, was_enabled=some_old_state),
            undo := an_undo_nobody_calls()
        ) \
        .when(
            lambda: take_action(
                an_action_setting(some_flag, enabled=(not some_old_state)),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(set_state=set_state),
                fetch_metrics=_a_read_that_never_answers(),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=undo
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.ESCALATED),
            _it_says_nothing_was_measured(),
            _nothing_was_put_back_through(undo),
            _the_undo_carried_is(an_undo_descriptor_for(some_flag, was_enabled=some_old_state))
        ))


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
                writes=the_writes(restart=restart),
                fetch_metrics=metrics_reading(a_window_where_memory_was_reclaimed()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(
                    restart=_a_restarter_bringing_up(some_leaking_service)
                ),
                fetch_metrics=metrics_reading(the_heap_came_back_down),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(
                    restart=_a_restarter_bringing_up(some_leaking_service)
                ),
                fetch_metrics=metrics_reading(the_heap_stayed_up),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(restart=restart_could_not_be_taken),
                fetch_metrics=metrics_reading(a_window_where_memory_was_reclaimed()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(
                    set_state=nothing_was_ever_written,
                    restart=_a_restarter_bringing_up(some_leaking_service)
                ),
                fetch_metrics=metrics_reading(a_window_where_memory_never_fell()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(
                    restart=_a_restarter_bringing_up(some_leaking_service)
                ),
                fetch_metrics=metrics_reading(the_heap_came_back_down),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _there_is_nothing_to_put_back()
        ))


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
                writes=the_writes(
                    restart=_a_restarter_bringing_up("dont-care-service"),
                    roll_back=roll_back
                ),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(
                    restart=_a_restarter_bringing_up("dont-care-service"),
                    roll_back=_a_roller_returning(SOME_APPLICATION)
                ),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
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
                writes=the_writes(
                    restart=_a_restarter_bringing_up("dont-care-service"),
                    roll_back=_a_roller_returning(SOME_APPLICATION)
                ),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=_an_undo_that_restores(SOME_APPLICATION)
            )
        ) \
            .then(
            _it_carries_a_way_back()
        )


@pytest.mark.unit
def test_taking_a_scale_out_asks_the_platform_for_the_application_alone() -> None:
    # No count goes with it. What to scale to is the tier's to resolve from what
    # is actually running, and a figure named here would be this layer asserting
    # a fact about live state it has no way to read.
    Scenario() \
        .given(scale_out := _a_scaler_returning(SOME_APPLICATION)) \
        .when(
            lambda: take_action(
                _a_scale_out_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(scale_out=scale_out),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            _the_scale_out_asked_for(scale_out, SOME_APPLICATION)
        )


@pytest.mark.unit
def test_a_deployment_that_recovered_after_a_scale_out_confirms_it() -> None:
    # Judged by the same rule every other kind is: the service returned to its
    # baseline in the minutes after the action. Nothing about capacity is
    # special here, which is the point - a fourth kind of action does not bring
    # a fourth way of being right.
    Scenario() \
        .given(the_latency_came_back_down := a_recovered_window()) \
        .when(
            lambda: take_action(
                _a_scale_out_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(scale_out=_a_scaler_returning(SOME_APPLICATION)),
                fetch_metrics=metrics_reading(the_latency_came_back_down),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_detail_mentions(f"[{SOME_COUNT_IT_WAS_RUNNING}] replicas"),
            _it_carries_the_count_to_put_back(SOME_COUNT_IT_WAS_RUNNING)
        ))


@pytest.mark.unit
def test_a_scale_out_at_the_ceiling_reaches_the_walk_as_the_refusal_it_is() -> None:
    # An escalation with the bound's own sentence on it. Nothing was changed, so
    # there is no verdict to reach - but the reason matters more here than for
    # any other failure to act: "Argus has run out of room to grow this
    # deployment" is a sentence somebody can do something about, where a bare
    # escalation reads as a platform that could not be reached.
    Scenario() \
        .given(
            the_deployment_is_as_large_as_it_may_get := _a_scaler_that_cannot(
                THE_CEILING_REFUSED
            )
        ) \
        .when(
            lambda: take_action(
                _a_scale_out_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(
                    scale_out=the_deployment_is_as_large_as_it_may_get
                ),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.ESCALATED),
            _the_detail_mentions(f"scale [{SOME_APPLICATION}] out"),
            _the_detail_mentions(THE_CEILING_REFUSED),
            _there_is_nothing_to_put_back()
        ))


@pytest.mark.unit
def test_a_refuted_scale_out_says_which_count_it_was_put_back_to() -> None:
    # The count, not "the previous size". A reader picking the incident up has to
    # be able to tell what the deployment is running now without going to the
    # platform to ask, and the figure the tier read is the only honest one -
    # nothing else here ever knew it.
    Scenario() \
        .given(undo := _an_undo_that_puts_the_count_back(SOME_APPLICATION)) \
        .when(
            lambda: take_action(
                _a_scale_out_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(scale_out=_a_scaler_returning(SOME_APPLICATION)),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=undo
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.REFUTED),
            _the_detail_mentions(f"to [{SOME_COUNT_IT_WAS_RUNNING}] replicas"),
            _it_carries_the_count_to_put_back(SOME_COUNT_IT_WAS_RUNNING)
        ))


@pytest.mark.unit
def test_an_autoscaler_with_no_room_left_is_not_attempted_rather_than_escalated() -> None:
    # The verdict that exists so a bound Argus holds does not wake anybody. The
    # tier was reached, it answered, and its answer is that a floor already meets
    # its ceiling - nothing is wrong, nothing was changed, and the walk has other
    # candidates. Escalating here ends a walk whose next candidate might be a flag
    # revert that takes seconds.
    #
    # Not `REFUTED` either, and that is the trap the assertion below is really
    # about: `REFUTED` says an explanation was tested and did not hold, where
    # nothing was tested - a record carrying it would have the postmortem report
    # that the evidence ruled a cause out when nothing ruled it out.
    Scenario() \
        .given(
            the_autoscaler_is_already_held_still := _a_pinner_with_no_room_left(
                THE_AUTOSCALER_HAS_NO_ROOM_LEFT
            )
        ) \
        .when(
            lambda: take_action(
                _a_pin_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(pin=the_autoscaler_is_already_held_still),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.NOT_ATTEMPTED),
            _it_says_nothing_was_measured(),
            _the_detail_mentions(
                f"stop [{SOME_APPLICATION}]'s autoscaler scaling it down"
            ),
            _the_detail_mentions(THE_AUTOSCALER_HAS_NO_ROOM_LEFT),
            _the_detail_does_not_mention(EXHAUSTED_ACTION_MARKER),
            _there_is_nothing_to_put_back()
        ))


@pytest.mark.unit
def test_a_pin_refused_without_the_marker_still_escalates() -> None:
    # The half that matters, and the one a single catch in the wrong order gets
    # wrong. `ActionExhausted` is an `McpToolError` like any other, so the broad
    # handler reached first swallows the exhausted case into an escalation - which
    # is the failure this pair is written around. This case is the other
    # direction: an unmarked refusal must *not* become the new verdict.
    #
    # The distinction is not a taxonomy. The tier raises both, and only the one
    # that changed nothing is marked: a refused patch can fire after sync was
    # already suspended, so the estate is in a state nobody can name and a human
    # has to look. Reading that as "nothing left to do" would move the walk on
    # from a deployment it has half-changed.
    Scenario() \
        .given(
            the_platform_would_not_patch_it := _a_pinner_that_cannot(
                THE_PATCH_WAS_REFUSED
            )
        ) \
        .when(
            lambda: take_action(
                _a_pin_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(pin=the_platform_would_not_patch_it),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.ESCALATED),
            _it_says_nothing_was_measured(),
            _the_detail_mentions(
                f"stop [{SOME_APPLICATION}]'s autoscaler scaling it down"
            ),
            _the_detail_mentions(THE_PATCH_WAS_REFUSED),
            _there_is_nothing_to_put_back()
        ))


@pytest.mark.unit
def test_a_rollback_whose_platform_was_not_there_is_neither_escalated_nor_exhausted() -> None:
    # The third thing a write can come back with, and the one that is never about
    # the action asked for. Four of the five generic mitigations reach the estate
    # through this platform, so a platform that is not answering has taken four
    # away at once - and what the walk does about that is pass over the other
    # three and reach for whatever acts through something else.
    #
    # Not `ESCALATED`, for the reason an exhausted action is not: escalating here
    # ends a walk whose next candidate is a flag revert on a provider that is
    # still answering. Not `NOT_ATTEMPTED` either, and that distinction is the
    # subtle one - that verdict says the tier answered and had nowhere left to
    # go, where this says it could not ask at all. A record carrying it would
    # report a bound that was never reached.
    Scenario() \
        .given(
            the_platform_was_not_answering := _a_roller_that_cannot_reach_the_platform(
                THE_PLATFORM_DID_NOT_ANSWER
            )
        ) \
        .when(
            lambda: take_action(
                _a_rollback_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(roll_back=the_platform_was_not_answering),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.PLATFORM_UNREACHABLE),
            _it_says_nothing_was_measured(),
            _the_detail_mentions(THE_PLATFORM_DID_NOT_ANSWER),
            _the_detail_does_not_mention(UNREACHABLE_PLATFORM_MARKER),
            _there_is_nothing_to_put_back()
        ))


@pytest.mark.unit
def test_a_rollback_refused_by_a_platform_that_answered_still_escalates() -> None:
    # The half that decides whether the test above is worth having, and the one a
    # single catch in the wrong order gets wrong in the other direction. A tier
    # that read every refusal as an unreachable platform would satisfy the case
    # above and have the walk write off four actions whenever one call was merely
    # rejected - and a rollback can be rejected *after* reconciliation was
    # suspended, which leaves the estate in a state nobody can name.
    Scenario() \
        .given(
            the_platform_refused_it := _a_roller_that_cannot(THE_ROLLBACK_WAS_REFUSED)
        ) \
        .when(
            lambda: take_action(
                _a_rollback_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(roll_back=the_platform_refused_it),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.ESCALATED),
            _the_detail_mentions(THE_ROLLBACK_WAS_REFUSED),
            _there_is_nothing_to_put_back()
        ))


@pytest.mark.unit
def test_a_pin_whose_platform_was_not_there_is_reported_the_same_way() -> None:
    # One kind is not the claim. What the walk narrows itself on is that every
    # action through this platform comes back the same way, so a second kind is
    # what says the verdict belongs to the platform rather than to the rollback -
    # and the pin is the one whose own tier already has two failure branches of
    # its own to be confused with.
    Scenario() \
        .given(
            the_platform_was_not_answering := _a_pinner_that_cannot_reach_the_platform(
                THE_PLATFORM_DID_NOT_ANSWER
            )
        ) \
        .when(
            lambda: take_action(
                _a_pin_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(pin=the_platform_was_not_answering),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.PLATFORM_UNREACHABLE),
            _the_detail_mentions(THE_PLATFORM_DID_NOT_ANSWER),
            _there_is_nothing_to_put_back()
        ))


@pytest.mark.unit
def test_a_platform_lost_after_the_suspension_still_narrows_and_says_what_it_left() -> None:
    # Both facts, because a walk needs both. The platform is gone, so the other
    # three actions through it are unavailable however far into this one the
    # outage arrived - and an application is sitting un-reconciled, which nothing
    # else records.
    #
    # The alternative was to escalate here, and it is wrong for the reason this
    # whole change exists: it would narrow the walk or not depending on which
    # call the outage happened to land on. A rollback suspends reconciliation
    # first because the platform refuses otherwise, so "after the first write" is
    # an ordinary place for an outage to arrive, not an exotic one.
    Scenario() \
        .given(
            the_platform_went_mid_rollback := _a_roller_that_lost_the_platform_mid_action(
                THE_PLATFORM_DID_NOT_ANSWER
            )
        ) \
        .when(
            lambda: take_action(
                _a_rollback_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(roll_back=the_platform_went_mid_rollback),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.PLATFORM_UNREACHABLE),
            _it_carries_back(WHAT_THE_ROLLBACK_LEFT)
        ))


@pytest.mark.unit
def test_what_a_person_reads_of_a_lost_platform_is_not_the_payload() -> None:
    # The descriptor rides in the same string the detail is built from, and the
    # detail is what appears in the timeline, the postmortem and a Slack line. A
    # JSON object in the middle of a sentence tells a reader nothing the verdict
    # beside it has not already said.
    Scenario() \
        .given(
            the_platform_went_mid_rollback := _a_roller_that_lost_the_platform_mid_action(
                THE_PLATFORM_DID_NOT_ANSWER
            )
        ) \
        .when(
            lambda: take_action(
                _a_rollback_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(roll_back=the_platform_went_mid_rollback),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            _the_detail_mentions(THE_PLATFORM_DID_NOT_ANSWER),
            _the_detail_does_not_mention(LEFT_BEHIND_MARKER)
        ))


@pytest.mark.unit
def test_a_confirmed_pin_says_which_floor_it_raised_and_to_what() -> None:
    # Both numbers, because an account of a pin is a transition and one of them is
    # half of it. The floor it came from is what a withdrawal puts back. The floor
    # it went to is the one a reader cannot reconstruct: the tier asks for whichever
    # is smaller of the declared ceiling and Argus's own cap, so a line naming the
    # destination as "its ceiling" is false in exactly the case nobody checks - and
    # names a number that belongs to somebody else's declaration rather than to
    # anything Argus wrote.
    Scenario() \
        .given(the_latency_came_back_down := a_recovered_window()) \
        .when(
            lambda: take_action(
                _a_pin_of(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(
                    pin=_a_pinner_holding_it_at(
                        SOME_APPLICATION, THE_FLOOR_IT_WAS_HELD_AT
                    )
                ),
                fetch_metrics=metrics_reading(the_latency_came_back_down),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_detail_mentions(f"from [{SOME_FLOOR_IT_COULD_FALL_TO}] replicas"),
            _the_detail_mentions(f"to [{THE_FLOOR_IT_WAS_HELD_AT}]"),
            _the_detail_does_not_mention("its ceiling")
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
        writes=the_writes(
            set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True)
        ),
        fetch_metrics=metrics_reading(metrics),
        now=clock or a_clock_frozen_at(ACTION_TIME),
        sleep=dont_care_sleep,
        undo=an_undo_nobody_calls(),
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


def _the_detail_does_not_mention(forbidden: str) -> Assertion[Outcome]:
    """What a reader must not be shown, asserted rather than assumed.

    The marker is how the transport classified this refusal, and it has done that
    job by the time a detail is written. It reaches a timeline, a postmortem and a
    Slack line, where `argus:action-exhausted` in the middle of a sentence tells a
    person nothing the verdict beside it has not already said - and a stripping
    step nobody asserts is one that quietly stops happening.
    """
    def assertion(outcome: Outcome) -> bool:
        if forbidden in outcome.detail:
            raise AssertionError(
                f"Expected the detail not to mention [{forbidden}], "
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


def _a_rollback_of(application: str) -> RollBackDeployment:
    return RollBackDeployment(application=application)


def _a_rollback_descriptor_for(application: str,
                               was_syncing_itself: bool = True) -> DeploymentRollbackUndo:
    return DeploymentRollbackUndo(
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
    roll_back: MagicMock = create_autospec(DeploymentRoller, instance=True)

    return roll_back


def _a_roller_returning(application: str) -> MagicMock:
    """Answers as the real roller does - with the descriptor recording both
    things it changed.

    Both, because rolling a deployment back means suspending the platform's
    own reconciliation first: it refuses otherwise, and would re-apply the
    revision being rolled away from at the next pass.
    """
    roll_back: MagicMock = create_autospec(DeploymentRoller, instance=True)
    roll_back.return_value = _a_rollback_descriptor_for(application)

    return roll_back


def _a_roller_that_cannot_reach_the_platform(failure: str) -> MagicMock:
    """Answers as the tier does when the platform was not there to be asked.

    `PlatformUnreachable` rather than a bare error, because that is what the
    transport raises when a tool's failure carries the marker - a case raising
    anything else would exercise a failure production cannot produce. Marked the
    way the tier marks it rather than with the token written out here, so this
    stays true if the token changes.
    """
    roll_back: MagicMock = create_autospec(DeploymentRoller, instance=True)
    roll_back.side_effect = PlatformUnreachable(
        an_unreachable_platform(DEPLOYMENT_PLATFORM, failure)
    )

    return roll_back


def _a_roller_that_cannot(failure: str) -> MagicMock:
    """Answers as the tier does when the rollback itself was refused.

    Unmarked, which is the whole of what it stands for: the same tier raises
    this and an unreachable platform, and only the one that means every action
    through the platform is unavailable carries that marker.
    """
    roll_back: MagicMock = create_autospec(DeploymentRoller, instance=True)
    roll_back.side_effect = McpToolError(failure)

    return roll_back


def _a_pinner_that_cannot_reach_the_platform(failure: str) -> MagicMock:
    """The pin's version of `_a_roller_that_cannot_reach_the_platform`."""
    pin: MagicMock = create_autospec(AutoscalerPinner, instance=True)
    pin.side_effect = PlatformUnreachable(
        an_unreachable_platform(DEPLOYMENT_PLATFORM, failure)
    )

    return pin


def _the_scale_out_asked_for(scale_out: MagicMock,
                             application: str) -> Assertion[Outcome]:
    def assertion(dont_care_outcome: Outcome) -> bool:
        asked = scale_out.call_args.args if scale_out.call_args else ()

        if asked != (application,):
            raise AssertionError(
                f"Expected a scale-out of [{application}] and nothing else, and "
                f"it asked for {asked}."
            )

        return True

    return assertion


def _it_carries_the_count_to_put_back(replicas: int) -> Assertion[Outcome]:
    def assertion(outcome: Outcome) -> bool:
        descriptor = outcome.undo_descriptor

        if not isinstance(descriptor, ReplicaUndo):
            raise AssertionError(
                f"Expected the outcome to carry the count a withdrawal would put "
                f"back, and it carried [{descriptor}]."
            )

        if descriptor.was_replicas != replicas:
            raise AssertionError(
                f"Expected the way back to name [{replicas}] replicas, and it "
                f"named [{descriptor.was_replicas}]."
            )

        return True

    return assertion


def _a_scale_out_of(application: str) -> ScaleOut:
    return ScaleOut(application=application)


def _a_replica_descriptor_for(
    application: str,
    was_replicas: int = SOME_COUNT_IT_WAS_RUNNING
) -> ReplicaUndo:
    return ReplicaUndo(
        application=application,
        was_replicas=was_replicas,
        was_syncing_itself=True
    )


def _a_scaler_returning(application: str) -> MagicMock:
    """Answers as the real scaler does - with the descriptor recording both
    things it changed.

    Both, because making a deployment larger means suspending the platform's own
    reconciliation first: it would otherwise put the count back to whatever the
    repository holds at its next sync, which is the size that was too small.
    """
    scale_out: MagicMock = create_autospec(DeploymentScaler, instance=True)
    scale_out.return_value = _a_replica_descriptor_for(application)

    return scale_out


def _a_scaler_that_cannot(failure: str) -> MagicMock:
    scale_out: MagicMock = create_autospec(DeploymentScaler, instance=True)
    scale_out.side_effect = RuntimeError(failure)

    return scale_out


def _an_undo_that_puts_the_count_back(application: str) -> MagicMock:
    undo: MagicMock = create_autospec(UndoChange, instance=True)
    undo.return_value = UndoAttempt(
        subject=application,
        outcome=Undone.RESTORED,
        detail=f"[{application}] was put back to its size and its sync policy"
    )

    return undo


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


def _a_pin_of(application: str) -> PinAutoscaler:
    return PinAutoscaler(application=application)


def _a_pinner_with_no_room_left(refusal: str) -> MagicMock:
    """Answers as the tier does when there is nothing left to hold still.

    `ActionExhausted` rather than a bare error, because that is what the transport
    raises when a tool's refusal carries the marker - a case raising anything else
    would be exercising a failure production cannot produce. Marked the way the
    tier marks it rather than with the token written out here, so this stays true
    if the token changes.
    """
    pin: MagicMock = create_autospec(AutoscalerPinner, instance=True)
    pin.side_effect = ActionExhausted(an_exhausted_action(refusal))

    return pin


def _a_pinner_that_cannot(failure: str) -> MagicMock:
    """Answers as the tier does when the patch itself was refused.

    Unmarked, which is the whole of what it stands for: the same tier raises both,
    and only the refusal that changed nothing carries the marker. This one can fire
    after reconciliation was already suspended, so nobody can say what state the
    estate is in.
    """
    pin: MagicMock = create_autospec(AutoscalerPinner, instance=True)
    pin.side_effect = McpToolError(failure)

    return pin


def _a_pinner_holding_it_at(application: str, floor_asked_for: int) -> MagicMock:
    """Answers as the tier does when the pin went through.

    Both floors on the descriptor, because both are what the tier knew: the one the
    controller had, and the one it was actually asked for - which is the smaller of
    the declared ceiling and Argus's own cap, and so is not reconstructible from
    either.
    """
    pin: MagicMock = create_autospec(AutoscalerPinner, instance=True)
    pin.return_value = AutoscalerUndo(
        application=application,
        was_min_replicas=SOME_FLOOR_IT_COULD_FALL_TO,
        min_replicas_asked_for=floor_asked_for,
        was_syncing_itself=True
    )

    return pin


def _a_roller_that_lost_the_platform_mid_action(failure: str) -> MagicMock:
    """The platform went after reconciliation was suspended.

    The half of the rollback that changed something. What it left behind is one
    boolean, this tier put it there, and the descriptor that puts it back travels
    on the failure - so the caller is told both that the platform is gone and
    that an application is sitting un-reconciled.
    """
    roll_back: MagicMock = create_autospec(DeploymentRoller, instance=True)
    roll_back.side_effect = PlatformUnreachable(
        an_unreachable_platform(
            DEPLOYMENT_PLATFORM, failure, undo_descriptor=WHAT_THE_ROLLBACK_LEFT
        ),
        WHAT_THE_ROLLBACK_LEFT
    )

    return roll_back


def _it_carries_back(expected: UndoDescriptor) -> Assertion[Outcome]:
    def assertion(outcome: Outcome) -> bool:
        if outcome.undo_descriptor != expected:
            raise AssertionError(
                f"Expected the outcome to carry {expected!r} as what has to be "
                f"put back, it carried {outcome.undo_descriptor!r}."
            )

        return True

    return assertion


def _a_read_that_fails_once_then_answers(
    window: list[MetricBucket]
) -> Callable[[], list[MetricBucket]]:
    """A metrics read that raises the first time and answers after.

    The real failure this stands for is a read tier whose tool executed and
    timed out - `McpToolError`, not a refused connection, which is the one the
    transport already retries. Raised as that type rather than a bare
    `Exception` so the test fails if the loop is narrowed to catch something
    else and this stops being the shape that reaches it.
    """
    answered = False

    def read() -> list[MetricBucket]:
        nonlocal answered

        if answered:
            return window

        answered = True
        raise McpToolError(
            "MCP tool call [get_metrics_summary] failed: timed out"
        )

    return read


def _the_unanswered_read_was_said(published: list[IncidentEvent],
                                  minute: str) -> Assertion[Outcome]:
    """One line saying the shop could not be read, for the minute being judged.

    The minute is the point of it. "A read failed" is a fact about Argus's
    plumbing; "the shop could not be read for the minute this action is being
    judged on" is a fact about the verdict, and it is the second that tells a
    person why a confirmation took longer than the window it was measured over.

    Exactly one, because the pass that failed is one pass. A loop that said it
    every pass after the first would report a single unreadable minute as a
    service nobody could read at all.
    """
    def assertion(_outcome: Outcome) -> bool:
        said = [
            event for event in published
            if isinstance(event, RetrievalUnanswered)
        ]

        if len(said) != 1:
            raise AssertionError(
                f"Expected one line about a read that went unanswered, and "
                f"{len(said)} were published - so either the failed pass is "
                f"invisible, or every later pass is repeating it."
            )

        if said[0].minute != minute:
            raise AssertionError(
                f"Expected the unanswered read to name minute [{minute}], the "
                f"one this action is being judged on, and it names "
                f"[{said[0].minute}]."
            )

        return True

    return assertion


def _a_read_that_never_answers() -> Callable[[], list[MetricBucket]]:
    """A metrics read that fails every time it is asked.

    The shape of the failure, and what makes it a different case from the one
    above: a read tier under the load the polling itself creates does not
    recover between passes, so a window bought to measure recovery can run out
    with not one reading in it.
    """
    def read() -> list[MetricBucket]:
        raise McpToolError("MCP tool call [get_metrics_summary] failed: timed out")

    return read


def _nothing_was_put_back_through(undo: MagicMock) -> Assertion[Outcome]:
    """The change left exactly where the action put it.

    The half of this that costs something. `REFUTED` puts the change back, and a
    mitigation whose every read failed is the one most likely to have worked -
    both times this was seen against the real stack the shop had in fact
    recovered - so refuting it here would restore the fault to a service that was
    well again, and call the grounds for doing so a measurement.
    """
    def assertion(_outcome: Outcome) -> bool:
        if undo.call_count != 0:
            raise AssertionError(
                f"Expected nothing to be put back where nothing was measured, "
                f"and the undo was called [{undo.call_count}] times."
            )

        return True

    return assertion


def _it_says_nothing_was_measured() -> Assertion[Outcome]:
    """The outcome carrying the one fact its verdict cannot.

    `ESCALATED` arrives from two opposite places. One is a refutation whose undo
    could not be established - the service *was* watched, and a candidate that
    stopped being marked tested there would lose a real experiment. The other is
    this: an action taken and never looked at. The verdict is the same word for
    both, so the thing a candidate's row has to be decided on is said beside it
    rather than read out of it.
    """
    def assertion(outcome: Outcome) -> bool:
        if outcome.measured:
            raise AssertionError(
                "Expected the outcome to say nothing was measured, and it "
                "claims the service was watched - so the candidate will be "
                "marked tested by an experiment that took no reading."
            )

        return True

    return assertion
