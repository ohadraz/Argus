from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation import Outcome, UndoAttempt, Undone, Verdict, take_action
from agent_mitigation.tools import (
    AcceleratorPinner,
    Arrival,
    AutoscalerPinner,
    CacheEntryDiscarder,
    DeploymentRoller,
    DeploymentScaler,
    FlagSetter,
    MetricsFetcher,
    MitigationSettings,
    RuleReader,
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
    AcceleratorPinUndo,
    AlertRuleStanding,
    AutoscalerUndo,
    DeploymentRollbackUndo,
    DiscardCacheEntries,
    MetricBucket,
    PinAutoscaler,
    PinToAccelerator,
    ReplicaUndo,
    RestartedService,
    RollBackDeployment,
    ScaleOut,
    UndoDescriptor,
)
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    calling,
    dont_care_sleep,
    one_record_was_logged,
)

from agent_mitigation_test.framework.assertions import the_verdict_is
from agent_mitigation_test.framework.builders import (
    ACTION_TIME,
    CALM_MINUTES,
    CALM_RATE,
    DONT_CARE_FLAG,
    FAILING_MINUTES,
    FAILING_RATE,
    THE_ONSET,
    a_clock_frozen_at,
    a_clock_reading_at,
    a_clock_that_runs_out_after_one_look,
    a_discard_removing,
    a_recovered_window,
    a_still_failing_window,
    a_window_ending_at_the_action,
    a_window_of_minutes,
    a_window_recovered_before_the_action,
    a_window_that_keeps_flapping,
    a_window_that_never_departed,
    a_window_that_stops_at_the_onset,
    a_window_where_memory_never_fell,
    a_window_where_memory_was_reclaimed,
    a_window_whose_readings_return_at,
    an_action_restarting,
    an_action_setting,
    an_undo_descriptor_for,
    an_undo_nobody_calls,
    an_undo_putting_flags_back,
    an_undo_that_put_it_back,
    metrics_reading,
    nobody_can_say,
    nobody_changed_it,
    nobody_wanted_it_before_it_was_taken,
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
# Where the store this tier writes to answers. A URL rather than a service name,
# because that is the only address the write tier has: it dials a store, and a
# service name passed down just to word a refusal would be the agent's
# vocabulary leaking into the tier.
SOME_CACHE_ENDPOINT = "redis://localhost:6379"
THE_ENTRIES_ARE_ALREADY_GONE = (
    f"none of the [1] entries named at [{SOME_CACHE_ENDPOINT}] are in the "
    f"store, so there is nothing here for a discard to remove"
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

# The card a pin holds the deployment to, and one somebody else had held it to
# before - the case where letting go is putting a pin back rather than removing
# one.
THE_FLEETS_CARD = "Tesla-V100-SXM2-16GB"
A_CARD_SOMEBODY_ELSE_CHOSE = "Tesla-T4"
# The tier's refusal for a deployment already held to the card, in its words.
THE_DEPLOYMENT_IS_ALREADY_THERE = (
    f"[{SOME_APPLICATION}] is already held to [{THE_FLEETS_CARD}], so there is "
    f"nothing here for a pin to move"
)

# How long the verification waits. Short, because every test here would
# otherwise sit through it - the clock and the sleeper are injected, so what
# this bounds is the arithmetic rather than any real wait.
A_SHORT_WAIT_IN_SECONDS = 180.0

# The rule that paged, for an alert about a series. What an action on one is
# judged by: the rule defines what "acceptable" is for the service, as it would
# for a responder - so whether the rule stopped firing is the verdict, and the
# metrics are read only to date the recovery.
SOME_RULE = "some-rule"


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
        .then(all_of(
            the_verdict_is(Verdict.WITHDRAWN),
            _the_detail_mentions("a person ended the incident"),
            _the_detail_does_not_mention("withdrawn")
        ))


@pytest.mark.unit
def test_an_action_withdrawn_before_it_was_taken_is_never_taken() -> None:
    # Withdrawn between the walk choosing the action and applying it. Applying
    # it anyway would be Argus changing the world after a person said stop, and
    # leaving behind a change the withdrawal would then have to put back.
    Scenario() \
        .given(
            some_old_state := False,
            set_state := _a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=some_old_state)
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(set_state=set_state),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                still_wanted=nobody_wanted_it_before_it_was_taken(),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.WITHDRAWN),
            _the_flag_was_never_set(set_state),
            _it_carries_nothing_to_put_back(),
            # The agent holds a yes-or-no and cannot tell a withdrawal from a
            # resolution, so it says what it knows and claims neither.
            _the_detail_mentions("a person ended the incident"),
            _the_detail_does_not_mention("withdrawn")
        ))


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
def test_the_wait_is_announced_before_a_verdict_is_reached() -> None:
    # Production is in its new state by this point and nothing further is
    # decided until a whole minute has passed and been judged. A page that said
    # nothing until the verdict arrived would leave a reader unable to tell a
    # slow verification from a stuck one. Said on the first reading, which is
    # the earliest the figure it carries is known - the other side of that is
    # `test_the_wait_is_announced_once_the_service_has_been_read`.
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
def test_a_change_the_platform_stopped_applying_reaches_no_verdict() -> None:
    # The other way no verdict is reached, and it is not the one above. There the
    # service could not be read; here it was readable throughout and the *change*
    # never landed - a rolling update the platform is holding, so the revision the
    # action asked for never reached a replica.
    #
    # Why that is not a refutation. Every minute since the action is a minute the
    # old code was serving, so nothing about this hypothesis was tested at all.
    # `REFUTED` would mark it tested, put the change back and strike the
    # explanation off, which is three wrong things done on no measurement - and
    # the explanation may well have been right, since it never had its chance.
    #
    # Why it does not wait for the window to run out either. Nothing is going to
    # change: the platform has stopped converging this deployment, which is a
    # state it reports rather than a duration anybody has to judge. Polling to the
    # deadline would spend the whole verification window learning what the first
    # look already said.
    #
    # The change stays where the action left it, carrying what would put it back,
    # exactly as the unread-service escalation does and for the same reason -
    # nobody knows whether it helped, so the decision is a person's.
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
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                arrivals=lambda _action: _a_platform_that_has_stopped_applying_it(),
                undo=undo
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.ESCALATED),
            _it_says_nothing_was_measured(),
            _the_detail_mentions("never applied"),
            _nothing_was_put_back_through(undo),
            _the_undo_carried_is(an_undo_descriptor_for(some_flag, was_enabled=some_old_state))
        ))


@pytest.mark.unit
def test_a_change_still_arriving_is_not_judged_until_it_has() -> None:
    # The wait this introduces, and the reason the escalation above is reachable
    # at all. A rollback is accepted long before every replica is running the
    # revision it returned to, so the minutes in between describe the code being
    # replaced - and a verdict read off them is a verdict about the wrong
    # deployment, which is how a mitigation that worked gets refuted.
    #
    # So nothing is judged while the change is still arriving: no look is
    # published, and the recovered window below is not consulted until the
    # platform says every replica has it. The clock is frozen, so what is being
    # claimed here is the ordering and not any duration.
    #
    # Two passes of still-arriving rather than one, because one would be satisfied
    # by a loop that happened to check arrival before its first read and never
    # again.
    Scenario() \
        .given(
            published := _a_page_listening(),
            some_old_state := False
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
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                arrivals=lambda _action: _a_platform_that_takes_two_passes_to_apply_it(),
                incident_id=_SOME_INCIDENT_ID,
                publisher=published.append,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_looks_published_number(published, 1)
        ))


