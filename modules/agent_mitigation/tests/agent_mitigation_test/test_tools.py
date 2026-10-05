"""Asking the flag provider whether a half-finished action actually landed.

A worker that died between taking an action and recording what came of it
leaves a claim with no outcome. Only the provider knows whether the change was
made, and this is the one place Argus asks it that question about itself.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import NamedTuple, cast
from unittest.mock import MagicMock, Mock, create_autospec

import pytest
from agent_mitigation.tools import (
    Arrival,
    DeploymentsBetween,
    FlagChangesSince,
    MitigationSettings,
    a_rollback_arriving_over,
    added_capacity_arriving_over,
    argus_changed_flag_since,
    deployment_restorer_over,
    deployment_roller_over,
    deployments_over,
    fetch_recent_deployments,
    fetch_recent_flag_changes,
    flag_changes_over,
    flag_setter_over,
    how_a_change_arrives,
    recent_metrics_over,
)
from argus_core import to_iso
from argus_core.mcp_transport import McpClient
from argus_core.models import (
    Action,
    ChangeEvent,
    DeploymentRollbackUndo,
    DiscardCacheEntries,
    FlagChange,
    PinAutoscaler,
    RollBackDeployment,
    RolloutProgress,
    ScaleOut,
)
from argus_testkit import Assertion, Scenario, all_of

from agent_mitigation_test.framework.builders import (
    a_deployment,
    an_action_restarting,
    an_action_setting,
)

SOME_FLAG = "kukibuki"
SOME_ARGUS_USER = "Shuki Tuki"
THE_MOMENT_IT_WAS_CLAIMED = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)
SOME_MOMENT = to_iso(THE_MOMENT_IT_WAS_CLAIMED)

# Six replicas with three updated, which is the split this reads and also the
# point at which an in-flight incompatibility fails the most requests.
SOME_FLEET_SIZE = 6
HALF_THE_FLEET = 3

ROLLOUT_PROGRESS_TOOL = "get_rollout_progress"

METRICS_TOOL = "get_metrics_summary"
FLAG_CHANGES_TOOL = "get_recent_flag_changes"
SET_FLAG_TOOL = "set_feature_flag"
ROLL_BACK_TOOL = "roll_back_deployment"
RESTORE_CONFIGURATION_TOOL = "restore_deployment"

CHANGE_EVENTS_TOOL = "get_change_events"

SOME_APPLICATION = "io-shop"
A_ROLLBACK_TO_PUT_BACK = DeploymentRollbackUndo(
    application=SOME_APPLICATION,
    was_on_history_id=2,
    was_on_revision="0d8e826225f0de73958a8a8dd3d867b2ae249e72",
    was_syncing_itself=True
)


@pytest.mark.unit
def test_a_provider_that_cannot_be_reached_answers_nothing() -> None:
    # The case that must not read as "no change was made": an unreachable
    # provider would then send the walk off to act a second time on an action
    # that may already have been taken.
    Scenario() \
        .given(
            the_provider_is_down := _a_fetch_that_fails()
        ) \
        .when(
            lambda: argus_changed_flag_since(
                SOME_FLAG,
                THE_MOMENT_IT_WAS_CLAIMED,
                _some_mitigation_settings(),
                fetch=the_provider_is_down
            )
        ) \
        .then(
            _it_answers_nothing()
        )


@pytest.mark.unit
def test_the_provider_is_asked_from_the_moment_the_action_was_claimed() -> None:
    # A change to the same flag before the claim belongs to whoever caused the
    # incident. Only one after it can be the attempt that stopped halfway.
    Scenario() \
        .given(
            fetch := _a_provider_reporting()
        ) \
        .when(
            lambda: argus_changed_flag_since(
                SOME_FLAG,
                THE_MOMENT_IT_WAS_CLAIMED,
                _some_mitigation_settings(),
                fetch=fetch
            )
        ) \
        .then(
            _it_asked_from(fetch, to_iso(THE_MOMENT_IT_WAS_CLAIMED))
        )


@pytest.mark.unit
def test_a_change_the_provider_attributes_to_argus_is_argus_own() -> None:
    # The answer a resumed walk acts on: the action it claimed did land, so
    # taking it again would be a second production write for one decision.
    Scenario() \
        .given(
            argus_changed_it := _a_provider_reporting(_a_change_by(SOME_ARGUS_USER))
        ) \
        .when(
            lambda: argus_changed_flag_since(SOME_FLAG,
                                             THE_MOMENT_IT_WAS_CLAIMED,
                                             _some_mitigation_settings(),
                                             fetch=argus_changed_it
            )
        ) \
        .then(
            _it_answers(True)
        )


@pytest.mark.unit
def test_a_change_the_provider_attributes_to_somebody_else_is_not_argus_own() -> None:
    # Somebody else moved the same flag in the same window. The claimed action
    # still did not land, and the walk has to be free to take it.
    Scenario() \
        .given(
            somebody_else_changed_it := _a_provider_reporting(
                _a_change_by("some-human"))
        ) \
        .when(
            lambda: argus_changed_flag_since(SOME_FLAG,
                                             THE_MOMENT_IT_WAS_CLAIMED,
                                             _some_mitigation_settings(),
                                             fetch=somebody_else_changed_it
            )
        ) \
        .then(
            _it_answers(False)
        )


@pytest.mark.unit
def test_the_window_asked_for_reaches_back_one_lookback_from_now() -> None:
    # The window is decided here rather than by the caller, so that proposing
    # an action stays free of both configuration and I/O.
    some_lookback = timedelta(minutes=30)
    some_moment = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)

    Scenario() \
        .given(
            fetch := _a_provider_reporting()
        ) \
        .when(
            lambda: fetch_recent_flag_changes(
                _some_mitigation_settings(lookback=some_lookback),
                fetch=fetch,
                now=lambda: some_moment
            )
        ) \
        .then(
            _it_asked_from(fetch, to_iso(some_moment - some_lookback))
        )


@pytest.mark.unit
def test_the_window_ends_at_an_onset_the_alert_stated() -> None:
    # A lookback measured back from now asks what somebody *just* changed, which
    # is the right question for an incident happening now and the wrong one for
    # an incident found by a check that runs weekly. There the flag moved a week
    # ago, a window ending now does not reach it, and Mitigation proposes
    # nothing - so the incident escalates with no action to recommend, which is
    # the one outcome this kind of incident must not produce.
    #
    # Anchored rather than widened. The sixty minutes is short on purpose: a
    # wide window makes "two flags changed, so no action" the common case.
    some_lookback = timedelta(minutes=30)
    a_week_earlier = THE_MOMENT_IT_WAS_CLAIMED - timedelta(days=7)

    Scenario() \
        .given(
            fetch := _a_provider_reporting()
        ) \
        .when(
            lambda: fetch_recent_flag_changes(
                _some_mitigation_settings(lookback=some_lookback),
                fetch=fetch,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED,
                onset=a_week_earlier
            )
        ) \
        .then(
            _it_asked_from(fetch, to_iso(a_week_earlier - some_lookback))
        )


@pytest.mark.unit
def test_a_change_made_after_the_onset_is_not_in_the_window() -> None:
    # The provider is asked from a moment and answers to the present, so a
    # window anchored a week back carries a week of changes unless something
    # closes it. A change made after the incident began did not cause it -
    # the rule the Investigator's own default window already applies.
    an_onset = THE_MOMENT_IT_WAS_CLAIMED - timedelta(days=7)
    the_one_that_moved_at_the_onset = _a_change_at(an_onset - timedelta(minutes=2))

    Scenario() \
        .given(
            fetch := _a_provider_reporting(
                the_one_that_moved_at_the_onset,
                _a_change_at(an_onset + timedelta(days=3))
            )
        ) \
        .when(
            lambda: fetch_recent_flag_changes(
                _some_mitigation_settings(),
                fetch=fetch,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED,
                onset=an_onset
            )
        ) \
        .then(
            _it_returned_only(the_one_that_moved_at_the_onset)
        )


@pytest.mark.unit
def test_changes_argus_made_itself_are_left_out() -> None:
    # Once Argus can act more than once on an incident its own revert lands in
    # this window, and a window carrying it turns the unambiguous case - one
    # flag changed, so that is the one to put back - into two, and refuses.
    somebody_elses = _a_change_by("some-human")

    Scenario() \
        .given(
            fetch := _a_provider_reporting(
                _a_change_by(SOME_ARGUS_USER), somebody_elses
            )
        ) \
        .when(
            lambda: fetch_recent_flag_changes(
                _some_mitigation_settings(),
                fetch=fetch,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED
            )
        ) \
        .then(
            _it_returned_only(somebody_elses)
        )


@pytest.mark.unit
def test_the_deploy_history_is_asked_for_the_lookback_before_a_stated_onset() -> None:
    # The window the flag history is asked for, and for the same reason: a
    # change a weekly check dated landed a week before the alert, and a window
    # ending now reaches nothing that old.
    some_lookback = timedelta(minutes=30)
    a_week_earlier = THE_MOMENT_IT_WAS_CLAIMED - timedelta(days=7)

    Scenario() \
        .given(
            fetch := _a_deploy_history_reporting()
        ) \
        .when(
            lambda: fetch_recent_deployments(
                _some_mitigation_settings(lookback=some_lookback),
                fetch=fetch,
                service=SOME_APPLICATION,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED,
                onset=a_week_earlier
            )
        ) \
        .then(
            _it_asked_for_the_window(
                fetch, SOME_APPLICATION, a_week_earlier - some_lookback, a_week_earlier
            )
        )


@pytest.mark.unit
def test_the_deploy_history_window_ends_now_where_no_onset_was_stated() -> None:
    some_lookback = timedelta(minutes=30)

    Scenario() \
        .given(
            fetch := _a_deploy_history_reporting()
        ) \
        .when(
            lambda: fetch_recent_deployments(
                _some_mitigation_settings(lookback=some_lookback),
                fetch=fetch,
                service=SOME_APPLICATION,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED
            )
        ) \
        .then(
            _it_asked_for_the_window(
                fetch,
                SOME_APPLICATION,
                THE_MOMENT_IT_WAS_CLAIMED - some_lookback,
                THE_MOMENT_IT_WAS_CLAIMED
            )
        )


@pytest.mark.unit
def test_the_deployments_the_history_reported_are_what_comes_back() -> None:
    the_deployment = a_deployment()

    Scenario() \
        .given(
            fetch := _a_deploy_history_reporting(the_deployment)
        ) \
        .when(
            lambda: fetch_recent_deployments(
                _some_mitigation_settings(),
                fetch=fetch,
                service=SOME_APPLICATION,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED
            )
        ) \
        .then(
            _it_returned_the_deployments(the_deployment)
        )


@pytest.mark.unit
def test_deployments_argus_made_itself_are_left_out() -> None:
    # Argus's own flag reverts are, and for the same reason: where no onset was
    # stated the window ends now, so a round after Argus rolled back reads its
    # rollback as the newest deployment - and proposes rolling that back.
    somebody_elses = a_deployment(actor="some-human")

    Scenario() \
        .given(
            fetch := _a_deploy_history_reporting(
                a_deployment(actor=SOME_ARGUS_USER), somebody_elses
            )
        ) \
        .when(
            lambda: fetch_recent_deployments(
                _some_mitigation_settings(),
                fetch=fetch,
                service=SOME_APPLICATION,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED
            )
        ) \
        .then(
            _it_returned_the_deployments(somebody_elses)
        )


@pytest.mark.integration
def test_the_deploy_history_is_asked_over_the_read_tier() -> None:
    # The platform's history is the read tier's, as it is for the Investigator's
    # change channel. The write tier holds no such tool, so a history bound to
    # it would fail every round rather than report anything.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write,
                    lambda: deployments_over(read)(service=SOME_APPLICATION,
                                                   window_start=SOME_MOMENT,
                                                   window_end=SOME_MOMENT))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(CHANGE_EVENTS_TOOL),
            _the_write_tier_was_asked_for()
        ))


@pytest.mark.integration
def test_the_flag_history_is_asked_over_the_write_tier() -> None:
    # The provider serves its audit log to admin credentials alone, and
    # `argus-read-mcp` holds none by design. A history bound to the read tier
    # would not error - it would find nothing, which reads exactly like an
    # incident in which no flag moved.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write,
                    lambda: flag_changes_over(write)(since=SOME_MOMENT))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(FLAG_CHANGES_TOOL)
        ))


@pytest.mark.integration
def test_the_one_write_argus_makes_goes_over_the_write_tier() -> None:
    # The tier split is enforced by absence: no read server has this tool at
    # all (spec §12.1, §13). A setter bound to the read client would fail on the
    # one call Argus makes that changes production - after the walk had already
    # decided to make it.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write,
                    lambda: flag_setter_over(write)(SOME_FLAG, True))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(SET_FLAG_TOOL)
        ))


@pytest.mark.integration
def test_the_service_is_re_read_over_the_read_tier() -> None:
    # The verdict's own evidence, and the one thing Mitigation asks that has
    # nothing to do with the provider. It belongs to the read tier for the same
    # reason every other retrieval does: reading needs no credential to mutate.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write, lambda: recent_metrics_over(read)())
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(METRICS_TOOL),
            _the_write_tier_was_asked_for()
        ))


@pytest.mark.unit
def test_each_kind_of_action_waits_for_what_it_actually_changes() -> None:
    # The dispatch, and the reason there is one. Three of the five actions have
    # nothing to wait for: a flag is in force on the next request because the shop
    # reads it fresh every time, a restart is answered with the new process's start
    # time so the tier that performed it has already waited, and an autoscaler's
    # floor is a field on its own object rather than a state anything converges on.
    #
    # The two that do are the two that change a Deployment, and they wait on
    # different counts - a rollback for the revision reaching every replica, a
    # scale-out for the replicas it asked for existing. Asserted together because
    # the claim is that they *differ*: one check for all five would either make
    # three actions wait for a rollout that is not happening, or let the two that
    # matter be judged on minutes their change was not in.
    #
    # The platform here reports a split fleet at the size it was told to be, which
    # is the one window that tells the two apart - the rollback is still arriving
    # and the capacity is already there.
    a_split_fleet_at_full_size = _a_rollout_reporting(
        wanted=SOME_FLEET_SIZE, serving=SOME_FLEET_SIZE, updated=HALF_THE_FLEET
    )

    Scenario() \
        .given(a_split_fleet_at_full_size) \
        .when(lambda: {
            kind: how_a_change_arrives(
                action, client=a_split_fleet_at_full_size
            )()
            for kind, action in cast("dict[str, Action]", {
                "a rollback": RollBackDeployment(application=SOME_APPLICATION),
                "a scale-out": ScaleOut(application=SOME_APPLICATION),
                "a flag": an_action_setting(SOME_FLAG, enabled=True),
                "a restart": an_action_restarting(SOME_APPLICATION),
                "an autoscaler pin": PinAutoscaler(application=SOME_APPLICATION),
                "a discard": DiscardCacheEntries(
                    service=SOME_APPLICATION, keys=("io-shop:summary:shopper-1",)
                )
            }).items()
        }) \
        .then(_each_kind_waits_for({
            "a rollback": Arrival.STILL_ARRIVING,
            "a scale-out": Arrival.ARRIVED,
            "a flag": Arrival.ARRIVED,
            "a restart": Arrival.ARRIVED,
            "an autoscaler pin": Arrival.ARRIVED,
            # The keys are gone when the store says they are gone. Nothing
            # converges on their absence and nothing has to be waited for, which
            # is the same answer the flag gets and for the same reason: the
            # change is complete at the moment it is accepted.
            "a discard": Arrival.ARRIVED
        }))


def _each_kind_waits_for(expected: dict[str, Arrival]) -> Assertion[dict[str, Arrival]]:
    """That every kind of action read this one window the way its own change
    arrives.

    All five in one assertion rather than one test each, because a function
    answering `ARRIVED` for everything satisfies four of them and is the bug this
    dispatch exists to avoid.
    """
    def each_kind_waits_for(measured: dict[str, Arrival]) -> bool:
        if measured != expected:
            disagreed = [
                f"[{kind}] answered [{measured.get(kind)}] rather than [{arrival}]"
                for kind, arrival in expected.items()
                if measured.get(kind) is not arrival
            ]
            raise AssertionError(
                "Expected each kind to wait for its own change, and "
                + "; ".join(disagreed) + "."
            )

        return True

    return each_kind_waits_for


@pytest.mark.unit
def test_a_rollback_has_arrived_once_every_replica_runs_the_revision() -> None:
    # What the wait is waiting for. A rollback is accepted long before the pods
    # turn over, so the minutes in between are minutes the revision being rolled
    # back was still serving - and a verdict read off them is a verdict about the
    # wrong code.
    Scenario() \
        .given(
            every_replica_has_it := _a_rollout_reporting(
                wanted=SOME_FLEET_SIZE, serving=SOME_FLEET_SIZE,
                updated=SOME_FLEET_SIZE
            )
        ) \
        .when(
            lambda: a_rollback_arriving_over(
                every_replica_has_it, SOME_APPLICATION
            )()
        ) \
        .then(
            _the_arrival_is(Arrival.ARRIVED)
        )


@pytest.mark.unit
def test_a_rollback_is_still_arriving_while_the_fleet_is_split() -> None:
    # The ordinary condition of every deployment for a minute or two, and not a
    # fault. Nothing is judged yet and nothing is given up on.
    Scenario() \
        .given(
            half_of_them_have_it := _a_rollout_reporting(
                wanted=SOME_FLEET_SIZE, serving=SOME_FLEET_SIZE,
                updated=HALF_THE_FLEET
            )
        ) \
        .when(
            lambda: a_rollback_arriving_over(
                half_of_them_have_it, SOME_APPLICATION
            )()
        ) \
        .then(
            _the_arrival_is(Arrival.STILL_ARRIVING)
        )


@pytest.mark.unit
def test_a_rolling_update_the_platform_holds_will_not_arrive() -> None:
    # What ends the wait without anybody naming a length. A rolling update nobody
    # is advancing satisfies no count ever, so a check that only answered "arrived
    # or not" would have the loop poll until its lease expired and leave the
    # change applied for another worker to find.
    #
    # Paused outranks the counts, and that is the whole point of reading it: the
    # fleet below is split, so a caller without this answer would wait for a
    # convergence that is not coming.
    Scenario() \
        .given(
            the_platform_has_stopped := _a_rollout_reporting(
                wanted=SOME_FLEET_SIZE, serving=SOME_FLEET_SIZE,
                updated=HALF_THE_FLEET, paused=True
            )
        ) \
        .when(
            lambda: a_rollback_arriving_over(
                the_platform_has_stopped, SOME_APPLICATION
            )()
        ) \
        .then(
            _the_arrival_is(Arrival.WILL_NOT_ARRIVE)
        )


@pytest.mark.unit
def test_a_rolling_update_the_platform_reports_failed_will_not_arrive() -> None:
    # The other way a rollback is held, and one a pause does not cover: a
    # Deployment past the deadline it declares, or one whose pods cannot be
    # created, is not converging either - and Kubernetes does not measure the
    # deadline while paused, so a failed rollout is never also a paused one.
    Scenario() \
        .given(
            the_platform_has_given_up := _a_rollout_reporting(
                wanted=SOME_FLEET_SIZE, serving=SOME_FLEET_SIZE,
                updated=HALF_THE_FLEET, failed=True
            )
        ) \
        .when(
            lambda: a_rollback_arriving_over(
                the_platform_has_given_up, SOME_APPLICATION
            )()
        ) \
        .then(
            _the_arrival_is(Arrival.WILL_NOT_ARRIVE)
        )


@pytest.mark.unit
def test_a_change_already_in_force_when_the_update_was_paused_has_arrived() -> None:
    # The order the two questions are asked in, which shows only on a window where
    # both answers are available. A rolling update can be stopped after it has
    # finished - every replica already on the new revision, and the pause set on a
    # deployment with nothing left to converge - and that pause says nothing about
    # the change this action made, which is in force on every replica serving.
    #
    # Read pause-first, this window answers `WILL_NOT_ARRIVE`: Mitigation then
    # reports that the change never applied and wakes somebody about a mitigation
    # that applied completely. So landed is asked first, and the pause answers only
    # for a fleet that has not finished - the case above, and the only one it is
    # read for.
    Scenario() \
        .given(
            the_whole_fleet_updated_then_held := _a_rollout_reporting(
                wanted=SOME_FLEET_SIZE, serving=SOME_FLEET_SIZE,
                updated=SOME_FLEET_SIZE, paused=True
            )
        ) \
        .when(
            lambda: a_rollback_arriving_over(
                the_whole_fleet_updated_then_held, SOME_APPLICATION
            )()
        ) \
        .then(
            _the_arrival_is(Arrival.ARRIVED)
        )


@pytest.mark.unit
def test_added_capacity_has_not_arrived_until_the_replicas_are_running() -> None:
    # The other action with something to wait for, and the case that proves the two
    # questions are different. Every replica that exists is on the right revision,
    # so a rollback would be finished here - and the deployment is running half the
    # replicas it was told to, so the capacity this action asked for is not there.
    #
    # Judging now would measure the shortage the scale-out was meant to end and
    # refute the action for not having worked yet.
    Scenario() \
        .given(
            half_the_capacity_asked_for := _a_rollout_reporting(
                wanted=SOME_FLEET_SIZE, serving=HALF_THE_FLEET,
                updated=HALF_THE_FLEET
            )
        ) \
        .when(
            lambda: added_capacity_arriving_over(
                half_the_capacity_asked_for, SOME_APPLICATION
            )()
        ) \
        .then(
            _the_arrival_is(Arrival.STILL_ARRIVING)
        )


@pytest.mark.unit
def test_added_capacity_is_still_arriving_while_the_rollout_is_paused() -> None:
    # A pause stops a new template rolling out, and nothing else. The deployment
    # controller still scales a paused Deployment - `syncDeployment` hands it to
    # `sync`, whose first act is `scale` - so the replicas a scale-out asked for
    # are on their way whether or not the rollout is held.
    #
    # Read as a rollback reads it, this window answers `WILL_NOT_ARRIVE`, and the
    # walk escalates a scale-out the platform is in the middle of applying.
    Scenario() \
        .given(
            short_of_what_it_asked_for_and_paused := _a_rollout_reporting(
                wanted=SOME_FLEET_SIZE, serving=HALF_THE_FLEET,
                updated=HALF_THE_FLEET, paused=True
            )
        ) \
        .when(
            lambda: added_capacity_arriving_over(
                short_of_what_it_asked_for_and_paused, SOME_APPLICATION
            )()
        ) \
        .then(
            _the_arrival_is(Arrival.STILL_ARRIVING)
        )


@pytest.mark.unit
def test_added_capacity_the_platform_reports_it_cannot_create_will_not_arrive() -> None:
    # What does end a scale-out's wait, now that a pause does not. A namespace out
    # of quota, or a Deployment past the deadline it declares, is what Kubernetes
    # calls a failed Deployment, and the platform says so in a condition of its
    # own - a state, not a figure anybody here chose. Without it, a scale-out the
    # platform cannot satisfy polls until the lease expires.
    Scenario() \
        .given(
            the_platform_cannot_create_them := _a_rollout_reporting(
                wanted=SOME_FLEET_SIZE, serving=HALF_THE_FLEET,
                updated=HALF_THE_FLEET, failed=True
            )
        ) \
        .when(
            lambda: added_capacity_arriving_over(
                the_platform_cannot_create_them, SOME_APPLICATION
            )()
        ) \
        .then(
            _the_arrival_is(Arrival.WILL_NOT_ARRIVE)
        )


@pytest.mark.unit
def test_added_capacity_has_arrived_once_the_replicas_are_up() -> None:
    # And the same window a rollback would call unfinished: the fleet is at the
    # size it was told to be, and the replicas are not all on the newest revision.
    # One answer for both actions would be wrong for one of them.
    Scenario() \
        .given(
            the_capacity_is_there := _a_rollout_reporting(
                wanted=SOME_FLEET_SIZE, serving=SOME_FLEET_SIZE,
                updated=HALF_THE_FLEET
            )
        ) \
        .when(
            lambda: added_capacity_arriving_over(
                the_capacity_is_there, SOME_APPLICATION
            )()
        ) \
        .then(
            _the_arrival_is(Arrival.ARRIVED)
        )


@pytest.mark.integration
def test_whether_a_change_arrived_is_asked_over_the_read_tier() -> None:
    # Reading, so the read tier - the same reason the metrics are asked there.
    # Asserted because the two clients are interchangeable at the type level and a
    # seam bound to the wrong one fails at the moment the walk has already changed
    # production, with the incident still happening.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(
                read, write,
                lambda: a_rollback_arriving_over(read, SOME_APPLICATION)()
            )
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(ROLLOUT_PROGRESS_TOOL),
            _the_write_tier_was_asked_for()
        ))


@pytest.mark.integration
def test_returning_a_deployment_to_an_earlier_revision_goes_over_the_write_tier() -> None:
    # The third write, and one no read server has either. A roller bound to the
    # read client would fail at the moment the walk had already decided to roll
    # production back - and the incident it was mitigating would still be
    # happening.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_answers_with(A_ROLLBACK_TO_PUT_BACK)
        ) \
        .when(
            _asking(read, write,
                    lambda: deployment_roller_over(write)(SOME_APPLICATION))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(ROLL_BACK_TOOL)
        ))


@pytest.mark.integration
def test_putting_a_rolled_back_deployment_back_goes_over_the_write_tier() -> None:
    # Undoing a rollback is its own tool rather than the same call reversed,
    # which is what separates it from a flag: a flag's undo is `set_state` with
    # the state the descriptor recorded, and a rollback's undo has two pieces of
    # prior state and a platform that refuses one order of them.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write,
                    lambda: deployment_restorer_over(write)(A_ROLLBACK_TO_PUT_BACK))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(RESTORE_CONFIGURATION_TOOL)
        ))


class _Asked(NamedTuple):
    """Which tool each tier was asked for, in the order it was asked."""

    read: list[str]
    write: list[str]


def _a_session_that_remembers_what_it_was_asked() -> Mock:
    """A client that answers nothing and records the question.

    Specced against `McpClient` rather than a `Protocol` of this suite's own,
    because what these seams are handed is the real thing and the question being
    asked is which of two it was handed.
    """
    client: Mock = create_autospec(McpClient, instance=True)

    return client


def _a_rollout_reporting(wanted: int,
                         serving: int,
                         updated: int,
                         paused: bool = False,
                         failed: bool = False) -> Mock:
    """A read tier answering with one rollout's counts.

    Specced against `McpClient` because that is what the seam is handed, and the
    transport applies the validator itself - so a client standing in for it
    answers the value directly rather than something to be parsed.
    """
    client: Mock = create_autospec(McpClient, instance=True)
    client.call.return_value = RolloutProgress(
        replicas_wanted=wanted,
        replicas_serving=serving,
        replicas_updated=updated,
        is_paused=paused,
        has_failed=failed
    )

    return client


def _the_arrival_is(expected: Arrival) -> Assertion[Arrival]:
    """That the seam read the counts as this state of arrival."""
    def the_arrival_is(arrival: Arrival) -> bool:
        if arrival is not expected:
            raise AssertionError(
                f"Expected [{expected}], and it answered [{arrival}]."
            )

        return True

    return the_arrival_is


def _a_session_that_answers_with(answer: object) -> Mock:
    """A session that records the question and gives a usable answer.

    The rollback's typed client checks what came back is a record of a
    deployment being rolled back, and refuses anything else - so a session
    answering with a bare mock is refused before the tier it was asked over can
    be read off it. Which is the client doing its job, and not what this test
    is about.
    """
    client: Mock = create_autospec(McpClient, instance=True)
    client.call.return_value = answer

    return client


def _asking(read: Mock, write: Mock, ask: Callable[[], object]) -> Callable[[], _Asked]:
    """Runs one seam and reports what each tier was asked for."""
    def step() -> _Asked:
        ask()

        return _Asked(
            read=[asked.args[0] for asked in read.call.call_args_list],
            write=[asked.args[0] for asked in write.call.call_args_list]
        )

    return step


def _the_read_tier_was_asked_for(*tools: str) -> Assertion[_Asked]:
    def assertion(asked: _Asked) -> bool:
        if asked.read != list(tools):
            raise AssertionError(
                f"Expected the read tier to be asked for {list(tools)}, "
                f"got {asked.read}."
            )

        return True

    return assertion


def _the_write_tier_was_asked_for(*tools: str) -> Assertion[_Asked]:
    def assertion(asked: _Asked) -> bool:
        if asked.write != list(tools):
            raise AssertionError(
                f"Expected the write tier to be asked for {list(tools)}, "
                f"got {asked.write}."
            )

        return True

    return assertion


def _a_fetch_that_fails() -> MagicMock:
    """The provider cannot be reached at all."""
    fetch: MagicMock = create_autospec(FlagChangesSince)
    fetch.side_effect = ConnectionError("the write tier is down")

    return fetch


def _it_answers_nothing() -> Assertion[bool | None]:
    def assertion(answer: bool | None) -> bool:
        if answer is not None:
            raise AssertionError(
                f"Expected no answer about the flag, got [{answer}]."
            )

        return True

    return assertion


def _it_asked_from(fetch: MagicMock, moment: str) -> Assertion[bool | None]:
    def assertion(_answer: bool | None) -> bool:
        if fetch.call_args.kwargs != {"since": moment}:
            raise AssertionError(
                f"Expected the provider to be asked from [{moment}], "
                f"got {fetch.call_args.kwargs}."
            )

        return True

    return assertion


def _a_change_by(actor: str) -> FlagChange:
    return FlagChange(
        flag=SOME_FLAG, enabled=True,
        occurred_at=to_iso(THE_MOMENT_IT_WAS_CLAIMED), actor=actor
    )


def _a_change_at(moment: datetime) -> FlagChange:
    """A change by somebody other than Argus, at a moment that matters.

    Separate from `_a_change_by` because the two tests care about different
    halves of the same record: that one is about who moved the flag, this is
    about when - and a builder taking both would make every call site state a
    fact it does not care about.
    """
    return FlagChange(
        flag=SOME_FLAG, enabled=True, occurred_at=to_iso(moment), actor="some-human"
    )


def _a_provider_reporting(*changes: FlagChange) -> MagicMock:
    fetch: MagicMock = create_autospec(FlagChangesSince)
    fetch.return_value = list(changes)

    return fetch


def _it_answers(expected: bool) -> Assertion[bool | None]:
    def assertion(answer: bool | None) -> bool:
        if answer is not expected:
            raise AssertionError(
                f"Expected the answer [{expected}], got [{answer}]."
            )

        return True

    return assertion


def _it_returned_only(*expected: FlagChange) -> Assertion[list[FlagChange]]:
    def assertion(changes: list[FlagChange]) -> bool:
        if tuple(changes) != expected:
            raise AssertionError(
                f"Expected the window to carry {expected}, got {tuple(changes)}."
            )

        return True

    return assertion


def _some_mitigation_settings(
    actor: str = SOME_ARGUS_USER,
    lookback: timedelta = timedelta(minutes=30)
) -> MitigationSettings:
    """How Mitigation behaves, as this suite sets it.

    The actor and the lookback are what these tests are about - who a change is
    attributed to, and how far back the window reaches. The wait is never
    reached here, since nothing in this file takes an action, and neither is
    the cap - nothing here proposes a second attempt on anything.
    """
    a_wait_nothing_here_reaches = 180.0

    return MitigationSettings(
        mitigation_change_lookback_minutes=int(lookback.total_seconds() // 60),
        unleash_actor=actor,
        argocd_actor=actor,
        mitigation_verification_timeout_seconds=a_wait_nothing_here_reaches,
        metrics_reporting_lag_minutes=0,
        mitigation_attempts_per_subject=1
    )


def _a_deploy_history_reporting(*deployments: ChangeEvent) -> MagicMock:
    fetch: MagicMock = create_autospec(DeploymentsBetween)
    fetch.return_value = list(deployments)

    return fetch


def _it_asked_for_the_window(fetch: MagicMock,
                             service: str,
                             starting: datetime,
                             ending: datetime) -> Assertion[list[ChangeEvent]]:
    def assertion(dont_care_deployments: list[ChangeEvent]) -> bool:
        expected = {
            "service": service,
            "window_start": to_iso(starting),
            "window_end": to_iso(ending)
        }

        if fetch.call_args.kwargs != expected:
            raise AssertionError(
                f"Expected the deploy history to be asked for {expected}, "
                f"got {fetch.call_args.kwargs}."
            )

        return True

    return assertion


def _it_returned_the_deployments(
    *expected: ChangeEvent
) -> Assertion[list[ChangeEvent]]:
    def assertion(deployments: list[ChangeEvent]) -> bool:
        if tuple(deployments) != expected:
            raise AssertionError(
                f"Expected the deployments {expected}, got {tuple(deployments)}."
            )

        return True

    return assertion