@pytest.mark.unit
def test_the_wait_lasts_as_long_as_the_recovery_it_waits_for_must_hold() -> None:
    # How long to watch was the one figure in the recovery path that was picked
    # rather than measured, and a constant is wrong in the direction that costs
    # most: a service failing one minute in five has to hold five clear minutes
    # before anybody may say it recovered, and three minutes of watching cannot
    # see them. The wait ran out first every time, so the verdict was reached
    # before the evidence that would decide it could exist.
    #
    # So the wait ends where the rule it is waiting on says it may: the moment
    # the last minute a recovery could be shown in has finished. This window's
    # rhythm asks for five clear minutes from 11:11, which ends at 11:16, where
    # the configured three minutes ended at 11:13:30.
    #
    # The claim is the second look. Its reading is taken at 11:14 - past the
    # constant, inside what the rhythm asks for - and a wait still bounded by the
    # setting would have refuted before taking it. The service never does
    # recover, so the verdict is the same word either way; what changed is when
    # it was reached, which is the whole of the defect.
    Scenario() \
        .given(
            published := _a_page_listening(),
            the_service_keeps_flapping := a_window_that_keeps_flapping(),
            past_the_configured_wait := A_SHORT_WAIT_IN_SECONDS + 30,
            past_the_wait_its_rhythm_asks_for := A_SHORT_WAIT_IN_SECONDS * 4,
            # 11:10:30 to 11:11 is thirty seconds, and the five clear minutes
            # this window asks for end at 11:16.
            the_wait_the_flap_earns := 30 + 5 * 60
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                incident_id=_SOME_INCIDENT_ID,
                publisher=published.append,
                writes=the_writes(
                    set_state=(set_state := _a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=True
                    ))
                ),
                fetch_metrics=metrics_reading(the_service_keeps_flapping),
                now=a_clock_reading_at(
                    ACTION_TIME,
                    past_the_configured_wait,
                    past_the_wait_its_rhythm_asks_for
                ),
                sleep=dont_care_sleep,
                undo=an_undo_putting_flags_back(set_state, nobody_changed_it())
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.REFUTED),
            _the_looks_published_number(published, 2),
            _the_wait_allowed(published, the_wait_the_flap_earns)
        ))


@pytest.mark.unit
def test_an_incident_with_no_rhythm_is_given_the_one_clear_minute_it_needs() -> None:
    # The same derivation in the other direction, and the one nearly every
    # incident takes: a departure that persisted and was acted on asks for a
    # single clear minute, so the wait ends when that minute has finished -
    # ninety seconds from an action at 11:10:30, where the constant said a
    # hundred and eighty.
    #
    # Worth a test of its own because it is the half that pays for itself. Every
    # refuted candidate in every walk waited out the whole constant, and the
    # ordinary case is now bounded by the minute the verdict is read off rather
    # than by a figure sized for the worst case anybody imagined.
    Scenario() \
        .given(
            published := _a_page_listening(),
            the_service_never_recovers := a_still_failing_window(),
            # 11:10:30 to 11:11 is thirty seconds, and the one clear minute this
            # window asks for ends at 11:12.
            the_wait_a_step_incident_earns := 30 + 60
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                incident_id=_SOME_INCIDENT_ID,
                publisher=published.append,
                writes=the_writes(
                    set_state=(set_state := _a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=True
                    ))
                ),
                fetch_metrics=metrics_reading(the_service_never_recovers),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_putting_flags_back(set_state, nobody_changed_it())
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.REFUTED),
            _the_wait_allowed(published, the_wait_a_step_incident_earns)
        ))


@pytest.mark.unit
def test_a_source_that_reports_a_minute_late_is_waited_for_a_minute_longer() -> None:
    # A source that reports a minute only once it has ended - Prometheus, read
    # at the end of each minute - hands over the minute a recovery shows in a
    # minute after it happened. A wait ending as that minute ends would end
    # before the reading that decides it could arrive, and refute the action
    # that worked: which is what the first run against such a source did to a
    # rollback. So the wait allows the lag on top of what the recovery needs.
    Scenario() \
        .given(
            published := _a_page_listening(),
            the_service_never_recovers := a_still_failing_window(),
            a_source_a_minute_late := 1,
            # 11:10:30 to 11:11 is thirty seconds, the one clear minute ends at
            # 11:12, and its reading arrives a minute after that.
            the_wait_a_late_reading_earns := 30 + 60 + 60
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(reporting_lag_minutes=a_source_a_minute_late),
                thresholds=_some_thresholds(),
                incident_id=_SOME_INCIDENT_ID,
                publisher=published.append,
                writes=the_writes(
                    set_state=(set_state := _a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=True
                    ))
                ),
                fetch_metrics=metrics_reading(the_service_never_recovers),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_putting_flags_back(set_state, nobody_changed_it())
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.REFUTED),
            _the_wait_allowed(published, the_wait_a_late_reading_earns)
        ))


@pytest.mark.unit
def test_the_minute_a_verdict_is_read_from_follows_the_change_arriving() -> None:
    # Which minute the verdict is read off is the action's own question, and the
    # action is not in force when the tier acknowledges it. A rollback is
    # accepted long before every replica carries the revision, so the minute
    # after the *acknowledgement* can be a minute the old code was serving -
    # which is the wrong deployment, judged.
    #
    # So the minute is taken from the arrival rather than from the call. The
    # change lands here at 11:11:10, ten seconds into the minute after the
    # action's own, and the first minute it was wholly in force for is therefore
    # 11:12 - one minute later than the acknowledgement would have said.
    Scenario() \
        .given(
            published := _a_page_listening(),
            the_change_lands_in_the_minute_after := 40
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                incident_id=_SOME_INCIDENT_ID,
                publisher=published.append,
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=True
                    )
                ),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_reading_at(
                    ACTION_TIME, the_change_lands_in_the_minute_after
                ),
                sleep=dont_care_sleep,
                arrivals=lambda _action: _a_platform_that_takes_two_passes_to_apply_it(),
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_wait_will_judge_from(published, "2026-08-20T11:12:00Z")
        ))


@pytest.mark.unit
def test_the_wait_is_announced_once_the_service_has_been_read() -> None:
    # The figure the announcement carries is measured off the service's own
    # window, so it cannot be said before the window has been read: said first
    # it is a guess, and the page would carry a number the wait does not keep.
    #
    # A wait whose reads never answer therefore announces nothing, and that is
    # the shape this asserts because it is the only one where the ordering shows.
    # The page does not go quiet: the unanswered reads are said instead, each one
    # a line, which is what the announcement was there to prevent. An
    # announcement with no reading behind it would be the one line on the page
    # nothing measured.
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
                publisher=published.append,
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=True
                    )
                ),
                fetch_metrics=_a_read_that_never_answers(),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.ESCALATED),
            _the_wait_was_announced(published, times=0)
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
def test_a_service_that_came_back_before_the_action_is_recorded_at_that_minute() -> None:
    # The minute recorded is a fact about the service, so it is neither the
    # minute Argus acted in nor the minute it stopped watching. Here the shop
    # came back at 11:08 on its own and the action followed at 11:10:30, so a
    # record reading 11:11 would credit the action with a recovery that preceded
    # it - the false attribution nothing in the account can show today.
    the_minute_it_came_back = "2026-08-20T11:08:00Z"

    Scenario() \
        .given(
            published := _a_page_listening()
        ) \
        .when(
            lambda: _an_action_is_taken(
                publisher=published.append,
                metrics=a_window_recovered_before_the_action()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_recovery_was_recorded_at(published, the_minute_it_came_back)
        ))


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
    # the action asked for. Five of the seven generic mitigations reach the estate
    # through this platform, so a platform that is not answering has taken five
    # away at once - and what the walk does about that is pass over the other
    # four and reach for whatever acts through something else.
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


@pytest.mark.unit
def test_taking_a_pin_to_a_card_asks_the_platform_for_that_card() -> None:
    # The caller names the card as well as the application. Which card was worked
    # out from where the replicas started before the onset, which the tier never
    # saw - so a pin that arrived without it would be the tier guessing.
    Scenario() \
        .given(pin_to_accelerator := _a_card_pinner_moving(was_pinned_to=None)) \
        .when(
            lambda: take_action(
                _a_pin_to(THE_FLEETS_CARD),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(pin_to_accelerator=pin_to_accelerator),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            _the_card_pin_asked_for(pin_to_accelerator, SOME_APPLICATION, THE_FLEETS_CARD)
        )


@pytest.mark.unit
def test_a_confirmed_pin_to_a_card_says_which_card_and_what_it_replaced() -> None:
    # Both ends, because an account of a pin is a transition. "Held to the V100"
    # alone reads as though the pods had been held to something else; what it
    # replaced is what a withdrawal puts back.
    Scenario() \
        .given(the_answers_came_back := a_recovered_window()) \
        .when(
            lambda: take_action(
                _a_pin_to(THE_FLEETS_CARD),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(
                    pin_to_accelerator=_a_card_pinner_moving(was_pinned_to=None)
                ),
                fetch_metrics=metrics_reading(the_answers_came_back),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_detail_mentions(f"[{SOME_APPLICATION}]'s pods to [{THE_FLEETS_CARD}]"),
            _the_detail_mentions("no card")
        ))


@pytest.mark.unit
def test_a_confirmed_pin_over_another_card_names_the_card_it_replaced() -> None:
    # The other end of the transition, where somebody had already held the pods
    # to a card. Named rather than said as "a card", because that card is what a
    # withdrawal holds them to again.
    Scenario() \
        .given(the_answers_came_back := a_recovered_window()) \
        .when(
            lambda: take_action(
                _a_pin_to(THE_FLEETS_CARD),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(
                    pin_to_accelerator=_a_card_pinner_moving(
                        was_pinned_to=A_CARD_SOMEBODY_ELSE_CHOSE
                    )
                ),
                fetch_metrics=metrics_reading(the_answers_came_back),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_detail_mentions(f"[{A_CARD_SOMEBODY_ELSE_CHOSE}]")
        ))


@pytest.mark.unit
def test_a_deployment_already_held_to_the_card_is_not_attempted_rather_than_escalated() -> None:
    # Nothing to move, nothing changed, and the walk has other candidates - the
    # autoscaler pin's case, for the other pin.
    Scenario() \
        .given(
            the_deployment_is_already_there := _a_card_pinner_with_nothing_to_move(
                THE_DEPLOYMENT_IS_ALREADY_THERE
            )
        ) \
        .when(
            lambda: take_action(
                _a_pin_to(THE_FLEETS_CARD),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(pin_to_accelerator=the_deployment_is_already_there),
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
                f"hold [{SOME_APPLICATION}]'s pods to [{THE_FLEETS_CARD}]"
            ),
            _the_detail_mentions(THE_DEPLOYMENT_IS_ALREADY_THERE),
            _the_detail_does_not_mention(EXHAUSTED_ACTION_MARKER),
            _there_is_nothing_to_put_back()
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("was_pinned_to", "put_back_as"),
    [
        (None, "any card"),
        (A_CARD_SOMEBODY_ELSE_CHOSE, f"[{A_CARD_SOMEBODY_ELSE_CHOSE}]")
    ],
    ids=["held-to-no-card-before", "held-to-another-card-before"]
)
def test_a_refuted_pin_to_a_card_says_what_it_was_put_back_to(
    was_pinned_to: str | None, put_back_as: str
) -> None:
    # Two different endings and both have to be said. A deployment held to no
    # card before is let go, and its pods may land anywhere again; one somebody
    # else had held to a card is held to that card again - which a sentence
    # saying "let go" would misreport as a pin removed.
    Scenario() \
        .given(undo := an_undo_that_put_it_back(SOME_APPLICATION)) \
        .when(
            lambda: take_action(
                _a_pin_to(THE_FLEETS_CARD),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(
                    pin_to_accelerator=_a_card_pinner_moving(was_pinned_to=was_pinned_to)
                ),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=undo
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.REFUTED),
            _the_detail_mentions(put_back_as)
        ))


@pytest.mark.unit
def test_a_service_nobody_could_see_is_refuted_when_the_readings_never_return() -> None:
    # Nothing was seen between the onset and the action, and nothing is seen after
    # it either. The action did not restore the sight, which is what it was for, so
    # it is refuted on a measurement rather than on silence: the window was read
    # every pass and carried no minute of the incident at all.
    Scenario() \
        .given(
            some_old_state := False,
            the_readings_never_come_back := a_window_that_stops_at_the_onset()
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                onset=THE_ONSET,
                writes=the_writes(
                    set_state=(set_state := _a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=some_old_state
                    ))
                ),
                fetch_metrics=metrics_reading(the_readings_never_come_back),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_putting_flags_back(set_state, nobody_changed_it())
            )
        ) \
        .then(
            the_verdict_is(Verdict.REFUTED)
        )


@pytest.mark.unit
def test_a_blind_spot_is_not_refuted_before_the_readings_have_had_a_chance() -> None:
    # The first pass of every blind spot, and the one the suite never covered.
    # The minute a verdict is read from is the minute *after* the change arrived,
    # and on the first look that minute has not finished - so the rule that
    # confirms a restored sight cannot answer yet, whatever the action achieved.
    #
    # What must not happen is that the wait settles anyway. A departure is a fact
    # about levels, and this window has none to be about: its minutes are absent
    # rather than calm, which is the whole of what the mode is. Refuting here
    # undoes the revert, blinds the shop again, and strikes off the one cause
    # that was right - on the strength of a window that could not have shown
    # anything yet.
    #
    # Asserted three ways, because the verdict alone would not say which rule
    # reached it. The service is looked at twice, so the loop went round rather
    # than settling; the detail names the sight returning; and it does not name
    # the departure rule, which is the one that must not have decided this.
    Scenario() \
        .given(
            some_old_state := False,
            the_readings_come_back_late := (
                _metrics_whose_readings_return_on_the_second_look()
            )
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                onset=THE_ONSET,
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=some_old_state
                    )
                ),
                fetch_metrics=the_readings_come_back_late,
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_that_put_it_back(DONT_CARE_FLAG)
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_service_was_looked_at(the_readings_come_back_late, times=2),
            _the_detail_mentions("could be read again"),
            _the_detail_does_not_mention("never departed")
        ))


@pytest.mark.unit
def test_the_minute_the_action_fell_inside_is_not_evidence_the_sight_was_there() -> None:
    # Whether this incident's own minutes were ever published is measured over
    # the span from the onset to the action, and this is the case that says where
    # the span ends. The rollback restores the reporting, so the minute it landed
    # in is the first to carry a row again - and that row exists *because* the
    # action worked. Counted as evidence the sight was never absent, it overturns
    # the measurement with the action's own effect and the incident is then judged
    # on levels it does not have.
    #
    # Asserted as which rule answered rather than as the verdict alone, because
    # the verdict here is reachable two ways: the rows come back calm, so a window
    # read a minute later would also confirm on levels. A case that asserted
    # `CONFIRMED` and nothing else would go green down that road while the span
    # was still measured wrongly, which is how this survived an e2e suite.
    Scenario() \
        .given(
            some_old_state := False,
            the_rows_return_as_the_action_lands := (
                _metrics_whose_rows_return_in_the_actions_own_minute()
            )
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                onset=THE_ONSET,
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=some_old_state
                    )
                ),
                fetch_metrics=the_rows_return_as_the_action_lands,
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_that_put_it_back(DONT_CARE_FLAG)
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_service_was_looked_at(the_rows_return_as_the_action_lands, times=2),
            _the_detail_mentions("could be read again"),
            _the_detail_does_not_mention("never departed"),
            _the_detail_does_not_mention("returned to baseline")
        ))


@pytest.mark.unit
def test_readings_returning_confirms_the_action_that_restored_them() -> None:
    # The sight came back, which is the whole of what the action was for. Confirmed
    # on the minutes existing rather than on their levels - they happen to be calm
    # here, and the next case is the one that proves the levels are not what
    # decided it.
    Scenario() \
        .given(
            some_old_state := False,
            the_readings_come_back := a_window_whose_readings_return_at(CALM_RATE)
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                onset=THE_ONSET,
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=some_old_state
                    )
                ),
                fetch_metrics=metrics_reading(the_readings_come_back),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            the_verdict_is(Verdict.CONFIRMED)
        )


@pytest.mark.unit
def test_readings_that_return_unwell_still_confirm_the_sight_was_restored() -> None:
    # The case the levels rule gets wrong. The minutes came back departed - the
    # shop is unwell for some reason nobody could have seen until now, because
    # until now nobody could see anything. Judged on levels this refutes, which
    # undoes the revert, blinds the shop again, and strikes off the one cause that
    # was right. What was mitigated was the blindness, and the blindness is over.
    Scenario() \
        .given(
            some_old_state := False,
            the_readings_come_back_bad := a_window_whose_readings_return_at(
                FAILING_RATE
            )
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                onset=THE_ONSET,
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(
                        DONT_CARE_FLAG, was_enabled=some_old_state
                    )
                ),
                fetch_metrics=metrics_reading(the_readings_come_back_bad),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            the_verdict_is(Verdict.CONFIRMED)
        )


@pytest.mark.unit
def test_an_onset_whose_minutes_were_all_read_is_judged_on_the_levels_as_before() -> None:
    # The guard that keeps the rule vacuous everywhere else. An incident may carry
    # a stated onset and still have been watched throughout - silent data
    # corruption is exactly that, a window with every minute present and flat - and
    # such an incident is judged on its levels as it always was. What selects the
    # new rule is the minutes being missing, never the onset being stated.
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
                onset=THE_ONSET,
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


def _a_platform_that_has_stopped_applying_it() -> Callable[[], Arrival]:
    """A platform reporting, every time it is asked, that it is not converging
    this change.

    Every time rather than once, because the claim is that the loop stops on the
    answer rather than that it happened to be asked at the right moment.
    """
    return lambda: Arrival.WILL_NOT_ARRIVE


def _a_platform_that_takes_two_passes_to_apply_it() -> Callable[[], Arrival]:
    """Still arriving, still arriving, then arrived - and arrived from then on."""
    answers = iter([Arrival.STILL_ARRIVING, Arrival.STILL_ARRIVING])

    return lambda: next(answers, Arrival.ARRIVED)


def _the_looks_published_number(published: list[IncidentEvent],
                                expected: int) -> Assertion[Outcome]:
    """That exactly this many looks at the service were published.

    The ordering assertion, counted rather than inspected: a loop that judged
    while the change was still arriving would publish a look per pass, so the
    count is what says the passes before arrival took none.
    """
    def assertion(_outcome: Outcome) -> bool:
        looks = [event for event in published if isinstance(event, RecoveryChecked)]
        if len(looks) != expected:
            raise AssertionError(
                f"Expected [{expected}] looks at the service, got [{len(looks)}]."
            )

        return True

    return assertion


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
        undo=an_undo_that_put_it_back(DONT_CARE_FLAG),
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


def _metrics_whose_rows_return_in_the_actions_own_minute() -> MagicMock:
    """The one window the existing blind-spot cases cannot express.

    `a_window_whose_readings_return_at` restores its rows at the first whole
    minute and the one after it, so the minute the action fell inside stays
    absent and the span that measures whether anything was ever seen never
    contains it. Here it does: the rollback lands mid-minute and that minute is
    the first to carry a row again, which is what actually happens when the thing
    being restored is the reporting itself.

    Two looks, because the first cannot settle anything. A row in the action's own
    minute is aggregated over seconds either side of the change, so it is evidence
    about neither state and the wait has to go round again - and the second look
    is where the first whole minute finally exists.
    """
    the_blind_minutes = {minute: CALM_RATE for minute in range(CALM_MINUTES)}
    # Offsets rather than instants, and these two are the whole of the case. 10 is
    # the minute `ACTION_TIME` falls inside, 11 is the first that wholly follows
    # it. Derived from the window's own shape so they move with it.
    acted_in = CALM_MINUTES + FAILING_MINUTES - 1
    first_whole = acted_in + 1

    fetch_metrics: MagicMock = create_autospec(MetricsFetcher, instance=True)
    fetch_metrics.side_effect = [
        a_window_of_minutes(the_blind_minutes | {acted_in: CALM_RATE}),
        a_window_of_minutes(
            the_blind_minutes | {acted_in: CALM_RATE, first_whole: CALM_RATE}
        )
    ]

    return fetch_metrics


def _metrics_recovering_only_after_the_action() -> MagicMock:
    """The first look ends at the action, so no whole minute has followed it
    yet; the second carries one, and only then can a verdict be read."""
    fetch_metrics: MagicMock = create_autospec(MetricsFetcher, instance=True)
    fetch_metrics.side_effect = [a_window_ending_at_the_action(), a_recovered_window()]

    return fetch_metrics


def _metrics_whose_readings_return_on_the_second_look() -> MagicMock:
    """A blind spot on its first pass, and the rows back on its second.

    The first look carries nothing from the onset onwards, the action included,
    so the minute a verdict would be read from does not exist yet - which is
    every blind spot's first pass and not an edge of one. The second carries the
    minutes that returned.

    Two looks rather than one, because what the case is about is the pass in
    between: the wait has to still be waiting after the first. A single-window
    reader cannot tell a loop that kept watching from one that settled, since
    both would answer the same thing however many times they were asked.
    """
    fetch_metrics: MagicMock = create_autospec(MetricsFetcher, instance=True)
    fetch_metrics.side_effect = [
        a_window_that_stops_at_the_onset(),
        a_window_whose_readings_return_at(CALM_RATE)
    ]

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


@pytest.mark.unit
def test_a_discard_reports_the_count_the_store_gave_back() -> None:
    # The figure is the store's, and that is the whole reason this action can be
    # judged by its own answer. Three keys were named and the store found two of
    # them: an entry something else had already discarded is an entry absent,
    # which is what the incident needed - so two is honest and three would be a
    # number Argus made up about a world it had not looked at.
    #
    # Bracketed, as every figure a detail quotes is, so the assertion cannot be
    # satisfied by a digit that happens to fall in some other part of the line.
    some_keys = (
        "io-shop:summary:shopper-3",
        "io-shop:summary:shopper-7",
        "io-shop:summary:shopper-9"
    )

    Scenario() \
        .given(
            the_store_found_two_of_them := a_discard_removing(2)
        ) \
        .when(
            lambda: take_action(
                _a_discard_of(SOME_APPLICATION, some_keys),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(discard=the_store_found_two_of_them),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            _the_detail_mentions("[2]"),
            _the_detail_does_not_mention("[3]")
        ))


@pytest.mark.unit
def test_a_discard_leaves_nothing_to_put_back() -> None:
    # The only action here that changes something persistent and still owes no
    # undo, and the distinction is worth pinning because the other two silences
    # mean different things. A restart records no descriptor because it changed
    # nothing to record; a rollback records one because what it replaced is
    # worth restoring. This changed something and there is nothing to restore:
    # the entries were a copy of records it never touched, so writing the old
    # figures back would be recreating the incident.
    Scenario() \
        .given(
            the_store_found_them_all := a_discard_removing(1)
        ) \
        .when(
            lambda: take_action(
                _a_discard_of(SOME_APPLICATION, ("io-shop:summary:shopper-3",)),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(discard=the_store_found_them_all),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            _there_is_nothing_to_put_back()
        )


@pytest.mark.unit
def test_a_discard_argus_declines_to_repeat_is_named_as_a_discard() -> None:
    # What the walk says it would have done, for an action it will not take
    # again. Said as discarding stale cached figures rather than as deleting or
    # clearing anything: what is removed is a copy, the records behind it are
    # untouched, and a verb suggesting otherwise would describe an action a
    # reader should be alarmed by.
    Scenario() \
        .given(
            nothing_is_left_to_remove := _a_discarder_with_nothing_left_to_remove(
                THE_ENTRIES_ARE_ALREADY_GONE
            )
        ) \
        .when(
            lambda: take_action(
                _a_discard_of(SOME_APPLICATION, ("io-shop:summary:shopper-3",)),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(discard=nothing_is_left_to_remove),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            _the_detail_mentions(
                f"discard [{SOME_APPLICATION}]'s stale cached figures"
            )
        )


@pytest.mark.unit
def test_a_discard_is_confirmed_by_its_receipt_where_no_series_ever_moved() -> None:
    # The third way an attempt is settled, and the only one available here. No
    # series departed, so there is nothing to have recovered from and nothing a
    # level could show coming back down - and the store's own count is a
    # statement about the world rather than a platform's acknowledgement.
    #
    # The clock is frozen on purpose: a receipt is in hand the moment the action
    # returns, so a verdict that needed the wait to run out would be waiting on a
    # window that can never answer.
    some_keys = ("io-shop:summary:shopper-3", "io-shop:summary:shopper-7")

    Scenario() \
        .given(
            the_store_found_both_of_them := a_discard_removing(2)
        ) \
        .when(
            lambda: take_action(
                _a_discard_of(SOME_APPLICATION, some_keys),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(discard=the_store_found_both_of_them),
                fetch_metrics=metrics_reading(a_window_that_never_departed()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_detail_does_not_mention("returned to baseline")
        ))


@pytest.mark.unit
def test_a_discard_is_confirmed_by_its_receipt_where_nothing_is_published() -> None:
    # The case above asked this of a window whose series were flat. This asks it
    # of the window a service in this state actually serves: none at all. An
    # incident that moves no series is an incident nothing publishes minutes
    # about, and a window with no minutes in it is not a window that disagrees -
    # it is a window with nothing to say.
    #
    # Read as disagreement, it refuted the one kind of action whose own answer
    # settles it. The slice from the onset up to the action is empty, so the
    # sight read as absent for a service that is fully observed, and the receipt
    # sat behind that measurement and was never reached. The onset is stated
    # because stating it is what makes the slice askable at all: an undated
    # incident takes the other path, which is why five discard cases and a green
    # suite never saw this.
    some_keys = ("io-shop:summary:shopper-3", "io-shop:summary:shopper-7")

    Scenario() \
        .given(
            the_store_found_both_of_them := a_discard_removing(2)
        ) \
        .when(
            lambda: take_action(
                _a_discard_of(SOME_APPLICATION, some_keys),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(discard=the_store_found_both_of_them),
                fetch_metrics=metrics_reading([]),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls(),
                onset=THE_ONSET
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            # What confirmed it, and not merely that something did. Every minute
            # of a window holding no departure counts as recovered, so the
            # recovery rule reaches CONFIRMED here too - a case asserting the
            # verdict alone would stay green with the receipt still gated, which
            # is the hole this closes rather than the one it reports.
            _the_detail_mentions("the store reported what it removed"),
            _the_detail_does_not_mention("returned to baseline")
        ))


@pytest.mark.unit
def test_a_restart_is_not_confirmed_by_a_window_nobody_published() -> None:
    # The guard on the case above, and why its rule still asks about the
    # departure instead of dropping the question. A restart reports that a
    # request was taken and nothing about what changed, so an empty window owes
    # it nothing: there is no receipt to settle it and no level to settle it
    # with, and confirming it would close an incident on no evidence at all.
    #
    # Asserted as "not confirmed" rather than as a verdict of its own, because
    # which of the other two it should be is a separate question about a window
    # that answered and said nothing - and pinning one here would make this case
    # fail when that question is answered.
    Scenario() \
        .given(
            dont_care_undo := an_undo_nobody_calls()
        ) \
        .when(
            lambda: take_action(
                an_action_restarting(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(
                    restart=_a_restarter_bringing_up(SOME_APPLICATION)
                ),
                fetch_metrics=metrics_reading([]),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=dont_care_undo,
                onset=THE_ONSET
            )
        ) \
        .then(all_of(
            _the_verdict_is_not(Verdict.CONFIRMED),
            _the_detail_does_not_mention("the store reported what it removed")
        ))


@pytest.mark.unit
def test_a_refuted_discard_puts_nothing_back_and_says_no_undo_was_owed() -> None:
    # The third silence, and it means what neither of the others does. A restart
    # puts nothing back because it changed nothing to put back; a rollback puts
    # something back because what it replaced is worth restoring. This changed
    # something real - figures are gone from the store - and still owes no undo,
    # because the figures were a copy of records it never touched.
    #
    # So the restart's words are false here, which is the whole of what this
    # pins. "There was nothing to put back" tells a reader the action was inert,
    # and the next person deciding whether to look at the cache would be told
    # Argus had never been in it.
    #
    # Refuted rather than confirmed from the receipt, because this window
    # departed. A discard is settled by its own answer only where no series ever
    # moved; where one moved and did not come back, the discard is an
    # explanation the evidence has not borne out, like any other.
    Scenario() \
        .given(
            nothing_was_put_back := an_undo_nobody_calls()
        ) \
        .when(
            lambda: take_action(
                _a_discard_of(SOME_APPLICATION, ("io-shop:summary:shopper-3",)),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(discard=a_discard_removing(1)),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=nothing_was_put_back
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.REFUTED),
            _no_undo_was_asked_for(nothing_was_put_back),
            _there_is_nothing_to_put_back(),
            _the_detail_mentions("no undo was owed"),
            _the_detail_does_not_mention("nothing to put back")
        ))


@pytest.mark.unit
def test_a_restart_is_not_confirmed_by_a_window_that_never_departed() -> None:
    # The hole this whole change exists to close, and the one outcome worse than
    # escalating. A walk that read this incident as a leak restarts the shop,
    # reads a window that never departed, and - because every minute of such a
    # window counts as recovered - closes it `MITIGATED` with every page still
    # wrong. The restart reports nothing about what it changed, so there is no
    # receipt to settle it either, and the honest answer is that nothing here
    # confirms anything.
    Scenario() \
        .given(
            the_shop_was_restarted := _a_restarter_bringing_up(SOME_APPLICATION)
        ) \
        .when(
            lambda: take_action(
                an_action_restarting(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(restart=the_shop_was_restarted),
                fetch_metrics=metrics_reading(a_window_that_never_departed()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            _the_verdict_is_not(Verdict.CONFIRMED),
            _the_detail_does_not_mention("returned to baseline")
        ))


@pytest.mark.unit
def test_a_measured_onset_is_still_judged_on_the_levels_it_always_was() -> None:
    # The half that must not move. Everything above is about a window with no
    # departure in it; this is a window with one, and asking whether it holds a
    # departure changes nothing about how it is judged - the service left its
    # baseline, came back, and the verdict is read off that as it always was.
    Scenario() \
        .given(
            the_shop_was_restarted := _a_restarter_bringing_up(SOME_APPLICATION)
        ) \
        .when(
            lambda: take_action(
                an_action_restarting(SOME_APPLICATION),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(restart=the_shop_was_restarted),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_detail_mentions("returned to baseline")
        ))


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


def _no_undo_was_asked_for(undo: MagicMock) -> Assertion[Outcome]:
    """The undo seam never reached, where the action owes no undo.

    Distinct from a change left in place because nothing was measured, which is
    what `_nothing_was_put_back_through` is about. Here the service was read and
    the hypothesis was refuted, and the undo is still not called - not because
    Argus cannot put this change back safely, but because putting it back would
    mean writing the stale figures in again, which is recreating the incident.
    """
    def assertion(_outcome: Outcome) -> bool:
        if undo.call_count != 0:
            raise AssertionError(
                f"Expected a refuted action owing no undo to ask for none, and "
                f"the undo was called [{undo.call_count}] times."
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


def _the_wait_allowed(published: list[IncidentEvent],
                      seconds: float) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        announced = next(
            event for event in published if isinstance(event, AwaitingRecovery)
        )
        if announced.seconds_allowed != seconds:
            raise AssertionError(
                f"Expected the wait to allow [{seconds}]s, "
                f"got [{announced.seconds_allowed}]s."
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


def _the_recovery_was_recorded_at(published: list[IncidentEvent],
                                  minute: str) -> Assertion[Outcome]:
    """The look that confirmed carries the minute the metrics say the service
    came back at.

    Asked of that look rather than of all of them, because it is the only one
    with a minute to carry: a look that found the service still failing has
    nothing to date, and one that answers a minute anyway is answering about a
    recovery it did not see.
    """
    def assertion(_outcome: Outcome) -> bool:
        confirmed = [
            event
            for event in published
            if isinstance(event, RecoveryChecked) and event.recovered
        ]

        if not confirmed:
            raise AssertionError(
                f"Expected a look reporting recovery at [{minute}], and no look "
                f"reported any."
            )

        if confirmed[-1].recovered_minute != minute:
            raise AssertionError(
                f"Expected the recovery to be recorded at [{minute}], got "
                f"[{confirmed[-1].recovered_minute}]."
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


def _some_mitigation_settings(reporting_lag_minutes: int = 0) -> MitigationSettings:
    """How Mitigation behaves, as this suite sets it.

    The lookback and the actor are named because the attribution tests turn on
    them; the wait is named because the expiry tests do. The cap is named only
    because the slice requires one - how many attempts a subject is allowed is
    the gate's question, and nothing taken here ever asks it twice. The
    reporting lag is 0 unless a test names it: a source that reports the minute
    in progress, which is what every other case here reads.
    """
    return MitigationSettings(
        mitigation_change_lookback_minutes=60,
        unleash_actor="argus",
        argocd_actor="argus",
        mitigation_verification_timeout_seconds=A_SHORT_WAIT_IN_SECONDS,
        mitigation_attempts_per_subject=1,
        metrics_reporting_lag_minutes=reporting_lag_minutes
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


def _it_carries_nothing_to_put_back() -> Assertion[Outcome]:
    def assertion(outcome: Outcome) -> bool:
        if outcome.undo_descriptor is not None:
            raise AssertionError(
                f"Expected an action that was never taken to leave nothing to put "
                f"back, and it carried [{outcome.undo_descriptor}]."
            )

        return True

    return assertion


def _the_flag_was_never_set(set_state: MagicMock) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        if set_state.called:
            raise AssertionError(
                f"Expected no flag to be set for an incident nobody wanted any "
                f"more, got {set_state.call_args_list}."
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


def _a_pin_to(card: str) -> PinToAccelerator:
    return PinToAccelerator(application=SOME_APPLICATION, accelerator=card)


def _a_card_pinner_moving(was_pinned_to: str | None) -> MagicMock:
    """Answers as the tier does when the pin went through, recording the card
    the pods were held to before - `None` where they were held to none."""
    pin: MagicMock = create_autospec(AcceleratorPinner, instance=True)
    pin.return_value = AcceleratorPinUndo(
        application=SOME_APPLICATION,
        was_pinned_to=was_pinned_to,
        pinned_to=THE_FLEETS_CARD,
        was_syncing_itself=True
    )

    return pin


def _a_card_pinner_with_nothing_to_move(refusal: str) -> MagicMock:
    """Answers as the tier does when the deployment is already on the card -
    marked the way the tier marks it, as `_a_pinner_with_no_room_left` is."""
    pin: MagicMock = create_autospec(AcceleratorPinner, instance=True)
    pin.side_effect = ActionExhausted(an_exhausted_action(refusal))

    return pin


def _the_card_pin_asked_for(pin: MagicMock,
                            application: str,
                            card: str) -> Assertion[Outcome]:
    def assertion(dont_care_outcome: Outcome) -> bool:
        asked = pin.call_args.args if pin.call_args else ()

        if asked != (application, card):
            raise AssertionError(
                f"Expected [{application}] to be held to [{card}], and the tier "
                f"was asked {asked}."
            )

        return True

    return assertion


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
) -> MetricsFetcher:
    """A metrics read that raises the first time and answers after.

    The real failure this stands for is a read tier whose tool executed and
    timed out - `McpToolError`, not a refused connection, which is the one the
    transport already retries. Raised as that type rather than a bare
    `Exception` so the test fails if the loop is narrowed to catch something
    else and this stops being the shape that reaches it.
    """
    answered = False

    def read(dont_care_rule: str | None, /) -> list[MetricBucket]:
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


def _a_read_that_never_answers() -> MetricsFetcher:
    """A metrics read that fails every time it is asked.

    The shape of the failure, and what makes it a different case from the one
    above: a read tier under the load the polling itself creates does not
    recover between passes, so a window bought to measure recovery can run out
    with not one reading in it.
    """
    def read(dont_care_rule: str | None, /) -> list[MetricBucket]:
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


def _a_discard_of(service: str, keys: tuple[str, ...]) -> DiscardCacheEntries:
    return DiscardCacheEntries(service=service, keys=keys)


def _a_discarder_with_nothing_left_to_remove(refusal: str) -> MagicMock:
    """Answers as the tier does when the action has nothing further to do.

    `ActionExhausted` for the reason the pin's stand-in raises it: that is what
    the transport raises when a tool's refusal carries the marker, and a case
    raising anything else would exercise a failure production cannot produce.
    """
    discard: MagicMock = create_autospec(CacheEntryDiscarder, instance=True)
    discard.side_effect = ActionExhausted(an_exhausted_action(refusal))

    return discard


def _the_verdict_is_not(forbidden: Verdict) -> Assertion[Outcome]:
    """Any verdict but this one.

    Written as a refusal rather than as the verdict expected, because what is
    being claimed is that one answer may not be reached - and naming a
    replacement would turn a test about an unsafe confirmation into a test about
    which safe answer was chosen instead, which is a different decision and not
    this one's to pin.
    """
    def assertion(outcome: Outcome) -> bool:
        if outcome.verdict is forbidden:
            raise AssertionError(
                f"Expected any verdict but [{forbidden}], and the attempt "
                f"settled on it anyway: [{outcome.detail}]."
            )

        return True

    return assertion



@pytest.mark.unit
def test_a_rule_that_stopped_firing_after_the_action_confirms_it() -> None:
    # Confirmed on the rule even where the metrics window still reads the
    # incident: whether the service is acceptable again is the rule's to say.
    Scenario() \
        .given(
            the_rule_resolved := _a_rule_reading(_a_rule_standing(
                is_normal=True, evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC)
            ))
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                the_rule_resolved,
                metrics=a_still_failing_window(),
                clock=a_clock_frozen_at(ACTION_TIME)
            )
        ) \
        .then(
            the_verdict_is(Verdict.CONFIRMED)
        )


@pytest.mark.unit
def test_a_rule_still_firing_when_the_time_runs_out_refutes_the_action() -> None:
    # The defect this closes: a flap with no rhythm hands the metrics a clear
    # minute and they confirm on it. A rule watching long enough to see the flap
    # goes on firing, and that is what refutes.
    Scenario() \
        .given(
            the_rule_still_fires := _a_rule_reading(_a_rule_standing(
                is_normal=False, evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC)
            ))
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                the_rule_still_fires,
                metrics=a_recovered_window(),
                clock=a_clock_that_runs_out_after_one_look(ACTION_TIME)
            )
        ) \
        .then(
            the_verdict_is(Verdict.REFUTED)
        )


@pytest.mark.unit
def test_a_rule_that_was_normal_before_the_action_does_not_confirm_it() -> None:
    # An evaluation whose range began before the action says nothing about the
    # action - the rule may have gone quiet in a lull the action had no part in.
    Scenario() \
        .given(
            the_rule_was_quiet_already := _a_rule_reading(_a_rule_standing(
                is_normal=True, evaluated_at=datetime(2026, 8, 20, 11, 11, tzinfo=UTC)
            ))
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                the_rule_was_quiet_already,
                metrics=a_recovered_window(),
                clock=a_clock_that_runs_out_after_one_look(ACTION_TIME)
            )
        ) \
        .then(
            the_verdict_is(Verdict.REFUTED)
        )


@pytest.mark.unit
def test_the_wait_is_read_off_the_rule() -> None:
    # The rule's range, plus one evaluation of its group, plus how long it keeps
    # firing, plus the metrics source's lag: two minutes, one, thirty seconds and
    # one minute, 270 seconds. Watched that long rather than for the configured
    # wait - still firing at 200 seconds is looked at again, and refuted at 270.
    Scenario() \
        .given(
            published := _a_page_listening(),
            the_rule_still_fires := _a_rule_reading(_a_rule_standing(
                is_normal=False,
                evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC),
                range_seconds=120,
                interval_seconds=60,
                keep_firing_for_seconds=30
            ))
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                the_rule_still_fires,
                metrics=a_still_failing_window(),
                clock=a_clock_reading_at(ACTION_TIME, 200, 270),
                publisher=published.append,
                reporting_lag_minutes=1
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.REFUTED),
            _the_wait_allowed(published, 270),
            _each_look_reported(published, False, False)
        ))


@pytest.mark.unit
def test_a_rule_confirming_the_action_still_records_the_minute_the_metrics_date() -> None:
    # The rule decides the verdict, not the minute. When the service came back is
    # a fact the metrics hold, and the write-up reads it.
    the_minute_it_came_back = "2026-08-20T11:08:00Z"

    Scenario() \
        .given(
            published := _a_page_listening(),
            the_rule_resolved := _a_rule_reading(_a_rule_standing(
                is_normal=True, evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC)
            ))
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                the_rule_resolved,
                metrics=a_window_recovered_before_the_action(),
                clock=a_clock_frozen_at(ACTION_TIME),
                publisher=published.append
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_recovery_was_recorded_at(published, the_minute_it_came_back)
        ))


@pytest.mark.unit
def test_a_rule_that_could_never_be_read_reaches_no_verdict() -> None:
    # Not refuted: nothing said the rule was still firing. Refuting would put a
    # change back on a measurement nobody took.
    Scenario() \
        .given(
            nobody_can_read_the_rule := _a_rule_nobody_can_read()
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                nobody_can_read_the_rule,
                metrics=a_recovered_window(),
                clock=a_clock_that_runs_out_after_one_look(ACTION_TIME)
            )
        ) \
        .then(
            the_verdict_is(Verdict.ESCALATED)
        )


@pytest.mark.unit
def test_a_window_that_never_departed_does_not_refute_an_action_the_rule_judges() -> None:
    # The metrics get no verdict of their own on an action the rule judges. A
    # window with nothing departed in it says nothing the rule has not, and
    # refuting on it would put back a change the rule found had worked.
    Scenario() \
        .given(
            the_rule_resolved := _a_rule_reading(_a_rule_standing(
                is_normal=True, evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC)
            ))
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                the_rule_resolved,
                metrics=a_window_that_never_departed(),
                clock=a_clock_frozen_at(ACTION_TIME)
            )
        ) \
        .then(
            the_verdict_is(Verdict.CONFIRMED)
        )


@pytest.mark.unit
def test_metrics_that_cannot_be_read_do_not_keep_the_rule_from_judging() -> None:
    # On the rule's path the window is read only to date the recovery, so a
    # window that cannot be read costs that date and nothing more: the rule
    # still says whether the action held.
    Scenario() \
        .given(
            the_rule_resolved := _a_rule_reading(_a_rule_standing(
                is_normal=True, evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC)
            ))
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                incident_id=_SOME_INCIDENT_ID,
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True)
                ),
                fetch_metrics=_a_read_that_never_answers(),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls(),
                rule=SOME_RULE,
                read_rule=the_rule_resolved
            )
        ) \
        .then(
            the_verdict_is(Verdict.CONFIRMED)
        )


@pytest.mark.unit
def test_the_service_is_re_read_for_the_rule_that_paged() -> None:
    # On the rule's path the window dates the recovery, and the minute it should
    # date is the one the rule's own series came back in. Read without the rule,
    # the window carries the five fixed series alone, and on an incident only
    # that series departed in the minute recorded is one nothing was wrong in.
    fetch_metrics: MagicMock = create_autospec(
        MetricsFetcher, instance=True, return_value=a_still_failing_window()
    )

    Scenario() \
        .given(
            the_rule_resolved := _a_rule_reading(_a_rule_standing(
                is_normal=True, evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC)
            ))
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                incident_id=_SOME_INCIDENT_ID,
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True)
                ),
                fetch_metrics=fetch_metrics,
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls(),
                rule=SOME_RULE,
                read_rule=the_rule_resolved
            )
        ) \
        .then(
            _the_service_was_read_for(fetch_metrics, SOME_RULE)
        )


@pytest.mark.unit
def test_a_rule_still_firing_is_read_again_until_it_stops() -> None:
    # Polled, not read once: a rule firing inside its deadline is asked again,
    # and the evaluation that reads it normal confirms.
    Scenario() \
        .given(
            published := _a_page_listening(),
            the_rule_stops_firing := _a_rule_reading_in_turn(
                _a_rule_standing(
                    is_normal=False, evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC)
                ),
                _a_rule_standing(
                    is_normal=True, evaluated_at=datetime(2026, 8, 20, 11, 13, tzinfo=UTC)
                )
            )
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                the_rule_stops_firing,
                metrics=a_still_failing_window(),
                clock=a_clock_reading_at(ACTION_TIME, 60, 120),
                publisher=published.append
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _each_look_reported(published, False, True)
        ))


@pytest.mark.unit
def test_an_evaluation_whose_range_begins_as_the_change_arrived_confirms_it() -> None:
    # The boundary: a range that starts at the very instant the change was in
    # force covers no minute before it.
    some_range_seconds = 60

    Scenario() \
        .given(
            the_rule_resolved := _a_rule_reading(_a_rule_standing(
                is_normal=True,
                evaluated_at=ACTION_TIME + timedelta(seconds=some_range_seconds),
                range_seconds=some_range_seconds
            ))
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                the_rule_resolved,
                metrics=a_still_failing_window(),
                clock=a_clock_frozen_at(ACTION_TIME)
            )
        ) \
        .then(
            the_verdict_is(Verdict.CONFIRMED)
        )


@pytest.mark.unit
def test_a_rule_unreadable_at_first_is_judged_once_it_can_be_read() -> None:
    Scenario() \
        .given(
            the_rule_answers_late := _a_rule_reading_in_turn(
                McpToolError("the rule could not be read"),
                _a_rule_standing(
                    is_normal=True, evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC)
                )
            )
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                the_rule_answers_late,
                metrics=a_still_failing_window(),
                clock=a_clock_reading_at(ACTION_TIME, 10, 20)
            )
        ) \
        .then(
            the_verdict_is(Verdict.CONFIRMED)
        )


@pytest.mark.unit
def test_a_rule_read_firing_and_unreadable_at_its_deadline_refutes() -> None:
    # Unlike a rule never read: the last thing it said was that it was firing,
    # and the deadline it set has passed.
    Scenario() \
        .given(
            the_rule_goes_quiet_firing := _a_rule_reading_in_turn(
                _a_rule_standing(
                    is_normal=False, evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC)
                ),
                McpToolError("the rule could not be read")
            )
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                the_rule_goes_quiet_firing,
                metrics=a_still_failing_window(),
                clock=a_clock_reading_at(ACTION_TIME, 10, 3600)
            )
        ) \
        .then(
            the_verdict_is(Verdict.REFUTED)
        )


@pytest.mark.unit
def test_a_rule_that_cannot_be_read_is_said_to_have_gone_unanswered() -> None:
    Scenario() \
        .given(
            published := _a_page_listening(),
            nobody_can_read_the_rule := _a_rule_nobody_can_read()
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                nobody_can_read_the_rule,
                metrics=a_recovered_window(),
                clock=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                publisher=published.append
            )
        ) \
        .then(
            _the_rule_read_was_said_unanswered(published)
        )


@pytest.mark.unit
def test_an_incident_withdrawn_while_its_rule_is_watched_is_withdrawn() -> None:
    Scenario() \
        .given(
            the_rule_still_fires := _a_rule_reading(_a_rule_standing(
                is_normal=False, evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC)
            ))
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                incident_id=_SOME_INCIDENT_ID,
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True)
                ),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                still_wanted=nobody_wants_it_any_more(),
                undo=an_undo_nobody_calls(),
                rule=SOME_RULE,
                read_rule=the_rule_still_fires
            )
        ) \
        .then(
            the_verdict_is(Verdict.WITHDRAWN)
        )


@pytest.mark.unit
def test_an_action_on_an_alert_naming_no_rule_reads_no_rule() -> None:
    # The walk binds a way to read rules for every incident; an alert that named
    # none is judged without one.
    Scenario() \
        .given(
            dont_care_rules := create_autospec(RuleReader)
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                incident_id=_SOME_INCIDENT_ID,
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True)
                ),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls(),
                rule=None,
                read_rule=dont_care_rules
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.CONFIRMED),
            _the_rule_was_never_read(dont_care_rules)
        ))


@pytest.mark.unit
def test_the_rules_deadline_is_read_off_its_first_reading() -> None:
    # Read once, as the levels' deadline is: a rule whose range a later read
    # reported wider does not move the time the action was given.
    Scenario() \
        .given(
            published := _a_page_listening(),
            the_rule_widens := _a_rule_reading_in_turn(
                _a_rule_standing(
                    is_normal=False,
                    evaluated_at=datetime(2026, 8, 20, 11, 12, tzinfo=UTC),
                    range_seconds=60
                ),
                _a_rule_standing(
                    is_normal=False,
                    evaluated_at=datetime(2026, 8, 20, 11, 13, tzinfo=UTC),
                    range_seconds=3600
                )
            )
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                the_rule_widens,
                metrics=a_still_failing_window(),
                clock=a_clock_reading_at(ACTION_TIME, 10, 130, 7200),
                publisher=published.append
            )
        ) \
        .then(all_of(
            the_verdict_is(Verdict.REFUTED),
            _each_look_reported(published, False, False)
        ))


def _the_service_was_read_for(fetch_metrics: MagicMock, rule: str) -> Assertion[Outcome]:
    """That every read of the service was made for this rule."""
    def assertion(dont_care_outcome: Outcome) -> bool:
        asked = [read.args for read in fetch_metrics.call_args_list]
        if not asked or any(args != (rule,) for args in asked):
            raise AssertionError(
                f"Expected every read of the service to be made for the rule "
                f"[{rule}], and they were made as {asked}."
            )

        return True

    return assertion


def _an_action_judged_by_the_rule(read_rule: RuleReader,
                                  metrics: list[MetricBucket],
                                  clock: Callable[[], datetime],
                                  publisher: Any = None,
                                  reporting_lag_minutes: int = 0) -> Outcome:
    """One flag revert on an incident paged by `SOME_RULE`."""
    keywords = {"publisher": publisher} if publisher is not None else {}

    return take_action(
        an_action_setting(DONT_CARE_FLAG, enabled=False),
        settings=_some_mitigation_settings(reporting_lag_minutes),
        thresholds=_some_thresholds(),
        incident_id=_SOME_INCIDENT_ID,
        writes=the_writes(
            set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True)
        ),
        fetch_metrics=metrics_reading(metrics),
        now=clock,
        sleep=dont_care_sleep,
        undo=an_undo_that_put_it_back(DONT_CARE_FLAG),
        rule=SOME_RULE,
        read_rule=read_rule,
        **keywords
    )


def _a_rule_standing(is_normal: bool,
                     evaluated_at: datetime,
                     range_seconds: int = 60,
                     interval_seconds: int = 60,
                     keep_firing_for_seconds: int = 0) -> AlertRuleStanding:
    return AlertRuleStanding(
        rule=SOME_RULE,
        is_normal=is_normal,
        evaluated_at=evaluated_at,
        range_seconds=range_seconds,
        interval_seconds=interval_seconds,
        keep_firing_for_seconds=keep_firing_for_seconds
    )


def _a_rule_reading(standing: AlertRuleStanding) -> RuleReader:
    read = create_autospec(RuleReader)
    read.return_value = standing

    return cast(RuleReader, read)


def _a_rule_nobody_can_read() -> RuleReader:
    read = create_autospec(RuleReader)
    read.side_effect = McpToolError("the rule could not be read")

    return cast(RuleReader, read)


def _a_rule_reading_in_turn(*answers: AlertRuleStanding | Exception) -> RuleReader:
    """A rule read once per answer, in order, sticking at the last - as the
    clocks here stick - so a loop that asks once more than expected is answered
    rather than handed a `StopIteration`."""
    remaining = list(answers)

    def read(rule: str, /) -> AlertRuleStanding:
        answer = remaining.pop(0) if len(remaining) > 1 else remaining[0]

        if isinstance(answer, Exception):
            raise answer

        return answer

    return cast(RuleReader, create_autospec(RuleReader, side_effect=read))


def _the_rule_read_was_said_unanswered(
    published: list[IncidentEvent]
) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        asked = [
            event.what_was_asked for event in published
            if isinstance(event, RetrievalUnanswered)
        ]

        if "the alert rule that paged" not in asked:
            raise AssertionError(
                f"Expected a read of the alert rule that paged to be said to have "
                f"gone unanswered, and the unanswered reads were {asked}."
            )

        return True

    return assertion


def _the_rule_was_never_read(read_rule: RuleReader) -> Assertion[Outcome]:
    def assertion(_outcome: Outcome) -> bool:
        asked = cast(MagicMock, read_rule).call_count

        if asked:
            raise AssertionError(
                f"Expected no rule to be read for an alert that named none, and "
                f"one was read {asked} times."
            )

        return True

    return assertion


# ---- what it logs ----

# Where taking an action logs from. The verdict is the Orchestrator's line; these
# are the things that went wrong on the way to one.
THE_TRYING = "agent_mitigation.trying"


@pytest.mark.unit
def test_an_action_withheld_because_nobody_wanted_it_is_logged(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The one stop that changes nothing anywhere, so the only trace that the
    # walk chose an action and did not take it is this line.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            some_old_state := False
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=(not some_old_state)),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(set_state=_a_flag_setter_changing_from(
                    DONT_CARE_FLAG, was_enabled=some_old_state
                )),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                still_wanted=nobody_wanted_it_before_it_was_taken(),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            one_record_was_logged(caplog, THE_TRYING, logging.INFO,
                                  "action not taken, incident no longer wanted")
        )


@pytest.mark.unit
def test_a_platform_that_was_not_there_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Five actions gone at once, which is worth a line to whoever runs the
    # platform even though the walk carries on to the other two.
    Scenario() \
        .given(
            a_rollback := _a_rollback_of(SOME_APPLICATION)
        ) \
        .when(
            lambda: take_action(
                a_rollback,
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(roll_back=_a_roller_that_cannot_reach_the_platform(
                    THE_PLATFORM_DID_NOT_ANSWER
                )),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            one_record_was_logged(caplog, THE_TRYING, logging.WARNING,
                                  "deployment platform unreachable",
                                  values={"action_type": a_rollback.action_type})
        )


@pytest.mark.unit
def test_an_action_that_could_not_be_taken_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The broadest of the three refusals and the one most likely to be reached
    # by something nobody foresaw, so it carries the traceback.
    Scenario() \
        .given(
            an_action := an_action_setting(DONT_CARE_FLAG, enabled=False)
        ) \
        .when(
            lambda: take_action(
                an_action,
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(set_state=_a_flag_setter_that_cannot_write(
                    "the provider could not be reached"
                )),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            one_record_was_logged(caplog, THE_TRYING, logging.WARNING,
                                  "action could not be performed",
                                  values={"action_type": an_action.action_type},
                                  failure=RuntimeError)
        )


@pytest.mark.unit
def test_a_read_that_could_not_be_answered_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    Scenario() \
        .given(
            reads := _a_read_that_fails_once_then_answers(a_recovered_window())
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True)
                ),
                fetch_metrics=reads,
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            one_record_was_logged(caplog, THE_TRYING, logging.WARNING,
                                  "metrics could not be read", failure=McpToolError)
        )


@pytest.mark.unit
def test_a_wait_that_never_read_the_service_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The change is left where it is with nobody knowing whether it helped,
    # which is what this line is there to say.
    Scenario() \
        .given(
            reads := _a_read_that_never_answers()
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True)
                ),
                fetch_metrics=reads,
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            one_record_was_logged(caplog, THE_TRYING, logging.WARNING,
                                  "nothing was measured before the deadline")
        )


@pytest.mark.unit
def test_a_rule_that_could_not_be_read_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    Scenario() \
        .given(
            nobody_can_read_the_rule := _a_rule_nobody_can_read()
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                nobody_can_read_the_rule,
                metrics=a_recovered_window(),
                clock=a_clock_that_runs_out_after_one_look(ACTION_TIME)
            )
        ) \
        .then(
            one_record_was_logged(caplog, THE_TRYING, logging.WARNING,
                                  "alert rule could not be read", failure=McpToolError)
        )


@pytest.mark.unit
def test_a_rule_that_could_never_be_read_is_logged_as_nothing_measured(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The rule's path to the same ending as the metrics' above, and logged the
    # same way because it is the same fact about the change left in place.
    Scenario() \
        .given(
            nobody_can_read_the_rule := _a_rule_nobody_can_read()
        ) \
        .when(
            lambda: _an_action_judged_by_the_rule(
                nobody_can_read_the_rule,
                metrics=a_recovered_window(),
                clock=a_clock_that_runs_out_after_one_look(ACTION_TIME)
            )
        ) \
        .then(
            one_record_was_logged(caplog, THE_TRYING, logging.WARNING,
                                  "nothing was measured before the deadline")
        )


@pytest.mark.unit
def test_a_change_the_platform_stopped_applying_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Something a person can act on today: the platform has given up on a
    # rollout, and it will not pick it up again by itself.
    Scenario() \
        .given(
            the_platform_gave_up := (lambda _action: _a_platform_that_has_stopped_applying_it())
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True)
                ),
                fetch_metrics=metrics_reading(a_still_failing_window()),
                now=a_clock_frozen_at(ACTION_TIME),
                sleep=dont_care_sleep,
                arrivals=the_platform_gave_up,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            one_record_was_logged(caplog, THE_TRYING, logging.WARNING,
                                  "change will not arrive")
        )


@pytest.mark.unit
def test_a_change_that_had_not_arrived_by_the_deadline_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Unlike the one above, this may still converge - which is why it is its
    # own line rather than that one's.
    Scenario() \
        .given(
            still_arriving := (lambda _action: lambda: Arrival.STILL_ARRIVING)
        ) \
        .when(
            lambda: take_action(
                an_action_setting(DONT_CARE_FLAG, enabled=False),
                settings=_some_mitigation_settings(),
                thresholds=_some_thresholds(),
                writes=the_writes(
                    set_state=_a_flag_setter_changing_from(DONT_CARE_FLAG, was_enabled=True)
                ),
                fetch_metrics=metrics_reading(a_recovered_window()),
                now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
                sleep=dont_care_sleep,
                arrivals=still_arriving,
                undo=an_undo_nobody_calls()
            )
        ) \
        .then(
            one_record_was_logged(caplog, THE_TRYING, logging.WARNING,
                                  "change did not arrive in time")
        )


@pytest.mark.unit
def test_an_undo_that_failed_is_logged_as_an_error(caplog: pytest.LogCaptureFixture) -> None:
    # Production left changed for a cause that was not the cause, and somebody
    # has to go and put it back by hand.
    some_flag = "monthly-spend-feature"

    Scenario() \
        .given(
            an_action := an_action_setting(some_flag, enabled=False),
            set_state := _a_flag_setter_that_cannot_put_it_back(
                some_flag, "the provider refused the write"
            )
        ) \
        .when(
            lambda: take_action(
                an_action,
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
            one_record_was_logged(caplog, THE_TRYING, logging.ERROR,
                                  "change could not be put back",
                                  values={"action_type": an_action.action_type})
        )
