"""Each kind of action Argus takes: the write it makes and the words for it, what
it waits for, and how the change it made is put back.

Putting a change back is conditional, and for a flag the condition is a question
about the provider's record, not about the flag's current value: has anybody but
Argus changed this flag since Argus wrote it. A value comparison answers a
different question - what does the provider's evaluation cache currently serve -
and answers it wrongly for as long as that cache is stale, which is exactly the
window in which a human's deliberate change would be overwritten.

For a change to a deployment the condition is the write tier's to settle, where
it reads the platform inside the same held change that would write: the restore
answers either that it put the change back, or what it found instead - somebody
else's change - and whether the reconciliation Argus suspended still stands. A
change left as somebody set it with Argus's suspension still in place is left
standing, which a person has to decide about; one left as somebody set it with
nothing of Argus's still in place is left as found.

Waiting differs by kind too. Two kinds change a Deployment and have a count to
wait on, and the two counts are different; the rest are in force once they are
acknowledged.

The five kinds that leave a change behind are planned before they are claimed:
the write tier works out the change and when it read the state it worked it out
from, the walk writes that onto the claim, and the write is handed it back to
compare the estate with. A restart and a discard leave nothing to compare and
have no plan.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime
from typing import Any, cast
from unittest.mock import MagicMock, call, create_autospec

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
    the_answer_was,
)
from core import RunLost
from core.models import (
    AcceleratorPinRestored,
    AcceleratorPinUndo,
    Action,
    AutoscalerUndo,
    AutoscalingRestored,
    CapacityRestored,
    ChangeFound,
    DeploymentRestored,
    DeploymentRollbackUndo,
    DiscardCacheEntries,
    FlagUndo,
    Made,
    NotMade,
    PinAutoscaler,
    PinToAccelerator,
    Planned,
    ReplicaUndo,
    RestartedService,
    RollBackDeployment,
    RolloutProgress,
    ScaleOut,
    UndoDescriptor,
)
from mcp_transport import (
    ActionExhausted,
    ChangedSince,
    McpToolError,
    a_change_made_since,
    an_exhausted_action,
)
from mitigation import UndoAttempt, Undone
from mitigation.kinds import (
    ActionKind,
    DiscardCacheEntriesKind,
    Performed,
    PinAutoscalerKind,
    PinToAcceleratorKind,
    RestartServiceKind,
    RevertFeatureFlagKind,
    RollBackDeploymentKind,
    ScaleOutKind,
    UndoableKind,
    arrival_of,
    kind_of,
    kind_undoing,
    performed_as_recorded,
    still_argus_s,
    undo_change,
)
from mitigation.tools import (
    AcceleratorPinner,
    AcceleratorPinPlanner,
    AcceleratorPinRestorer,
    AcceleratorPinStillArgusS,
    Arrival,
    AutoscalerPinner,
    AutoscalerPinPlanner,
    AutoscalerPinStillArgusS,
    AutoscalingRestorer,
    CacheEntryDiscarder,
    CapacityRestorer,
    DeploymentRestorer,
    DeploymentRoller,
    DeploymentScaler,
    FlagPlanner,
    FlagSetter,
    FlagStillArgusS,
    PerformingWrites,
    PlannedFlagSetter,
    PuttingBack,
    RollbackPlanner,
    RollbackStillArgusS,
    RolloutReader,
    ScaleOutPlanner,
    ScaleOutStillArgusS,
    ServiceRestarter,
    WhetherAFlagWasMade,
    WhetherAnAcceleratorPinWasMade,
    WhetherAnAutoscalerPinWasMade,
    WhetherARollbackWasMade,
    WhetherAScaleOutWasMade,
)

from mitigation_test.framework.builders import (
    ACTION_TIME,
    a_capacity_restorer_nobody_calls,
    a_discard_removing,
    a_plan_of,
    a_restorer_nobody_calls,
    an_action_restarting,
    an_action_setting,
    an_autoscaling_restorer_nobody_calls,
    an_undo_descriptor_for,
    nobody_can_say,
    somebody_changed_it,
    the_way_back,
    the_writes,
)

SOME_FLAG = "monthly-spend-feature"

SOME_APPLICATION = "io-shop"
SOME_SERVICE = "kuki-service"
THE_REVISION_IT_WAS_ON = "0d8e826225f0de73958a8a8dd3d867b2ae249e72"
THE_REVISION_IT_ROLLED_BACK_TO = "544cef36a8eaf45c5b030c3d5c21473d8176cef3"
# The size the deployment was running before Argus made it larger.
THE_COUNT_IT_WAS_RUNNING = 3
# What a write tier found where it left a change as somebody had set it since,
# in its own words.
SOME_FINDING = "revision [9b2c4e1] by [alice]"
# The floor the autoscaler was allowed to fall to before Argus held it still.
THE_FLOOR_IT_WAS_HOLDING = 3
# And the floor it was raised to, which is the ceiling here and is not always: the
# tier asks for whichever is smaller of the ceiling and Argus's own cap.
THE_CEILING_IT_WAS_HELD_AT = 6
# The card Argus held the deployment's pods to, and one somebody else had held
# them to before - the case where letting go is putting a pin back rather than
# removing one.
THE_CARD_IT_WAS_HELD_TO = "Tesla-V100-SXM2-16GB"
A_CARD_SOMEBODY_ELSE_CHOSE = "Tesla-T4"
SOME_CACHE_KEY = "io-shop:summary:shopper-3"
# The state a flag action asks for, which its plan is asked for beside the flag:
# the one thing about a flag change the tier could not work out for itself.
THE_STATE_THE_FLAG_IS_ASKED_INTO = True
# A count of exactly one, where the noun has to agree with it.
ONE_REPLICA = 1
# The count an autoscaler had moved the deployment to between the plan and the
# write - one more than the plan read, which is all that matters about it.
THE_COUNT_THE_AUTOSCALER_MOVED_IT_TO = THE_COUNT_IT_WAS_RUNNING + 1
# When the flag's write landed, as the write tier answers it. What tells that
# write's answer apart from the plan it was handed, which carries no such
# moment; a deployment's write answers with the plan undated.
THE_WRITE_LANDED_AT = ACTION_TIME

# Six replicas with three updated, which is the split an arrival reads and also
# the point at which an in-flight incompatibility fails the most requests.
SOME_FLEET_SIZE = 6
HALF_THE_FLEET = 3

# Where the kinds log from.
THE_KINDS = "mitigation.kinds"

# The case lists below hold ways to build what a case is handed rather than the
# things themselves. A lambda looks its names up when it is called, so the
# builders it calls can be defined further down, and every case is handed
# collaborators of its own rather than one mock shared with every other. The
# kinds themselves are shared: they hold nothing.

# Every kind of action, one of each, with the kind that takes it.
EVERY_KIND_OF_ACTION = [
    pytest.param(lambda: an_action_setting(SOME_FLAG, enabled=True),
                 RevertFeatureFlagKind, id="flag"),
    pytest.param(lambda: an_action_restarting(SOME_SERVICE), RestartServiceKind, id="restart"),
    pytest.param(lambda: RollBackDeployment(application=SOME_APPLICATION),
                 RollBackDeploymentKind, id="rollback"),
    pytest.param(lambda: ScaleOut(application=SOME_APPLICATION), ScaleOutKind, id="scale-out"),
    pytest.param(lambda: PinAutoscaler(application=SOME_APPLICATION),
                 PinAutoscalerKind, id="autoscaler-pin"),
    pytest.param(lambda: a_pin_to(THE_CARD_IT_WAS_HELD_TO), PinToAcceleratorKind,
                 id="card-pin"),
    pytest.param(lambda: a_discard_of(SOME_CACHE_KEY), DiscardCacheEntriesKind, id="discard")
]

# Every kind of change, one of each, with the kind that puts it back.
EVERY_KIND_OF_CHANGE = [
    pytest.param(lambda: an_undo_descriptor_for(SOME_FLAG), RevertFeatureFlagKind, id="flag"),
    pytest.param(lambda: a_rollback_descriptor_for(SOME_APPLICATION),
                 RollBackDeploymentKind, id="rollback"),
    pytest.param(lambda: a_resize_descriptor_for(SOME_APPLICATION), ScaleOutKind,
                 id="scale-out"),
    pytest.param(lambda: a_pin_descriptor_for(SOME_APPLICATION), PinAutoscalerKind,
                 id="autoscaler-pin"),
    pytest.param(lambda: a_card_pin_descriptor_for(SOME_APPLICATION), PinToAcceleratorKind,
                 id="card-pin")
]

# Every kind of action that is planned, with a plan of it, the write that
# performs it and what that write is.
EVERY_KIND_OF_PLANNED_WRITE = [
    pytest.param(RevertFeatureFlagKind(), lambda: an_action_setting(SOME_FLAG, enabled=True),
                 lambda: a_plan_of(a_planned_flag_change_for(SOME_FLAG, was_enabled=False)),
                 "set_state", PlannedFlagSetter, id="flag"),
    pytest.param(RollBackDeploymentKind(), lambda: RollBackDeployment(application=SOME_APPLICATION),
                 lambda: a_plan_of(a_rollback_descriptor_for(SOME_APPLICATION)),
                 "roll_back", DeploymentRoller, id="rollback"),
    pytest.param(ScaleOutKind(), lambda: ScaleOut(application=SOME_APPLICATION),
                 lambda: a_plan_of(a_resize_descriptor_for(SOME_APPLICATION)),
                 "scale_out", DeploymentScaler, id="scale-out"),
    pytest.param(PinAutoscalerKind(), lambda: PinAutoscaler(application=SOME_APPLICATION),
                 lambda: a_plan_of(a_pin_descriptor_for(SOME_APPLICATION)),
                 "pin", AutoscalerPinner, id="autoscaler-pin"),
    pytest.param(PinToAcceleratorKind(), lambda: a_pin_to(THE_CARD_IT_WAS_HELD_TO),
                 lambda: a_plan_of(a_card_pin_descriptor_for(SOME_APPLICATION)),
                 "pin_to_accelerator", AcceleratorPinner, id="card-pin")
]

# The two kinds of action with nothing to plan, with the write that performs
# each and what that write is.
EVERY_KIND_OF_UNPLANNED_WRITE = [
    pytest.param(RestartServiceKind(), lambda: an_action_restarting(SOME_SERVICE),
                 "restart", ServiceRestarter, id="restart"),
    pytest.param(DiscardCacheEntriesKind(), lambda: a_discard_of(SOME_CACHE_KEY),
                 "discard", CacheEntryDiscarder, id="discard")
]

# Every kind of action that is planned, with the part of the write tier that
# plans it, what that part is, and what it is asked: the address the action
# names, and for a flag the state asked for and for a pin to a card the card -
# the two things the tier could not work out for itself.
EVERY_KIND_OF_PLAN = [
    pytest.param(RevertFeatureFlagKind(),
                 lambda: an_action_setting(SOME_FLAG, enabled=THE_STATE_THE_FLAG_IS_ASKED_INTO),
                 "plan_flag", FlagPlanner, (SOME_FLAG, THE_STATE_THE_FLAG_IS_ASKED_INTO),
                 id="flag"),
    pytest.param(RollBackDeploymentKind(), lambda: RollBackDeployment(application=SOME_APPLICATION),
                 "plan_rollback", RollbackPlanner, (SOME_APPLICATION,), id="rollback"),
    pytest.param(ScaleOutKind(), lambda: ScaleOut(application=SOME_APPLICATION),
                 "plan_scale_out", ScaleOutPlanner, (SOME_APPLICATION,), id="scale-out"),
    pytest.param(PinAutoscalerKind(), lambda: PinAutoscaler(application=SOME_APPLICATION),
                 "plan_autoscaler_pin", AutoscalerPinPlanner, (SOME_APPLICATION,),
                 id="autoscaler-pin"),
    pytest.param(PinToAcceleratorKind(), lambda: a_pin_to(THE_CARD_IT_WAS_HELD_TO),
                 "plan_accelerator_pin", AcceleratorPinPlanner,
                 (SOME_APPLICATION, THE_CARD_IT_WAS_HELD_TO), id="card-pin")
]

# Every kind of action, with what it says it would have done. The words are the
# whole of what these say: each is quoted after "did not" or "could not" in a line
# that exists to explain why nothing happened.
EVERY_INTENT = [
    pytest.param(RevertFeatureFlagKind(), lambda: an_action_setting(SOME_FLAG, enabled=True),
                 f"set flag [{SOME_FLAG}] ON", id="flag"),
    pytest.param(RestartServiceKind(), lambda: an_action_restarting(SOME_SERVICE),
                 f"restart [{SOME_SERVICE}]", id="restart"),
    pytest.param(RollBackDeploymentKind(), lambda: RollBackDeployment(application=SOME_APPLICATION),
                 f"roll [{SOME_APPLICATION}] back to its previous revision", id="rollback"),
    pytest.param(ScaleOutKind(), lambda: ScaleOut(application=SOME_APPLICATION),
                 f"scale [{SOME_APPLICATION}] out", id="scale-out"),
    pytest.param(PinAutoscalerKind(), lambda: PinAutoscaler(application=SOME_APPLICATION),
                 f"stop [{SOME_APPLICATION}]'s autoscaler scaling it down", id="autoscaler-pin"),
    pytest.param(PinToAcceleratorKind(), lambda: a_pin_to(THE_CARD_IT_WAS_HELD_TO),
                 f"hold [{SOME_APPLICATION}]'s pods to [{THE_CARD_IT_WAS_HELD_TO}]",
                 id="card-pin"),
    # Figures thrown away, never data deleted or a cache cleared: what goes is a
    # copy, and a verb suggesting otherwise would describe an action a reader
    # should be alarmed by.
    pytest.param(DiscardCacheEntriesKind(), lambda: a_discard_of(SOME_CACHE_KEY),
                 f"discard [{SOME_APPLICATION}]'s stale cached figures", id="discard")
]

# Every kind of change, with the kind that puts it back, the part of the way back
# it puts it back through, and what the answer is about. One case each, because
# each kind's restore is its own.
EVERY_KIND_OF_RESTORE = [
    pytest.param(RollBackDeploymentKind(), lambda: a_rollback_descriptor_for(SOME_APPLICATION),
                 "restore_deployment", DeploymentRestorer, SOME_APPLICATION, id="rollback"),
    pytest.param(ScaleOutKind(), lambda: a_resize_descriptor_for(SOME_APPLICATION),
                 "restore_capacity", CapacityRestorer, SOME_APPLICATION, id="scale-out"),
    pytest.param(PinAutoscalerKind(), lambda: a_pin_descriptor_for(SOME_APPLICATION),
                 "restore_autoscaling", AutoscalingRestorer, SOME_APPLICATION,
                 id="autoscaler-pin"),
    pytest.param(PinToAcceleratorKind(), lambda: a_card_pin_descriptor_for(SOME_APPLICATION),
                 "restore_accelerator_pin", AcceleratorPinRestorer, SOME_APPLICATION,
                 id="card-pin"),
    pytest.param(RevertFeatureFlagKind(),
                 lambda: an_undo_descriptor_for(SOME_FLAG, was_enabled=True),
                 "set_state", FlagSetter, SOME_FLAG, id="flag")
]

# Every kind of change, with a part of the way back that puts the whole of it back.
EVERY_WHOLE_RESTORE = [
    pytest.param(RollBackDeploymentKind(), lambda: a_rollback_descriptor_for(SOME_APPLICATION),
                 "restore_deployment", lambda: _a_restorer_that_puts_back(), id="rollback"),
    pytest.param(ScaleOutKind(), lambda: a_resize_descriptor_for(SOME_APPLICATION),
                 "restore_capacity", lambda: _a_capacity_restorer_that_puts_back(),
                 id="scale-out"),
    pytest.param(PinAutoscalerKind(), lambda: a_pin_descriptor_for(SOME_APPLICATION),
                 "restore_autoscaling", lambda: _an_autoscaling_restorer_that_puts_back(),
                 id="autoscaler-pin"),
    pytest.param(PinToAcceleratorKind(), lambda: a_card_pin_descriptor_for(SOME_APPLICATION),
                 "restore_accelerator_pin",
                 lambda: _an_accelerator_pin_restorer_that_puts_back(), id="card-pin"),
    pytest.param(RevertFeatureFlagKind(),
                 lambda: an_undo_descriptor_for(SOME_FLAG, was_enabled=True),
                 "set_state", lambda: _a_flag_setter(), id="flag")
]

# Every kind that restores two things, answering that only the first went back.
EVERY_HALF_RESTORE = [
    pytest.param(RollBackDeploymentKind(), lambda: a_rollback_descriptor_for(SOME_APPLICATION),
                 "restore_deployment",
                 lambda: _a_restorer_that_puts_back(revision=True, automated_sync=False),
                 id="rollback"),
    pytest.param(ScaleOutKind(), lambda: a_resize_descriptor_for(SOME_APPLICATION),
                 "restore_capacity",
                 lambda: _a_capacity_restorer_that_puts_back(count=True, automated_sync=False),
                 id="scale-out"),
    pytest.param(PinAutoscalerKind(), lambda: a_pin_descriptor_for(SOME_APPLICATION),
                 "restore_autoscaling",
                 lambda: _an_autoscaling_restorer_that_puts_back(floor=True,
                                                                 automated_sync=False),
                 id="autoscaler-pin"),
    pytest.param(PinToAcceleratorKind(), lambda: a_card_pin_descriptor_for(SOME_APPLICATION),
                 "restore_accelerator_pin",
                 lambda: _an_accelerator_pin_restorer_that_puts_back(pin=True,
                                                                     automated_sync=False),
                 id="card-pin")
]

# Every answer but a restore, with the way back that brings it about.
EVERY_ANSWER_BUT_A_RESTORE = [
    pytest.param(RollBackDeploymentKind(), lambda: a_rollback_descriptor_for(SOME_APPLICATION),
                 lambda: the_way_back(
                     restore_deployment=_a_restorer_that_puts_back(automated_sync=False)),
                 id="rollback-partly"),
    pytest.param(RollBackDeploymentKind(), lambda: a_rollback_descriptor_for(SOME_APPLICATION),
                 lambda: the_way_back(
                     restore_deployment=_a_collaborator_raising(DeploymentRestorer)),
                 id="rollback-refused"),
    pytest.param(ScaleOutKind(), lambda: a_resize_descriptor_for(SOME_APPLICATION),
                 lambda: the_way_back(
                     restore_capacity=_a_capacity_restorer_that_puts_back(automated_sync=False)),
                 id="scale-out-partly"),
    pytest.param(ScaleOutKind(), lambda: a_resize_descriptor_for(SOME_APPLICATION),
                 lambda: the_way_back(
                     restore_capacity=_a_collaborator_raising(CapacityRestorer)),
                 id="scale-out-refused"),
    pytest.param(PinAutoscalerKind(), lambda: a_pin_descriptor_for(SOME_APPLICATION),
                 lambda: the_way_back(
                     restore_autoscaling=_an_autoscaling_restorer_that_puts_back(
                         automated_sync=False)),
                 id="autoscaler-pin-partly"),
    pytest.param(PinAutoscalerKind(), lambda: a_pin_descriptor_for(SOME_APPLICATION),
                 lambda: the_way_back(
                     restore_autoscaling=_a_collaborator_raising(AutoscalingRestorer)),
                 id="autoscaler-pin-refused"),
    pytest.param(PinToAcceleratorKind(), lambda: a_card_pin_descriptor_for(SOME_APPLICATION),
                 lambda: the_way_back(
                     restore_accelerator_pin=_an_accelerator_pin_restorer_that_puts_back(
                         automated_sync=False)),
                 id="card-pin-partly"),
    pytest.param(PinToAcceleratorKind(), lambda: a_card_pin_descriptor_for(SOME_APPLICATION),
                 lambda: the_way_back(
                     restore_accelerator_pin=_a_collaborator_raising(AcceleratorPinRestorer)),
                 id="card-pin-refused"),
    pytest.param(RevertFeatureFlagKind(),
                 lambda: an_undo_descriptor_for(SOME_FLAG, was_enabled=True),
                 lambda: the_way_back(changed_from_outside=somebody_changed_it()),
                 id="flag-left-as-found"),
    pytest.param(RevertFeatureFlagKind(),
                 lambda: an_undo_descriptor_for(SOME_FLAG, was_enabled=True),
                 lambda: the_way_back(changed_from_outside=nobody_can_say()),
                 id="flag-unaccounted-for"),
    pytest.param(RevertFeatureFlagKind(),
                 lambda: an_undated_flag_change_for(SOME_FLAG),
                 lambda: the_way_back(),
                 id="flag-undated"),
    pytest.param(RevertFeatureFlagKind(),
                 lambda: an_undo_descriptor_for(SOME_FLAG, was_enabled=True),
                 lambda: the_way_back(set_state=_a_collaborator_raising(FlagSetter)),
                 id="flag-refused"),
    pytest.param(RollBackDeploymentKind(), lambda: a_rollback_descriptor_for(SOME_APPLICATION),
                 lambda: the_way_back(restore_deployment=_a_collaborator_answering(
                     DeploymentRestorer, _a_deployment_left(SOME_FINDING, still_suspended=True))),
                 id="rollback-left-standing"),
    pytest.param(PinToAcceleratorKind(), lambda: a_card_pin_descriptor_for(SOME_APPLICATION),
                 lambda: the_way_back(restore_accelerator_pin=_a_collaborator_answering(
                     AcceleratorPinRestorer,
                     _an_accelerator_pin_left(SOME_FINDING, still_suspended=False))),
                 id="card-pin-left-as-found")
]

# Every kind of change a write tier can find somebody else's since: the kind,
# a descriptor of it Argus found syncing itself or not, the part of the way back
# that answers, and that part's answer where it left the change as found -
# saying what it found, and whether Argus's suspension still stands.
EVERY_CHANGE_SOMEBODY_COULD_MAKE_THEIR_OWN = [
    pytest.param(RollBackDeploymentKind(),
                 lambda syncing: a_rollback_descriptor_for(SOME_APPLICATION,
                                                           was_syncing_itself=syncing),
                 "restore_deployment", DeploymentRestorer,
                 lambda found, suspended: _a_deployment_left(found, suspended),
                 id="rollback"),
    pytest.param(ScaleOutKind(),
                 lambda syncing: a_resize_descriptor_for(SOME_APPLICATION,
                                                         was_syncing_itself=syncing),
                 "restore_capacity", CapacityRestorer,
                 lambda found, suspended: _a_capacity_left(found, suspended),
                 id="scale-out"),
    pytest.param(PinAutoscalerKind(),
                 lambda syncing: a_pin_descriptor_for(SOME_APPLICATION,
                                                      was_syncing_itself=syncing),
                 "restore_autoscaling", AutoscalingRestorer,
                 lambda found, suspended: _an_autoscaling_left(found, suspended),
                 id="autoscaler-pin"),
    pytest.param(PinToAcceleratorKind(),
                 lambda syncing: a_card_pin_descriptor_for(SOME_APPLICATION,
                                                           was_syncing_itself=syncing),
                 "restore_accelerator_pin", AcceleratorPinRestorer,
                 lambda found, suspended: _an_accelerator_pin_left(found, suspended),
                 id="card-pin")
]

# The two kinds with a count to wait on, each with the action that asks it.
EVERY_KIND_WITH_SOMETHING_TO_WAIT_FOR = [
    pytest.param(RollBackDeploymentKind(),
                 lambda: RollBackDeployment(application=SOME_APPLICATION), id="rollback"),
    pytest.param(ScaleOutKind(), lambda: ScaleOut(application=SOME_APPLICATION),
                 id="scale-out")
]


# ---- which kind ----


@pytest.mark.unit
@pytest.mark.parametrize(("an_action", "expected"), EVERY_KIND_OF_ACTION)
def test_each_kind_of_action_is_taken_by_its_own_kind(
    an_action: Callable[[], Action], expected: type
) -> None:
    # One example of each member of the union. The `match` behind this is what
    # the type checker holds exhaustive; what it cannot hold is that each arm
    # returns the right kind rather than the one beside it.
    Scenario() \
        .given(action := an_action()) \
        .when(lambda: kind_of(action)) \
        .then(_it_is_a(expected))


@pytest.mark.unit
@pytest.mark.parametrize(("a_descriptor", "expected"), EVERY_KIND_OF_CHANGE)
def test_each_kind_of_change_is_put_back_by_the_kind_that_made_it(
    a_descriptor: Callable[[], UndoDescriptor], expected: type
) -> None:
    # A change routed to another kind's undo is the dispatch the descriptor
    # union exists to rule out: a rollback sent to something that writes flags,
    # or a pin to a card sent to the autoscaler's restorer.
    Scenario() \
        .given(descriptor := a_descriptor()) \
        .when(lambda: kind_undoing(descriptor)) \
        .then(_it_is_a(expected))


# ---- planning ----


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "an_action", "planner", "spec", "expected"), EVERY_KIND_OF_PLAN)
def test_each_kind_is_planned_by_the_write_tier_for_what_its_action_names(
    kind: UndoableKind[Any], an_action: Callable[[], Action], planner: str, spec: type,
    expected: tuple[object, ...]
) -> None:
    # Through the write tier, which is where the write that is handed the plan
    # compares the estate with it: one port for the read and the compare, and
    # for a flag the admin read only that tier holds the token for. What the
    # tier answers is the plan, and nothing here works it out again - so any
    # plan would do, and one shape stands in for all five.
    Scenario() \
        .given(
            the_plan_answered := a_plan_of(a_resize_descriptor_for(SOME_APPLICATION)),
            planning := _a_collaborator_answering(spec, the_plan_answered)
        ) \
        .when(
            lambda: kind.plan(an_action(), the_writes(**{planner: planning}))
        ) \
        .then(all_of(
            _the_planner_was_asked(planning, *expected),
            _it_is_the_plan(the_plan_answered)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "an_action", "planner", "spec", "dont_care_asked"),
                         EVERY_KIND_OF_PLAN)
def test_a_plan_writes_nothing(
    kind: UndoableKind[Any], an_action: Callable[[], Action], planner: str, spec: type,
    dont_care_asked: tuple[object, ...]
) -> None:
    # A plan is made before the claim, and a change made before the claim is
    # one no row records - the withdrawal would never find it, and the write-up
    # would never say it happened.
    Scenario() \
        .given(
            writes := the_writes(**{planner: _a_collaborator_answering(
                spec, a_plan_of(a_resize_descriptor_for(SOME_APPLICATION))
            )})
        ) \
        .when(
            lambda: kind.plan(an_action(), writes)
        ) \
        .then(
            _nothing_was_written_through(writes)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "an_action", "planner", "spec", "dont_care_asked"),
                         EVERY_KIND_OF_PLAN)
def test_a_plan_refused_reaches_whoever_planned_it_as_the_tier_raised_it(
    kind: UndoableKind[Any], an_action: Callable[[], Action], planner: str, spec: type,
    dont_care_asked: tuple[object, ...]
) -> None:
    # A deployment already as large as Argus may make it, or a flag already as
    # asked, is refused at the plan as the write used to refuse it - and which
    # refusal it was decides the verdict, from the exception's own type. A kind
    # that caught it, or wrapped it, would turn an exhausted action into an
    # escalation.
    dont_care_refusal = "nothing left to do"

    Scenario() \
        .given(
            nothing_left_to_do := _a_collaborator_raising(
                spec, ActionExhausted(an_exhausted_action(dont_care_refusal))
            )
        ) \
        .when(attempting(
            lambda: kind.plan(an_action(), the_writes(**{planner: nothing_left_to_do}))
        )) \
        .then(
            an_error_was_raised(ActionExhausted)
        )


# ---- performing ----


@pytest.mark.unit
def test_a_flag_revert_sets_the_flag_to_the_state_it_names_from_its_plan() -> None:
    # The plan, and not the flag's name: the write compares the provider's
    # history since the plan's read before it writes anything, so a write handed
    # the name alone would have nothing to compare with.
    some_old_state = False

    Scenario() \
        .given(
            the_plan := a_plan_of(a_planned_flag_change_for(SOME_FLAG, was_enabled=some_old_state)),
            set_state := _a_planned_flag_setter_answering(
                what_it_left := _as_written(the_plan.descriptor)
            )
        ) \
        .when(
            lambda: RevertFeatureFlagKind().perform(
                an_action_setting(SOME_FLAG, enabled=(not some_old_state)),
                the_plan,
                the_writes(set_state=set_state)
            )
        ) \
        .then(all_of(
            _the_write_was_asked(set_state, the_plan, not some_old_state),
            _it_says(f"set flag [{SOME_FLAG}] ON"),
            _it_leaves(what_it_left)
        ))


@pytest.mark.unit
def test_a_restart_asks_for_the_service_the_action_names() -> None:
    Scenario() \
        .given(restart := _a_restarter_bringing_up(SOME_SERVICE)) \
        .when(
            lambda: RestartServiceKind().perform(
                an_action_restarting(SOME_SERVICE), None, the_writes(restart=restart)
            )
        ) \
        .then(all_of(
            _the_write_was_asked(restart, SOME_SERVICE),
            _it_says(f"restarted [{SOME_SERVICE}]")
        ))


@pytest.mark.unit
def test_a_restart_leaves_no_way_back() -> None:
    # A withdrawal hours later reads the outcome and does what it says. There
    # is no prior value a restart could name, so the field is absent rather
    # than empty - and absent is the only state that cannot be misread.
    Scenario() \
        .given(restart := _a_restarter_bringing_up(SOME_SERVICE)) \
        .when(
            lambda: RestartServiceKind().perform(
                an_action_restarting(SOME_SERVICE), None, the_writes(restart=restart)
            )
        ) \
        .then(_it_leaves(None))


@pytest.mark.unit
def test_a_rollback_is_written_from_the_plan_it_was_handed() -> None:
    # Not the application, and not a commit. Which entry to return to was
    # settled when the rollback was planned and recorded on the claim, and a
    # write handed anything less would work it out again from a history that
    # may have moved since.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_rollback_descriptor_for(SOME_APPLICATION)),
            roll_back := _a_roller_returning(the_plan.descriptor)
        ) \
        .when(
            lambda: RollBackDeploymentKind().perform(
                RollBackDeployment(application=SOME_APPLICATION), the_plan,
                the_writes(roll_back=roll_back)
            )
        ) \
        .then(_the_write_was_asked(roll_back, the_plan))


@pytest.mark.unit
def test_a_rollback_names_the_revision_it_rolled_off_rather_than_the_platform_s_entry() -> None:
    # The entry is the platform's address for a revision, and means nothing to
    # a reader once the history has moved on; the commit is what they look up.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_rollback_descriptor_for(SOME_APPLICATION)),
            roll_back := _a_roller_returning(the_plan.descriptor)
        ) \
        .when(
            lambda: RollBackDeploymentKind().perform(
                RollBackDeployment(application=SOME_APPLICATION), the_plan,
                the_writes(roll_back=roll_back)
            )
        ) \
        .then(all_of(
            _it_says(f"[{THE_REVISION_IT_WAS_ON}]"),
            _it_does_not_say("history entry")
        ))


@pytest.mark.unit
def test_a_rollback_leaves_the_way_back_the_write_answered_with() -> None:
    # The difference the record has to keep. A restart leaves nothing behind
    # and says so by carrying no descriptor; a rollback changed two things,
    # and a withdrawal hours later has to be able to put both of them back.
    #
    # What the write answered, which is the plan as it was handed over -
    # undated, since nothing yet says when a deployment's write landed.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_rollback_descriptor_for(SOME_APPLICATION)),
            roll_back := _a_roller_returning(
                what_it_left := the_plan.descriptor
            )
        ) \
        .when(
            lambda: RollBackDeploymentKind().perform(
                RollBackDeployment(application=SOME_APPLICATION), the_plan,
                the_writes(roll_back=roll_back)
            )
        ) \
        .then(_it_leaves(what_it_left))


@pytest.mark.unit
def test_a_scale_out_is_written_from_the_plan_it_was_handed() -> None:
    # No count of this layer's goes with it. What to scale to was the tier's to
    # resolve from what was running when it planned, and a figure named here
    # would be this layer asserting a fact about live state it has no way to
    # read.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_resize_descriptor_for(SOME_APPLICATION)),
            scale_out := _a_scaler_returning(the_plan.descriptor)
        ) \
        .when(
            lambda: ScaleOutKind().perform(
                ScaleOut(application=SOME_APPLICATION), the_plan,
                the_writes(scale_out=scale_out)
            )
        ) \
        .then(_the_write_was_asked(scale_out, the_plan))


@pytest.mark.unit
def test_a_scale_out_says_the_count_it_scaled_from_and_leaves_it_to_put_back() -> None:
    # The count it came *from*, which is what the descriptor records and what a
    # reader needs to know was undone. Where it went is the tier's to have
    # decided, and the tier reports that figure nowhere a sentence can quote it.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_resize_descriptor_for(SOME_APPLICATION)),
            scale_out := _a_scaler_returning(
                what_it_left := the_plan.descriptor
            )
        ) \
        .when(
            lambda: ScaleOutKind().perform(
                ScaleOut(application=SOME_APPLICATION), the_plan,
                the_writes(scale_out=scale_out)
            )
        ) \
        .then(all_of(
            _it_says(f"from [{THE_COUNT_IT_WAS_RUNNING}] replicas"),
            _it_leaves(what_it_left)
        ))


@pytest.mark.unit
def test_a_scale_out_says_the_count_the_write_found_rather_than_the_one_planned() -> None:
    # An autoscaler moves a count between the plan and the write as a matter of
    # course, and the write scales out from the count it finds and records that
    # one. The sentence and the way back are the write's: the plan's count is
    # a figure the deployment was no longer running when Argus changed it, and
    # a withdrawal putting it back would be putting back a number nobody left.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_resize_descriptor_for(SOME_APPLICATION)),
            scale_out := _a_scaler_returning(
                what_it_left := a_resize_descriptor_for(
                    SOME_APPLICATION, was_replicas=THE_COUNT_THE_AUTOSCALER_MOVED_IT_TO
                )
            )
        ) \
        .when(
            lambda: ScaleOutKind().perform(
                ScaleOut(application=SOME_APPLICATION), the_plan,
                the_writes(scale_out=scale_out)
            )
        ) \
        .then(all_of(
            _it_says(f"from [{THE_COUNT_THE_AUTOSCALER_MOVED_IT_TO}] replicas"),
            _it_does_not_say(f"[{THE_COUNT_IT_WAS_RUNNING}]"),
            _it_leaves(what_it_left)
        ))


@pytest.mark.unit
def test_a_scale_out_from_one_replica_says_one_replica() -> None:
    # The count agrees with its noun: "[1] replicas" is the line a reader stops at.
    Scenario() \
        .given(
            the_plan := a_plan_of(
                a_resize_descriptor_for(SOME_APPLICATION, was_replicas=ONE_REPLICA)
            ),
            scale_out := _a_scaler_returning(the_plan.descriptor)
        ) \
        .when(
            lambda: ScaleOutKind().perform(
                ScaleOut(application=SOME_APPLICATION), the_plan,
                the_writes(scale_out=scale_out)
            )
        ) \
        .then(all_of(
            _it_says(f"from [{ONE_REPLICA}] replica"),
            _it_does_not_say(f"[{ONE_REPLICA}] replicas")
        ))


@pytest.mark.unit
def test_an_autoscaler_pin_says_which_floor_it_raised_and_to_what() -> None:
    # Both numbers, because an account of a pin is a transition and one of them is
    # half of it. The floor it came from is what a withdrawal puts back. The floor
    # it went to is the one a reader cannot reconstruct: the tier asks for whichever
    # is smaller of the declared ceiling and Argus's own cap, so a line naming the
    # destination as "its ceiling" is false in exactly the case nobody checks - and
    # names a number that belongs to somebody else's declaration rather than to
    # anything Argus wrote.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_pin_descriptor_for(SOME_APPLICATION)),
            pin := _a_pinner_returning(the_plan.descriptor)
        ) \
        .when(
            lambda: PinAutoscalerKind().perform(
                PinAutoscaler(application=SOME_APPLICATION), the_plan, the_writes(pin=pin)
            )
        ) \
        .then(all_of(
            _it_says(f"from [{THE_FLOOR_IT_WAS_HOLDING}] replicas"),
            _it_says(f"to [{THE_CEILING_IT_WAS_HELD_AT}]"),
            _it_does_not_say("its ceiling")
        ))


@pytest.mark.unit
def test_an_autoscaler_pin_from_a_floor_of_one_replica_says_one_replica() -> None:
    Scenario() \
        .given(
            the_plan := a_plan_of(
                a_pin_descriptor_for(SOME_APPLICATION, was_min_replicas=ONE_REPLICA)
            ),
            pin := _a_pinner_returning(the_plan.descriptor)
        ) \
        .when(
            lambda: PinAutoscalerKind().perform(
                PinAutoscaler(application=SOME_APPLICATION), the_plan, the_writes(pin=pin)
            )
        ) \
        .then(all_of(
            _it_says(f"from [{ONE_REPLICA}] replica to"),
            _it_does_not_say(f"[{ONE_REPLICA}] replicas")
        ))


@pytest.mark.unit
def test_an_autoscaler_pin_is_written_from_the_plan_it_was_handed() -> None:
    # The floor to raise it to was the tier's to resolve from the autoscaler's
    # own ceiling when it planned, and the write compares the autoscaler with
    # the plan before it touches it.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_pin_descriptor_for(SOME_APPLICATION)),
            pin := _a_pinner_returning(the_plan.descriptor)
        ) \
        .when(
            lambda: PinAutoscalerKind().perform(
                PinAutoscaler(application=SOME_APPLICATION), the_plan, the_writes(pin=pin)
            )
        ) \
        .then(_the_write_was_asked(pin, the_plan))


@pytest.mark.unit
def test_an_autoscaler_pin_leaves_the_way_back_the_write_answered_with() -> None:
    # Both floors and the suspended sync, which is what a withdrawal hours later
    # has to put back - and the write's answer, the plan as it was handed over
    # and undated, is the record of them the row keeps.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_pin_descriptor_for(SOME_APPLICATION)),
            pin := _a_pinner_returning(
                what_it_left := the_plan.descriptor
            )
        ) \
        .when(
            lambda: PinAutoscalerKind().perform(
                PinAutoscaler(application=SOME_APPLICATION), the_plan, the_writes(pin=pin)
            )
        ) \
        .then(_it_leaves(what_it_left))


@pytest.mark.unit
def test_a_pin_to_a_card_is_written_from_the_plan_it_was_handed() -> None:
    # The card travels in the plan. Which card was worked out from where the
    # replicas started before the onset, which the tier never saw - so it was
    # named when the pin was planned, and the write holds the pods to the card
    # the claim recorded rather than to one it is told a second time.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_card_pin_descriptor_for(SOME_APPLICATION)),
            pin_to_accelerator := _a_card_pinner_returning(the_plan.descriptor)
        ) \
        .when(
            lambda: PinToAcceleratorKind().perform(
                a_pin_to(THE_CARD_IT_WAS_HELD_TO), the_plan,
                the_writes(pin_to_accelerator=pin_to_accelerator)
            )
        ) \
        .then(_the_write_was_asked(pin_to_accelerator, the_plan))


@pytest.mark.unit
def test_a_pin_to_a_card_says_which_card_and_what_it_replaced() -> None:
    # Both ends, because an account of a pin is a transition. "Held to the V100"
    # alone reads as though the pods had been held to something else; what it
    # replaced is what a withdrawal puts back.
    Scenario() \
        .given(
            the_plan := a_plan_of(
                a_card_pin_descriptor_for(SOME_APPLICATION, was_pinned_to=None)
            ),
            pin_to_accelerator := _a_card_pinner_returning(the_plan.descriptor)
        ) \
        .when(
            lambda: PinToAcceleratorKind().perform(
                a_pin_to(THE_CARD_IT_WAS_HELD_TO), the_plan,
                the_writes(pin_to_accelerator=pin_to_accelerator)
            )
        ) \
        .then(all_of(
            _it_says(f"[{SOME_APPLICATION}]'s pods to [{THE_CARD_IT_WAS_HELD_TO}]"),
            _it_says("no card")
        ))


@pytest.mark.unit
def test_a_pin_over_another_card_names_the_card_it_replaced() -> None:
    # The other end of the transition, where somebody had already held the pods
    # to a card. Named rather than said as "a card", because that card is what a
    # withdrawal holds them to again.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_card_pin_descriptor_for(
                SOME_APPLICATION, was_pinned_to=A_CARD_SOMEBODY_ELSE_CHOSE
            )),
            pin_to_accelerator := _a_card_pinner_returning(the_plan.descriptor)
        ) \
        .when(
            lambda: PinToAcceleratorKind().perform(
                a_pin_to(THE_CARD_IT_WAS_HELD_TO), the_plan,
                the_writes(pin_to_accelerator=pin_to_accelerator)
            )
        ) \
        .then(_it_says(f"[{A_CARD_SOMEBODY_ELSE_CHOSE}]"))


@pytest.mark.unit
def test_a_pin_to_a_card_leaves_the_way_back_the_write_answered_with() -> None:
    # The card the pods were held to before, and the suspended sync - what a
    # withdrawal lets the pods off the card back to - as the write answered
    # them: the plan as it was handed over, undated.
    Scenario() \
        .given(
            the_plan := a_plan_of(a_card_pin_descriptor_for(
                SOME_APPLICATION, was_pinned_to=A_CARD_SOMEBODY_ELSE_CHOSE
            )),
            pin_to_accelerator := _a_card_pinner_returning(
                what_it_left := the_plan.descriptor
            )
        ) \
        .when(
            lambda: PinToAcceleratorKind().perform(
                a_pin_to(THE_CARD_IT_WAS_HELD_TO), the_plan,
                the_writes(pin_to_accelerator=pin_to_accelerator)
            )
        ) \
        .then(_it_leaves(what_it_left))


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
        SOME_CACHE_KEY,
        "io-shop:summary:shopper-7",
        "io-shop:summary:shopper-9"
    )
    fewer_than_were_named = len(some_keys) - 1

    Scenario() \
        .given(the_store_found_fewer := a_discard_removing(fewer_than_were_named)) \
        .when(
            lambda: DiscardCacheEntriesKind().perform(
                a_discard_of(*some_keys), None, the_writes(discard=the_store_found_fewer)
            )
        ) \
        .then(all_of(
            _it_says(f"[{fewer_than_were_named}]"),
            _it_does_not_say(f"[{len(some_keys)}]")
        ))


@pytest.mark.unit
def test_a_discard_leaves_no_way_back() -> None:
    # The only action that changes something persistent and still owes no undo.
    # A restart records no descriptor because it changed nothing to record; this
    # changed something and there is nothing to restore: the entries were a copy
    # of records it never touched, so writing the old figures back would be
    # recreating the incident.
    dont_care_count = 1

    Scenario() \
        .given(the_store_found_it := a_discard_removing(dont_care_count)) \
        .when(
            lambda: DiscardCacheEntriesKind().perform(
                a_discard_of(SOME_CACHE_KEY), None, the_writes(discard=the_store_found_it)
            )
        ) \
        .then(_it_leaves(None))


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "an_action", "a_plan", "write", "spec"),
                         EVERY_KIND_OF_PLANNED_WRITE)
def test_a_refusal_reaches_whoever_took_the_action_as_the_tier_raised_it(
    kind: UndoableKind[Any], an_action: Callable[[], Action],
    a_plan: Callable[[], Planned[Any]], write: str, spec: type
) -> None:
    # Which refusal it was is what decides the verdict - an exhausted action is
    # passed over, an unreachable platform narrows the walk, anything else
    # escalates - and that is decided by whoever took the action, from the
    # exception's own type. A kind that caught it, or wrapped it, would turn
    # every one of the three into the third.
    dont_care_refusal = "nothing left to do"

    Scenario() \
        .given(
            nothing_left_to_do := _a_collaborator_raising(
                spec, ActionExhausted(an_exhausted_action(dont_care_refusal))
            )
        ) \
        .when(attempting(
            lambda: kind.perform(an_action(), a_plan(),
                                 the_writes(**{write: nothing_left_to_do}))
        )) \
        .then(
            an_error_was_raised(ActionExhausted)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "an_action", "write", "spec"), EVERY_KIND_OF_UNPLANNED_WRITE)
def test_a_refusal_of_an_action_with_no_plan_reaches_whoever_took_it_as_the_tier_raised_it(
    kind: ActionKind[Any, Any], an_action: Callable[[], Action], write: str, spec: type
) -> None:
    # The same, for the two kinds that leave nothing to compare and are
    # performed from no plan at all.
    dont_care_refusal = "nothing left to do"

    Scenario() \
        .given(
            nothing_left_to_do := _a_collaborator_raising(
                spec, ActionExhausted(an_exhausted_action(dont_care_refusal))
            )
        ) \
        .when(attempting(
            lambda: kind.perform(an_action(), None, the_writes(**{write: nothing_left_to_do}))
        )) \
        .then(
            an_error_was_raised(ActionExhausted)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "an_action", "a_plan", "write", "spec"),
                         EVERY_KIND_OF_PLANNED_WRITE)
def test_a_change_made_since_the_plan_reaches_whoever_took_the_action_as_the_tier_raised_it(
    kind: UndoableKind[Any], an_action: Callable[[], Action],
    a_plan: Callable[[], Planned[Any]], write: str, spec: type
) -> None:
    # The refusal that says somebody is acting on the service now. It escalates
    # where an exhausted action is passed over, and the walk tells the two apart
    # by the exception's type - so a kind that caught it, or wrapped it, would
    # have Argus act on the next candidate beside a person already acting.
    dont_care_finding = "the count is [5], and the plan found [3]"

    Scenario() \
        .given(
            somebody_has_been_in_there := _a_collaborator_raising(
                spec, ChangedSince(a_change_made_since(dont_care_finding))
            )
        ) \
        .when(attempting(
            lambda: kind.perform(an_action(), a_plan(),
                                 the_writes(**{write: somebody_has_been_in_there}))
        )) \
        .then(
            an_error_was_raised(ChangedSince)
        )


# ---- what it would have done ----


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "an_action", "expected"), EVERY_INTENT)
def test_each_kind_says_what_it_would_have_done(
    kind: ActionKind[Any, Any], an_action: Callable[[], Action], expected: str
) -> None:
    # Separate from what a performed action says, and different in tense and in
    # what it may claim: this is quoted where nothing happened, and a sentence
    # saying something did would be a record of a change nobody made.
    Scenario() \
        .given(action := an_action()) \
        .when(lambda: kind.intent(action)) \
        .then(the_answer_was(expected))


# ---- how a change was put back ----


@pytest.mark.unit
def test_a_rollback_put_back_says_the_revision_it_was_put_back_to() -> None:
    Scenario() \
        .given(descriptor := a_rollback_descriptor_for(SOME_APPLICATION)) \
        .when(lambda: RollBackDeploymentKind().put_back_as(descriptor)) \
        .then(the_answer_was(f"to revision [{THE_REVISION_IT_WAS_ON}]"))


@pytest.mark.unit
def test_a_scale_out_put_back_says_which_count_it_was_put_back_to() -> None:
    # The count, not "the previous size". A reader picking the incident up has to
    # be able to tell what the deployment is running now without going to the
    # platform to ask, and the figure the tier read is the only honest one -
    # nothing else here ever knew it.
    Scenario() \
        .given(descriptor := a_resize_descriptor_for(SOME_APPLICATION)) \
        .when(lambda: ScaleOutKind().put_back_as(descriptor)) \
        .then(the_answer_was(f"to [{THE_COUNT_IT_WAS_RUNNING}] replicas"))


@pytest.mark.unit
def test_a_scale_out_put_back_to_one_replica_says_one_replica() -> None:
    Scenario() \
        .given(descriptor := a_resize_descriptor_for(SOME_APPLICATION, was_replicas=ONE_REPLICA)) \
        .when(lambda: ScaleOutKind().put_back_as(descriptor)) \
        .then(the_answer_was(f"to [{ONE_REPLICA}] replica"))


@pytest.mark.unit
def test_an_autoscaler_pin_put_back_to_a_floor_of_one_replica_says_one_replica() -> None:
    Scenario() \
        .given(descriptor := a_pin_descriptor_for(SOME_APPLICATION, was_min_replicas=ONE_REPLICA)) \
        .when(lambda: PinAutoscalerKind().put_back_as(descriptor)) \
        .then(the_answer_was(f"to an autoscaler floor of [{ONE_REPLICA}] replica"))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("was_pinned_to", "expected"),
    [
        (None, "to letting its pods run on any card"),
        (A_CARD_SOMEBODY_ELSE_CHOSE, f"to holding its pods to [{A_CARD_SOMEBODY_ELSE_CHOSE}]")
    ],
    ids=["held-to-no-card-before", "held-to-another-card-before"]
)
def test_a_pin_to_a_card_put_back_says_what_it_was_put_back_to(
    was_pinned_to: str | None, expected: str
) -> None:
    # Two different endings and both have to be said. A deployment held to no
    # card before is let go, and its pods may land anywhere again; one somebody
    # else had held to a card is held to that card again - which a sentence
    # saying "let go" would misreport as a pin removed.
    Scenario() \
        .given(
            descriptor := a_card_pin_descriptor_for(SOME_APPLICATION, was_pinned_to=was_pinned_to)
        ) \
        .when(lambda: PinToAcceleratorKind().put_back_as(descriptor)) \
        .then(the_answer_was(expected))


# ---- waiting for a change to arrive ----


@pytest.mark.unit
def test_each_kind_of_action_waits_for_what_it_actually_changes() -> None:
    # Five of the seven actions have nothing to wait for: a flag is in force on
    # the next request because the shop reads it fresh every time, a restart is
    # answered with the new process's start time so the tier that performed it
    # has already waited, an autoscaler's floor is a field on its own object
    # rather than a state anything converges on, a discard is answered with how
    # many entries went, and a pin to a card is in force once the platform holds
    # the selector.
    #
    # The two that do are the two that change a Deployment, and they wait on
    # different counts - a rollback for the revision reaching every replica, a
    # scale-out for the replicas it asked for existing. Asserted together because
    # the claim is that they *differ*: one check for all seven would either make
    # five actions wait for a rollout that is not happening, or let the two that
    # matter be judged on minutes their change was not in.
    #
    # The platform here reports a split fleet at the size it was told to be, which
    # is the one window that tells the two apart - the rollback is still arriving
    # and the capacity is already there.
    a_split_fleet_at_full_size = _a_rollout_reporting(
        wanted=SOME_FLEET_SIZE, serving=SOME_FLEET_SIZE, updated=HALF_THE_FLEET
    )
    every_kind: dict[str, tuple[ActionKind[Any, Any], Action]] = {
        "a rollback": (RollBackDeploymentKind(),
                       RollBackDeployment(application=SOME_APPLICATION)),
        "a scale-out": (ScaleOutKind(), ScaleOut(application=SOME_APPLICATION)),
        "a flag": (RevertFeatureFlagKind(), an_action_setting(SOME_FLAG, enabled=True)),
        "a restart": (RestartServiceKind(), an_action_restarting(SOME_SERVICE)),
        "an autoscaler pin": (PinAutoscalerKind(),
                              PinAutoscaler(application=SOME_APPLICATION)),
        "a pin to a card": (PinToAcceleratorKind(), a_pin_to(THE_CARD_IT_WAS_HELD_TO)),
        "a discard": (DiscardCacheEntriesKind(), a_discard_of(SOME_CACHE_KEY))
    }

    Scenario() \
        .given(a_split_fleet_at_full_size) \
        .when(lambda: {
            name: kind.arrival(action, a_split_fleet_at_full_size)()
            for name, (kind, action) in every_kind.items()
        }) \
        .then(_each_kind_waits_for({
            "a rollback": Arrival.STILL_ARRIVING,
            "a scale-out": Arrival.ARRIVED,
            "a flag": Arrival.ARRIVED,
            "a restart": Arrival.ARRIVED,
            "an autoscaler pin": Arrival.ARRIVED,
            # A selector on the pod template, in force once the platform accepts
            # it. The pods it moves are rescheduled by the platform afterwards,
            # and whether that helped is what the verification watches - it is
            # not a count anything here could wait on.
            "a pin to a card": Arrival.ARRIVED,
            # The keys are gone when the store says they are gone. Nothing
            # converges on their absence and nothing has to be waited for, which
            # is the same answer the flag gets and for the same reason: the
            # change is complete at the moment it is accepted.
            "a discard": Arrival.ARRIVED
        }))


@pytest.mark.unit
def test_an_action_arrives_as_its_own_kind_says() -> None:
    # What the walk binds once over its read tier, before it knows which
    # action it will take. One window that the two answers differ on, so an
    # arrival that asked the wrong kind - or one kind for both - cannot pass.
    a_split_fleet = _a_rollout_reporting(
        wanted=SOME_FLEET_SIZE, serving=SOME_FLEET_SIZE, updated=HALF_THE_FLEET
    )

    Scenario() \
        .given(a_split_fleet) \
        .when(lambda: {
            "a rollback": arrival_of(
                RollBackDeployment(application=SOME_APPLICATION), rollouts=a_split_fleet
            )(),
            "a flag": arrival_of(
                an_action_setting(SOME_FLAG, enabled=True), rollouts=a_split_fleet
            )()
        }) \
        .then(_each_kind_waits_for({
            "a rollback": Arrival.STILL_ARRIVING,
            "a flag": Arrival.ARRIVED
        }))


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "an_action"), EVERY_KIND_WITH_SOMETHING_TO_WAIT_FOR)
def test_the_rollout_asked_about_is_the_one_the_action_changed(
    kind: ActionKind[Any, Any], an_action: Callable[[], Action]
) -> None:
    # The service is the action's, and it is the kind that knows which field of
    # the action names it. A reader asked about anything else would report some
    # other deployment's rollout as this change arriving.
    Scenario() \
        .given(
            rollouts := _a_rollout_reporting(
                wanted=SOME_FLEET_SIZE, serving=SOME_FLEET_SIZE, updated=SOME_FLEET_SIZE
            )
        ) \
        .when(
            lambda: kind.arrival(an_action(), rollouts)()
        ) \
        .then(
            _the_rollout_was_asked_about(rollouts, SOME_APPLICATION)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "an_action"), EVERY_KIND_WITH_SOMETHING_TO_WAIT_FOR)
def test_a_rollout_is_read_afresh_on_every_look(
    kind: ActionKind[Any, Any], an_action: Callable[[], Action]
) -> None:
    # The wait asks the same arrival again and again, and only a fresh read can
    # answer differently. An arrival that read the rollout once and kept the
    # answer would report a fleet still turning over for as long as the wait
    # lasted - and the change would be judged as one that never arrived.
    # Short of the replicas asked for, and not all of those serving on the new
    # revision - so neither count is met, and the window is still arriving for
    # a rollback and a scale-out alike.
    still_turning_over = _a_rollout_of(
        wanted=SOME_FLEET_SIZE, serving=HALF_THE_FLEET + 1, updated=HALF_THE_FLEET
    )
    turned_over = _a_rollout_of(
        wanted=SOME_FLEET_SIZE, serving=SOME_FLEET_SIZE, updated=SOME_FLEET_SIZE
    )

    Scenario() \
        .given(
            has_arrived := kind.arrival(
                an_action(), _rollouts_reading(still_turning_over, turned_over)
            )
        ) \
        .when(
            lambda: [has_arrived(), has_arrived()]
        ) \
        .then(
            _the_looks_answered([Arrival.STILL_ARRIVING, Arrival.ARRIVED])
        )


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
            lambda: RollBackDeploymentKind().arrival(
                RollBackDeployment(application=SOME_APPLICATION), every_replica_has_it
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
            lambda: RollBackDeploymentKind().arrival(
                RollBackDeployment(application=SOME_APPLICATION), half_of_them_have_it
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
            lambda: RollBackDeploymentKind().arrival(
                RollBackDeployment(application=SOME_APPLICATION), the_platform_has_stopped
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
            lambda: RollBackDeploymentKind().arrival(
                RollBackDeployment(application=SOME_APPLICATION), the_platform_has_given_up
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
            lambda: RollBackDeploymentKind().arrival(
                RollBackDeployment(application=SOME_APPLICATION),
                the_whole_fleet_updated_then_held
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
            lambda: ScaleOutKind().arrival(
                ScaleOut(application=SOME_APPLICATION), half_the_capacity_asked_for
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
            lambda: ScaleOutKind().arrival(
                ScaleOut(application=SOME_APPLICATION),
                short_of_what_it_asked_for_and_paused
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
            lambda: ScaleOutKind().arrival(
                ScaleOut(application=SOME_APPLICATION), the_platform_cannot_create_them
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
            lambda: ScaleOutKind().arrival(
                ScaleOut(application=SOME_APPLICATION), the_capacity_is_there
            )()
        ) \
        .then(
            _the_arrival_is(Arrival.ARRIVED)
        )


# ---- putting a change back ----


@pytest.mark.unit
@pytest.mark.parametrize(("dont_care_kind", "a_descriptor", "write", "a_whole_restore"),
                         EVERY_WHOLE_RESTORE)
def test_a_change_is_put_back_by_the_kind_that_made_it(
    dont_care_kind: UndoableKind[Any], a_descriptor: Callable[[], UndoDescriptor], write: str,
    a_whole_restore: Callable[[], MagicMock]
) -> None:
    # `undo_change` is what both callers hold - a refuted action and a withdrawn
    # incident - and all it adds to the kinds below is which of them it asks. A
    # change sent to another kind's undo would reach a write that has nothing to
    # do with it, and every other part of the way back here is a spy nobody calls.
    restore = a_whole_restore()

    Scenario() \
        .given(descriptor := a_descriptor()) \
        .when(
            lambda: undo_change(descriptor, the_way_back(**{write: restore}))
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _the_restore_was_used(restore)
        ))


@pytest.mark.unit
def test_a_flag_nobody_touched_is_put_back() -> None:
    set_state = _a_flag_setter()

    Scenario() \
        .given(
            descriptor := an_undo_descriptor_for(SOME_FLAG, was_enabled=True)
        ) \
        .when(
            lambda: RevertFeatureFlagKind().undo(descriptor, the_way_back(set_state=set_state))
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _the_flag_was_set_to(set_state, SOME_FLAG, enabled=True)
        ))


@pytest.mark.unit
def test_a_flag_somebody_changed_is_left_as_found() -> None:
    # The case a value comparison gets wrong. The flag may well still read as
    # what Argus wrote - the provider's evaluation is a cache, and a change made
    # a moment ago has not reached it - but the record says somebody has been in
    # there, and their change is not Argus's to overwrite.
    set_state = _a_flag_setter()

    Scenario() \
        .given(
            descriptor := an_undo_descriptor_for(SOME_FLAG, was_enabled=True)
        ) \
        .when(
            lambda: RevertFeatureFlagKind().undo(
                descriptor,
                the_way_back(set_state=set_state, changed_from_outside=somebody_changed_it())
            )
        ) \
        .then(all_of(
            _it_reports(Undone.LEFT_AS_FOUND),
            _nothing_was_written(set_state),
            _it_says_exactly("was left as found: it has been changed from outside since "
                             "Argus set it")
        ))


@pytest.mark.unit
def test_a_descriptor_that_does_not_say_when_argus_wrote_is_not_acted_on() -> None:
    # Rows written before the descriptor carried the moment. Guessing from the
    # current value is the failure this whole check exists to remove, so an
    # answer nobody can date is one of the three answers rather than a restore.
    set_state = _a_flag_setter()

    Scenario() \
        .given(
            a_descriptor_from_before := an_undated_flag_change_for(SOME_FLAG)
        ) \
        .when(
            lambda: RevertFeatureFlagKind().undo(
                a_descriptor_from_before, the_way_back(set_state=set_state)
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _nothing_was_written(set_state)
        ))


@pytest.mark.unit
def test_a_record_that_cannot_be_read_is_not_written_over() -> None:
    # "Nobody can say" and "nobody changed it" are opposite facts, and the whole
    # value of this check is the difference between them.
    set_state = _a_flag_setter()

    Scenario() \
        .given(
            descriptor := an_undo_descriptor_for(SOME_FLAG, was_enabled=True)
        ) \
        .when(
            lambda: RevertFeatureFlagKind().undo(
                descriptor,
                the_way_back(set_state=set_state, changed_from_outside=nobody_can_say())
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _nothing_was_written(set_state)
        ))


@pytest.mark.unit
def test_the_record_is_asked_about_from_the_moment_argus_wrote() -> None:
    # Not from the moment of the undo, and not from a lookback window: a change
    # made before Argus wrote is not somebody overriding Argus, and asking from
    # anywhere but the write would count it as one.
    the_moment_argus_wrote = ACTION_TIME
    asked = _a_record_asked_about(answering=False)

    Scenario() \
        .given(
            descriptor := an_undo_descriptor_for(
                SOME_FLAG, was_enabled=True, written_at=the_moment_argus_wrote)
        ) \
        .when(
            lambda: RevertFeatureFlagKind().undo(
                descriptor, the_way_back(changed_from_outside=asked.record)
            )
        ) \
        .then(
            _it_was_asked_from(asked, the_moment_argus_wrote)
        )


@pytest.mark.unit
def test_a_flag_put_back_says_what_became_of_it_and_nothing_else() -> None:
    # What the line says after the flag's name. The name is the subject the
    # narration already leads with, and the state is the one fact left to say.
    Scenario() \
        .given(
            descriptor := an_undo_descriptor_for(SOME_FLAG, was_enabled=True)
        ) \
        .when(
            lambda: RevertFeatureFlagKind().undo(descriptor, the_way_back())
        ) \
        .then(
            _it_says_exactly("was put back ON")
        )


@pytest.mark.unit
def test_a_rollback_is_put_back_by_the_restorer_rather_than_the_flag_setter() -> None:
    # Several kinds of change share the way back, and the one that is not a flag
    # must not reach the part that writes flags - which, before the descriptor
    # was a union, is exactly what would have happened.
    set_state = _a_flag_setter()

    Scenario() \
        .given(
            descriptor := a_rollback_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: RollBackDeploymentKind().undo(
                descriptor,
                the_way_back(set_state=set_state,
                             restore_deployment=_a_restorer_that_puts_back())
            )
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _nothing_was_written(set_state)
        ))


@pytest.mark.unit
def test_a_rollback_put_back_reports_the_application_as_its_subject() -> None:
    # An unwind holds several answers at once and has to say which is which.
    # A rollback is about an application, where a flag revert is about a flag.
    Scenario() \
        .given(
            descriptor := a_rollback_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: RollBackDeploymentKind().undo(
                descriptor, the_way_back(restore_deployment=_a_restorer_that_puts_back())
            )
        ) \
        .then(
            _it_is_about(SOME_APPLICATION)
        )


@pytest.mark.unit
def test_a_rollback_whose_sync_could_not_be_restored_is_not_counted_as_undone() -> None:
    # The half that is easy to lose. The revision is back, so the deployment
    # looks right - and it is silently receiving nothing anybody ships to it,
    # because the reconciliation Argus suspended is still suspended. Reported
    # as not established, which is what escalates it to somebody.
    Scenario() \
        .given(
            descriptor := a_rollback_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: RollBackDeploymentKind().undo(
                descriptor,
                the_way_back(restore_deployment=_a_restorer_that_puts_back(
                    revision=True, automated_sync=False
                ))
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed("automated sync")
        ))


@pytest.mark.unit
def test_a_restorer_that_raises_leaves_the_rollback_not_established() -> None:
    # Nothing raises out of an undo. An unwind runs over every change an
    # incident made, and one deployment nobody can reach must not stop the
    # others being put back.
    some_failure = "the platform refused"

    Scenario() \
        .given(
            descriptor := a_rollback_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: RollBackDeploymentKind().undo(
                descriptor,
                the_way_back(restore_deployment=_a_collaborator_raising(
                    DeploymentRestorer, RuntimeError(some_failure)
                ))
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed(some_failure)
        ))


@pytest.mark.unit
def test_a_scale_out_is_put_back_by_the_capacity_restorer_and_nothing_else() -> None:
    # A resize sent to something that writes flags would be an undo writing to
    # the wrong system, and one sent to the deployment restorer would put a
    # *revision* back on a deployment whose revision nobody touched.
    set_state = _a_flag_setter()
    restore_deployment = a_restorer_nobody_calls()

    Scenario() \
        .given(
            descriptor := a_resize_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: ScaleOutKind().undo(
                descriptor,
                the_way_back(set_state=set_state,
                             restore_deployment=restore_deployment,
                             restore_capacity=_a_capacity_restorer_that_puts_back())
            )
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _nothing_was_written(set_state),
            _the_restorer_was_not_asked(restore_deployment, "the deployment restorer")
        ))


@pytest.mark.unit
def test_a_scale_out_put_back_reports_the_application_as_its_subject() -> None:
    Scenario() \
        .given(
            descriptor := a_resize_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: ScaleOutKind().undo(
                descriptor, the_way_back(restore_capacity=_a_capacity_restorer_that_puts_back())
            )
        ) \
        .then(
            _it_is_about(SOME_APPLICATION)
        )


@pytest.mark.unit
def test_a_scale_out_put_back_says_the_count_and_the_reconciliation_both_went() -> None:
    # Both halves in the sentence, because both were changed and a reader has
    # only this line. A withdrawal that said "the deployment was put back" would
    # leave the one silently damaging outcome unreadable: a deployment at its
    # declared size that the platform is no longer reconciling looks right from
    # every angle and receives nothing anybody ships to it.
    Scenario() \
        .given(
            descriptor := a_resize_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: ScaleOutKind().undo(
                descriptor, the_way_back(restore_capacity=_a_capacity_restorer_that_puts_back())
            )
        ) \
        .then(all_of(
            _it_says_what_is_still_changed(f"[{THE_COUNT_IT_WAS_RUNNING}] replicas"),
            _it_says_what_is_still_changed("automated sync was restored")
        ))


@pytest.mark.unit
def test_a_resize_whose_sync_could_not_be_restored_is_not_counted_as_undone() -> None:
    # The quiet half. A deployment back at its declared size while the platform
    # is still not reconciling it looks right from every angle a reader has, and
    # receives nothing anybody ships to it.
    Scenario() \
        .given(
            descriptor := a_resize_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: ScaleOutKind().undo(
                descriptor,
                the_way_back(restore_capacity=_a_capacity_restorer_that_puts_back(
                    count=True, automated_sync=False
                ))
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed("automated sync")
        ))


@pytest.mark.unit
def test_a_capacity_restorer_that_raises_leaves_the_resize_not_established() -> None:
    some_failure = "the platform would not answer"

    Scenario() \
        .given(
            descriptor := a_resize_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: ScaleOutKind().undo(
                descriptor,
                the_way_back(restore_capacity=_a_collaborator_raising(
                    CapacityRestorer, RuntimeError(some_failure)
                ))
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed(some_failure)
        ))


@pytest.mark.unit
def test_a_scale_out_from_one_replica_put_back_says_one_replica() -> None:
    # The count agrees with its noun: "[1] replicas" is the line a reader
    # stops at.
    Scenario() \
        .given(descriptor := a_resize_descriptor_for(SOME_APPLICATION, was_replicas=ONE_REPLICA)) \
        .when(
            lambda: ScaleOutKind().undo(
                descriptor, the_way_back(restore_capacity=_a_capacity_restorer_that_puts_back())
            )
        ) \
        .then(_it_says_what_is_still_changed(f"put back to [{ONE_REPLICA}] replica, and"))


@pytest.mark.unit
def test_a_scale_out_from_one_replica_that_could_not_be_put_back_says_one_replica() -> None:
    Scenario() \
        .given(descriptor := a_resize_descriptor_for(SOME_APPLICATION, was_replicas=ONE_REPLICA)) \
        .when(
            lambda: ScaleOutKind().undo(
                descriptor,
                the_way_back(restore_capacity=_a_collaborator_raising(CapacityRestorer))
            )
        ) \
        .then(_it_says_what_is_still_changed(f"put back to [{ONE_REPLICA}] replica:"))


@pytest.mark.unit
def test_a_pin_is_put_back_by_the_autoscaling_restorer_and_nothing_else() -> None:
    # A pin sent to the capacity restorer would put a replica *count* back on a
    # deployment whose count Argus never set: the two act on the same number,
    # and only one of them wrote it.
    set_state = _a_flag_setter()
    restore_capacity = a_capacity_restorer_nobody_calls()

    Scenario() \
        .given(
            descriptor := a_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: PinAutoscalerKind().undo(
                descriptor,
                the_way_back(set_state=set_state,
                             restore_capacity=restore_capacity,
                             restore_autoscaling=_an_autoscaling_restorer_that_puts_back())
            )
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _nothing_was_written(set_state),
            _the_restorer_was_not_asked(restore_capacity, "the capacity restorer")
        ))


@pytest.mark.unit
def test_a_pin_put_back_reports_the_application_as_its_subject() -> None:
    # An unwind holds several answers at once and has to say which is which. A
    # pin is about an application, as a rollback and a resize are.
    Scenario() \
        .given(
            descriptor := a_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: PinAutoscalerKind().undo(
                descriptor,
                the_way_back(restore_autoscaling=_an_autoscaling_restorer_that_puts_back())
            )
        ) \
        .then(
            _it_is_about(SOME_APPLICATION)
        )


@pytest.mark.unit
def test_a_pin_whose_sync_could_not_be_restored_is_not_counted_as_undone() -> None:
    # The half that is easy to lose, and the same half a rollback and a resize
    # can lose. The floor is back, so the controller is free to move again - and
    # the deployment is silently receiving nothing anybody ships to it, because
    # the reconciliation Argus suspended is still suspended.
    Scenario() \
        .given(
            descriptor := a_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: PinAutoscalerKind().undo(
                descriptor,
                the_way_back(restore_autoscaling=_an_autoscaling_restorer_that_puts_back(
                    floor=True, automated_sync=False
                ))
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed("automated sync")
        ))


@pytest.mark.unit
def test_an_autoscaling_restorer_that_raises_leaves_the_pin_not_established() -> None:
    some_failure = "the platform would not answer"

    Scenario() \
        .given(
            descriptor := a_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: PinAutoscalerKind().undo(
                descriptor,
                the_way_back(restore_autoscaling=_a_collaborator_raising(
                    AutoscalingRestorer, RuntimeError(some_failure)
                ))
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed(some_failure)
        ))


@pytest.mark.unit
def test_a_pin_to_a_card_is_put_back_by_its_own_restorer_and_nothing_else() -> None:
    # A pin to a card sent to the autoscaling restorer would write a floor onto
    # a deployment whose floor Argus never set: both are pins, and only one of
    # them wrote that field.
    restore_autoscaling = an_autoscaling_restorer_nobody_calls()

    Scenario() \
        .given(
            descriptor := a_card_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: PinToAcceleratorKind().undo(
                descriptor,
                the_way_back(
                    restore_autoscaling=restore_autoscaling,
                    restore_accelerator_pin=_an_accelerator_pin_restorer_that_puts_back()
                )
            )
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _it_is_about(SOME_APPLICATION),
            _the_restorer_was_not_asked(restore_autoscaling, "the autoscaling restorer")
        ))


@pytest.mark.unit
def test_a_pin_to_a_card_whose_sync_could_not_be_restored_is_not_counted_as_undone() -> None:
    # The same half every action under a GitOps controller can lose. The pods
    # may land on any card again, and the deployment is silently receiving
    # nothing anybody ships to it.
    Scenario() \
        .given(
            descriptor := a_card_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: PinToAcceleratorKind().undo(
                descriptor,
                the_way_back(
                    restore_accelerator_pin=_an_accelerator_pin_restorer_that_puts_back(
                        pin=True, automated_sync=False
                    )
                )
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed("automated sync")
        ))


@pytest.mark.unit
def test_an_accelerator_pin_restorer_that_raises_leaves_the_pin_not_established() -> None:
    some_failure = "the platform would not answer"

    Scenario() \
        .given(
            descriptor := a_card_pin_descriptor_for(SOME_APPLICATION)
        ) \
        .when(
            lambda: PinToAcceleratorKind().undo(
                descriptor,
                the_way_back(restore_accelerator_pin=_a_collaborator_raising(
                    AcceleratorPinRestorer, RuntimeError(some_failure)
                ))
            )
        ) \
        .then(all_of(
            _it_reports(Undone.NOT_ESTABLISHED),
            _it_says_what_is_still_changed(some_failure)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "a_descriptor", "write", "spec", "an_answer"),
                         EVERY_CHANGE_SOMEBODY_COULD_MAKE_THEIR_OWN)
def test_a_change_somebody_made_their_own_while_argus_s_suspension_stands_is_left_standing(
    kind: UndoableKind[Any], a_descriptor: Callable[[bool], UndoDescriptor], write: str,
    spec: type, an_answer: Callable[[str, bool], object]
) -> None:
    # Neither put back nor simply left: the subject is theirs now, and the
    # reconciliation Argus suspended is still suspended - resuming it would
    # have the platform re-apply git over them. Something of Argus's is still
    # in place, so a person has to decide it, and the sentence says why.
    Scenario() \
        .given(
            putting_back := the_way_back(**{
                write: _a_collaborator_answering(spec, an_answer(SOME_FINDING, True))
            })
        ) \
        .when(
            lambda: kind.undo(a_descriptor(True), putting_back)
        ) \
        .then(all_of(
            _it_reports(Undone.LEFT_STANDING),
            _it_says_what_is_still_changed(SOME_FINDING),
            _it_says_what_is_still_changed("left as they set it"),
            _it_says_what_is_still_changed("suspended still stands")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "a_descriptor", "write", "spec", "an_answer"),
                         EVERY_CHANGE_SOMEBODY_COULD_MAKE_THEIR_OWN)
@pytest.mark.parametrize("was_syncing_itself", [True, False],
                         ids=["argus-suspended-sync", "sync-was-off-before-argus"])
def test_a_change_somebody_made_their_own_with_nothing_of_argus_s_standing_is_left_as_found(
    kind: UndoableKind[Any], a_descriptor: Callable[[bool], UndoDescriptor], write: str,
    spec: type, an_answer: Callable[[str, bool], object], was_syncing_itself: bool
) -> None:
    # Whatever Argus found: sync off before Argus came was never Argus's to
    # resume, and a person who reverted in git and turned sync back on has
    # ended Argus's suspension themselves. The write tier, which read the
    # platform, says which - so nothing of Argus's is left, and the change is
    # left as found.
    Scenario() \
        .given(
            putting_back := the_way_back(**{
                write: _a_collaborator_answering(spec, an_answer(SOME_FINDING, False))
            })
        ) \
        .when(
            lambda: kind.undo(a_descriptor(was_syncing_itself), putting_back)
        ) \
        .then(all_of(
            _it_reports(Undone.LEFT_AS_FOUND),
            _it_says_exactly(f"was left as found: {SOME_FINDING}")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "a_descriptor", "write", "spec", "nothing_back"), [
    pytest.param(RollBackDeploymentKind(), lambda: a_rollback_descriptor_for(SOME_APPLICATION),
                 "restore_deployment", DeploymentRestorer,
                 lambda: DeploymentRestored(revision_put_back=False,
                                            automated_sync_put_back=False),
                 id="rollback"),
    pytest.param(ScaleOutKind(), lambda: a_resize_descriptor_for(SOME_APPLICATION),
                 "restore_capacity", CapacityRestorer,
                 lambda: CapacityRestored(count_put_back=False, automated_sync_put_back=False),
                 id="scale-out"),
    pytest.param(PinAutoscalerKind(), lambda: a_pin_descriptor_for(SOME_APPLICATION),
                 "restore_autoscaling", AutoscalingRestorer,
                 lambda: AutoscalingRestored(floor_put_back=False, automated_sync_put_back=False),
                 id="autoscaler-pin"),
    pytest.param(PinToAcceleratorKind(), lambda: a_card_pin_descriptor_for(SOME_APPLICATION),
                 "restore_accelerator_pin", AcceleratorPinRestorer,
                 lambda: AcceleratorPinRestored(pin_put_back=False, automated_sync_put_back=False),
                 id="card-pin")
])
def test_a_change_the_write_tier_could_not_read_is_not_established(
    kind: UndoableKind[Any], a_descriptor: Callable[[], UndoDescriptor], write: str,
    spec: type, nothing_back: Callable[[], object]
) -> None:
    # What a write tier answers where a read its check needed never came back:
    # nothing written, neither half back, nothing found. Not left as found -
    # nobody established that anybody changed anything - and not restored, so
    # somebody is told the change may still be out there.
    Scenario() \
        .given(
            putting_back := the_way_back(**{write: _a_collaborator_answering(spec, nothing_back())})
        ) \
        .when(
            lambda: kind.undo(a_descriptor(), putting_back)
        ) \
        .then(
            _it_reports(Undone.NOT_ESTABLISHED)
        )


@pytest.mark.unit
@pytest.mark.parametrize("was_syncing_itself", [True, False],
                         ids=["argus-suspended-sync", "sync-was-off-before-argus"])
def test_a_count_left_to_its_autoscaler_is_put_back_and_says_so(
    was_syncing_itself: bool
) -> None:
    # The count is the controller's, and was never Argus's to write back: what
    # was Argus's is the sync, and that was put back where it was suspended. So
    # the change is restored, and the sentence says the count went to the
    # autoscaler rather than naming a number nobody wrote.
    Scenario() \
        .given(
            descriptor := a_resize_descriptor_for(SOME_APPLICATION,
                                                  was_syncing_itself=was_syncing_itself)
        ) \
        .when(
            lambda: ScaleOutKind().undo(
                descriptor,
                the_way_back(restore_capacity=_a_collaborator_answering(
                    CapacityRestorer,
                    CapacityRestored(count_put_back=True, automated_sync_put_back=True,
                                     count_left_to_its_autoscaler=True)
                ))
            )
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _it_says_what_is_still_changed("left to its autoscaler"),
            # And the account of the refutation says the same, rather than the
            # kind's usual ending, which names a count nobody wrote back.
            _it_is_said_as("left to its autoscaler")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "a_descriptor", "write", "a_whole_restore"),
                         EVERY_WHOLE_RESTORE)
def test_a_change_put_back_does_not_name_its_subject_again(
    kind: UndoableKind[Any], a_descriptor: Callable[[], UndoDescriptor], write: str,
    a_whole_restore: Callable[[], MagicMock]
) -> None:
    # The narration leads with the subject and follows it with this, so a
    # detail that named it again said it twice on one line.
    Scenario() \
        .given(
            putting_back := the_way_back(**{write: a_whole_restore()})
        ) \
        .when(
            lambda: kind.undo(a_descriptor(), putting_back)
        ) \
        .then(all_of(
            _it_reports(Undone.RESTORED),
            _it_does_not_name_its_subject()
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "a_descriptor", "the_way_back_handed"),
                         EVERY_ANSWER_BUT_A_RESTORE)
def test_a_change_not_put_back_does_not_name_its_subject_again(
    kind: UndoableKind[Any], a_descriptor: Callable[[], UndoDescriptor],
    the_way_back_handed: Callable[[], PuttingBack]
) -> None:
    # Said as a restore is: the narration leads with the subject and follows it
    # with this, verb and all - a write that failed could not be put back, one
    # half done was only partly put back - so a detail naming the subject again
    # said it twice on one line.
    Scenario() \
        .given(
            handed := the_way_back_handed()
        ) \
        .when(
            lambda: kind.undo(a_descriptor(), handed)
        ) \
        .then(
            _it_does_not_name_its_subject()
        )


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "a_descriptor", "write", "spec", "subject"),
                         EVERY_KIND_OF_RESTORE)
def test_a_restore_that_raised_is_logged_as_a_warning(
    kind: UndoableKind[Any], a_descriptor: Callable[[], UndoDescriptor], write: str, spec: type,
    subject: str, caplog: pytest.LogCaptureFixture
) -> None:
    # The answer says not established and whoever asked escalates on it, and
    # neither of those carries the traceback - the one thing that says why.
    Scenario() \
        .given(
            the_restore_raises := _a_collaborator_raising(spec)
        ) \
        .when(
            lambda: kind.undo(a_descriptor(), the_way_back(**{write: the_restore_raises}))
        ) \
        .then(
            one_record_was_logged(caplog, THE_KINDS, logging.WARNING, "restore failed",
                                  values={"subject": subject}, failure=RuntimeError)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "a_descriptor", "write", "spec", "dont_care_subject"),
                         EVERY_KIND_OF_RESTORE)
def test_a_restore_refused_because_the_run_was_lost_is_raised_rather_than_answered(
    kind: UndoableKind[Any], a_descriptor: Callable[[], UndoDescriptor], write: str, spec: type,
    dont_care_subject: str
) -> None:
    # Not established would have whoever asked escalate an incident another
    # claim is walking - and a change put back from here would be put back
    # under the walk that holds it now.
    dont_care_why = "a newer claim holds this run"

    Scenario() \
        .given(
            the_run_was_lost := _a_collaborator_raising(spec, RunLost(dont_care_why))
        ) \
        .when(attempting(
            lambda: kind.undo(a_descriptor(), the_way_back(**{write: the_run_was_lost}))
        )) \
        .then(
            an_error_was_raised(RunLost)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "a_descriptor", "write", "half_a_restore"),
                         EVERY_HALF_RESTORE)
def test_a_change_only_partly_put_back_is_logged_as_a_warning(
    kind: UndoableKind[Any], a_descriptor: Callable[[], UndoDescriptor], write: str,
    half_a_restore: Callable[[], MagicMock],
    caplog: pytest.LogCaptureFixture
) -> None:
    # A deployment that looks right and receives nothing anybody ships to it,
    # which nobody looking at it would notice.
    Scenario() \
        .given(
            putting_back := the_way_back(**{write: half_a_restore()})
        ) \
        .when(
            lambda: kind.undo(a_descriptor(), putting_back)
        ) \
        .then(
            one_record_was_logged(caplog, THE_KINDS, logging.WARNING,
                                  "change only partly put back",
                                  values={"subject": SOME_APPLICATION,
                                          "still_changed": "automated sync"})
        )


@pytest.mark.unit
def test_a_flag_change_that_does_not_say_when_argus_wrote_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    Scenario() \
        .given(
            a_descriptor_from_before := an_undated_flag_change_for(SOME_FLAG)
        ) \
        .when(
            lambda: RevertFeatureFlagKind().undo(a_descriptor_from_before, the_way_back())
        ) \
        .then(
            one_record_was_logged(caplog, THE_KINDS, logging.WARNING,
                                  "flag change carries no write time",
                                  values={"subject": SOME_FLAG})
        )


@pytest.mark.unit
def test_a_record_that_cannot_be_read_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    Scenario() \
        .given(
            putting_back := the_way_back(changed_from_outside=nobody_can_say())
        ) \
        .when(
            lambda: RevertFeatureFlagKind().undo(
                an_undo_descriptor_for(SOME_FLAG, was_enabled=True), putting_back
            )
        ) \
        .then(
            one_record_was_logged(caplog, THE_KINDS, logging.WARNING,
                                  "outside change could not be established",
                                  values={"subject": SOME_FLAG})
        )


@pytest.mark.unit
def test_a_flag_left_as_found_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # Nothing was written, so the write server says nothing - and a flag Argus
    # changed and then deliberately left is the one thing a person should know
    # before they go looking for it.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            putting_back := the_way_back(changed_from_outside=somebody_changed_it())
        ) \
        .when(
            lambda: RevertFeatureFlagKind().undo(
                an_undo_descriptor_for(SOME_FLAG, was_enabled=True), putting_back
            )
        ) \
        .then(
            one_record_was_logged(caplog, THE_KINDS, logging.INFO, "flag left as found",
                                  values={"subject": SOME_FLAG})
        )


class _ARecordAskedAbout:
    """The question the undo asked, kept so a test can assert on it."""

    def __init__(self, answering: bool) -> None:
        self.asked_about: tuple[str, datetime] | None = None
        self._answer = answering

    def record(self, flag: str, since: datetime) -> bool | None:
        self.asked_about = (flag, since)

        return self._answer


def a_pin_to(card: str) -> PinToAccelerator:
    return PinToAccelerator(application=SOME_APPLICATION, accelerator=card)


def a_discard_of(*keys: str) -> DiscardCacheEntries:
    return DiscardCacheEntries(service=SOME_APPLICATION, keys=keys)


def an_undated_flag_change_for(flag: str) -> FlagUndo:
    """A flag change recorded before the descriptor carried the moment Argus
    wrote it - which `an_undo_descriptor_for` cannot build, since it always
    dates one."""
    return FlagUndo(flag=flag, was_enabled=True, environment="production")


def a_planned_flag_change_for(flag: str, was_enabled: bool) -> FlagUndo:
    """A flag change as a plan holds it: the state found, and no moment of a
    write - nothing has been written yet - and no environment, which only the
    provider's answer to a write names."""
    return FlagUndo(flag=flag, was_enabled=was_enabled)


def _as_written(planned: FlagUndo) -> FlagUndo:
    """What the flag's write answers with: the change it was handed, dated by
    the moment it landed. The flag's alone - a deployment's write answers with
    the plan as it was handed over, undated."""
    return planned.model_copy(update={"written_at": THE_WRITE_LANDED_AT})


def a_rollback_descriptor_for(application: str,
                              was_syncing_itself: bool = True) -> DeploymentRollbackUndo:
    return DeploymentRollbackUndo(
        application=application,
        was_on_history_id=2,
        was_on_revision=THE_REVISION_IT_WAS_ON,
        rolled_back_to_revision=THE_REVISION_IT_ROLLED_BACK_TO,
        was_syncing_itself=was_syncing_itself
    )


def a_resize_descriptor_for(application: str,
                            was_syncing_itself: bool = True,
                            was_replicas: int = THE_COUNT_IT_WAS_RUNNING) -> ReplicaUndo:
    return ReplicaUndo(
        application=application,
        was_replicas=was_replicas,
        replicas_asked_for=was_replicas * 2,
        was_syncing_itself=was_syncing_itself
    )


def a_pin_descriptor_for(application: str,
                         was_syncing_itself: bool = True,
                         was_min_replicas: int = THE_FLOOR_IT_WAS_HOLDING) -> AutoscalerUndo:
    return AutoscalerUndo(
        application=application,
        was_min_replicas=was_min_replicas,
        min_replicas_asked_for=THE_CEILING_IT_WAS_HELD_AT,
        was_syncing_itself=was_syncing_itself
    )


def a_card_pin_descriptor_for(application: str,
                              was_pinned_to: str | None = None,
                              was_syncing_itself: bool = True) -> AcceleratorPinUndo:
    return AcceleratorPinUndo(
        application=application,
        was_pinned_to=was_pinned_to,
        pinned_to=THE_CARD_IT_WAS_HELD_TO,
        was_syncing_itself=was_syncing_itself
    )


def _a_deployment_left(found: str, still_suspended: bool) -> DeploymentRestored:
    """A rollback the write tier left as somebody set it: nothing written."""
    return DeploymentRestored(revision_put_back=False, automated_sync_put_back=False,
                              left_because=found, sync_still_suspended=still_suspended)


def _a_capacity_left(found: str, still_suspended: bool) -> CapacityRestored:
    """A scale-out the write tier left as somebody set it: nothing written."""
    return CapacityRestored(count_put_back=False, automated_sync_put_back=False,
                            left_because=found, sync_still_suspended=still_suspended)


def _an_autoscaling_left(found: str, still_suspended: bool) -> AutoscalingRestored:
    """An autoscaler pin the write tier left as somebody set it: nothing written."""
    return AutoscalingRestored(floor_put_back=False, automated_sync_put_back=False,
                               left_because=found, sync_still_suspended=still_suspended)


def _an_accelerator_pin_left(found: str, still_suspended: bool) -> AcceleratorPinRestored:
    """A pin to a card the write tier left as somebody set it: nothing written."""
    return AcceleratorPinRestored(pin_put_back=False, automated_sync_put_back=False,
                                  left_because=found, sync_still_suspended=still_suspended)


def _a_collaborator_answering(spec: type, answer: object) -> MagicMock:
    """`spec`, answering `answer` however it is asked."""
    collaborator: MagicMock = create_autospec(spec, instance=True)
    collaborator.return_value = answer

    return collaborator


def _a_flag_setter() -> MagicMock:
    return _a_flag_setter_answering(an_undo_descriptor_for(SOME_FLAG))


def _a_flag_setter_answering(descriptor: UndoDescriptor) -> MagicMock:
    """Answers as the real setter does - with the descriptor that would put the
    change back.

    Specced without `instance=True`, unlike the other doubles here: an instance
    autospec of a `Protocol` keeps `self` in its `__call__` signature, and
    `assert_called_once_with` then fails on calls that print identically."""
    setter: MagicMock = create_autospec(FlagSetter)
    setter.return_value = descriptor

    return setter


def _a_planned_flag_setter_answering(descriptor: UndoDescriptor) -> MagicMock:
    """Answers as the real write does - with the descriptor that would put the
    change back.

    Specced without `instance=True`, for the reason `_a_flag_setter_answering`
    gives."""
    setter: MagicMock = create_autospec(PlannedFlagSetter)
    setter.return_value = descriptor

    return setter


def _a_restarter_bringing_up(service: str) -> MagicMock:
    """Answers as the real restarter does - with the process that came up. The
    start time is arbitrary: what makes a restart checkable is that it moved."""
    dont_care_start_time = 1_756_000_600.0
    restart: MagicMock = create_autospec(ServiceRestarter, instance=True)
    restart.return_value = RestartedService(
        service=service, process_start_time_seconds=dont_care_start_time
    )

    return restart


def _a_roller_returning(descriptor: DeploymentRollbackUndo) -> MagicMock:
    roll_back: MagicMock = create_autospec(DeploymentRoller, instance=True)
    roll_back.return_value = descriptor

    return roll_back


def _a_scaler_returning(descriptor: ReplicaUndo) -> MagicMock:
    scale_out: MagicMock = create_autospec(DeploymentScaler, instance=True)
    scale_out.return_value = descriptor

    return scale_out


def _a_pinner_returning(descriptor: AutoscalerUndo) -> MagicMock:
    pin: MagicMock = create_autospec(AutoscalerPinner, instance=True)
    pin.return_value = descriptor

    return pin


def _a_card_pinner_returning(descriptor: AcceleratorPinUndo) -> MagicMock:
    pin: MagicMock = create_autospec(AcceleratorPinner, instance=True)
    pin.return_value = descriptor

    return pin


def _a_record_asked_about(answering: bool) -> _ARecordAskedAbout:
    return _ARecordAskedAbout(answering)


def _it_is_a(expected: type) -> Assertion[object]:
    def assertion(kind: object) -> bool:
        if not isinstance(kind, expected):
            raise AssertionError(
                f"Expected a [{expected.__name__}], got [{type(kind).__name__}]."
            )

        return True

    return assertion


def _the_write_was_asked(write: MagicMock, *expected: object) -> Assertion[Performed]:
    """`call_args_list` compared directly rather than `assert_called_once_with`:
    an autospec of a `Protocol` keeps `self` in its signature, and the assertion
    methods then fail on calls that print identically."""
    def assertion(dont_care_performed: Performed) -> bool:
        if write.call_args_list != [call(*expected)]:
            raise AssertionError(
                f"Expected the write to be asked once for {list(expected)}, got "
                f"{write.call_args_list}"
            )

        return True

    return assertion


def _the_planner_was_asked(planner: MagicMock, *expected: object) -> Assertion[Planned[Any]]:
    """`call_args_list` compared directly, for the reason `_the_write_was_asked`
    gives."""
    def assertion(dont_care_plan: Planned[Any]) -> bool:
        if planner.call_args_list != [call(*expected)]:
            raise AssertionError(
                f"Expected the plan to be asked for once for {list(expected)}, got "
                f"{planner.call_args_list}"
            )

        return True

    return assertion


def _it_is_the_plan(expected: Planned[Any]) -> Assertion[Planned[Any]]:
    def assertion(planned: Planned[Any]) -> bool:
        if planned != expected:
            raise AssertionError(f"Expected the plan [{expected}], got [{planned}].")

        return True

    return assertion


def _nothing_was_written_through(writes: PerformingWrites) -> Assertion[object]:
    """None of the writes in the bundle asked - every one a spy, so a plan, or a
    question whether a change is still Argus's, that wrote anything at all, of
    any kind, is caught here."""
    def assertion(dont_care_answer: object) -> bool:
        every_write: dict[str, object] = {
            "set_state": writes.set_state,
            "restart": writes.restart,
            "roll_back": writes.roll_back,
            "scale_out": writes.scale_out,
            "pin": writes.pin,
            "discard": writes.discard,
            "pin_to_accelerator": writes.pin_to_accelerator
        }
        written = {
            name: cast(MagicMock, write).call_args_list
            for name, write in every_write.items()
            if cast(MagicMock, write).called
        }

        if written:
            raise AssertionError(f"Expected a plan to write nothing, and it wrote {written}")

        return True

    return assertion


def _it_says(mentioned: str) -> Assertion[Performed]:
    def assertion(performed: Performed) -> bool:
        if mentioned not in performed.said:
            raise AssertionError(
                f"Expected what was done to mention [{mentioned}], got [{performed.said}]."
            )

        return True

    return assertion


def _it_does_not_say(forbidden: str) -> Assertion[Performed]:
    def assertion(performed: Performed) -> bool:
        if forbidden in performed.said:
            raise AssertionError(
                f"Expected what was done not to mention [{forbidden}], got "
                f"[{performed.said}]."
            )

        return True

    return assertion


def _it_leaves(expected: UndoDescriptor | None) -> Assertion[Performed]:
    def assertion(performed: Performed) -> bool:
        if performed.undo_descriptor != expected:
            raise AssertionError(
                f"Expected the way back [{expected}], got [{performed.undo_descriptor}]."
            )

        return True

    return assertion


def _it_reports(expected: Undone) -> Assertion[UndoAttempt]:
    def assertion(attempt: UndoAttempt) -> bool:
        if attempt.outcome is not expected:
            raise AssertionError(
                f"Expected the undo to report [{expected}], got "
                f"[{attempt.outcome}]: {attempt.detail}."
            )

        return True

    return assertion


def _the_flag_was_set_to(set_state: MagicMock,
                         flag: str,
                         enabled: bool) -> Assertion[UndoAttempt]:
    def assertion(_attempt: UndoAttempt) -> bool:
        set_state.assert_called_once_with(flag, enabled)

        return True

    return assertion


def _nothing_was_written(set_state: MagicMock) -> Assertion[UndoAttempt]:
    def assertion(_attempt: UndoAttempt) -> bool:
        if set_state.called:
            raise AssertionError(
                f"Expected nothing to be written, and the flag was set: "
                f"{set_state.call_args}."
            )

        return True

    return assertion


def _the_restore_was_used(restore: MagicMock) -> Assertion[UndoAttempt]:
    def assertion(_attempt: UndoAttempt) -> bool:
        if not restore.called:
            raise AssertionError(
                "Expected the change to be put back through its own kind's part of the "
                "way back, and that part was never asked."
            )

        return True

    return assertion


def _it_was_asked_from(asked: _ARecordAskedAbout,
                       moment: datetime) -> Assertion[UndoAttempt]:
    def assertion(_attempt: UndoAttempt) -> bool:
        if asked.asked_about != (SOME_FLAG, moment):
            raise AssertionError(
                f"Expected the record to be asked about [{SOME_FLAG}] from "
                f"[{moment}], and it was asked {asked.asked_about}."
            )

        return True

    return assertion


def _a_restorer_that_puts_back(revision: bool = True,
                               automated_sync: bool = True) -> MagicMock:
    restore: MagicMock = create_autospec(DeploymentRestorer, instance=True)
    restore.return_value = DeploymentRestored(
        revision_put_back=revision, automated_sync_put_back=automated_sync
    )

    return restore


def _it_is_about(subject: str) -> Assertion[UndoAttempt]:
    def assertion(attempt: UndoAttempt) -> bool:
        if attempt.subject != subject:
            raise AssertionError(
                f"Expected the answer to be about [{subject}], and it was about "
                f"[{attempt.subject}]."
            )

        return True

    return assertion


def _it_says_what_is_still_changed(mentioned: str) -> Assertion[UndoAttempt]:
    def assertion(attempt: UndoAttempt) -> bool:
        if mentioned not in attempt.detail:
            raise AssertionError(
                f"Expected the report to name [{mentioned}], and it said: "
                f"{attempt.detail}"
            )

        return True

    return assertion


def _it_is_said_as(mentioned: str) -> Assertion[UndoAttempt]:
    def assertion(attempt: UndoAttempt) -> bool:
        if attempt.said_as is None or mentioned not in attempt.said_as:
            raise AssertionError(
                f"Expected the put-back said as something naming [{mentioned}], and "
                f"it was said as [{attempt.said_as}]."
            )

        return True

    return assertion


def _it_says_exactly(expected: str) -> Assertion[UndoAttempt]:
    def assertion(attempt: UndoAttempt) -> bool:
        if attempt.detail != expected:
            raise AssertionError(
                f"Expected the report to say [{expected}], and it said "
                f"[{attempt.detail}]."
            )

        return True

    return assertion


def _it_does_not_name_its_subject() -> Assertion[UndoAttempt]:
    def assertion(attempt: UndoAttempt) -> bool:
        if attempt.subject in attempt.detail:
            raise AssertionError(
                f"Expected the report not to name [{attempt.subject}] again, and "
                f"it said [{attempt.detail}]."
            )

        return True

    return assertion


def _an_autoscaling_restorer_that_puts_back(
    floor: bool = True,
    automated_sync: bool = True
) -> MagicMock:
    restore: MagicMock = create_autospec(AutoscalingRestorer, instance=True)
    restore.return_value = AutoscalingRestored(
        floor_put_back=floor, automated_sync_put_back=automated_sync
    )

    return restore


def _a_capacity_restorer_that_puts_back(count: bool = True,
                                        automated_sync: bool = True) -> MagicMock:
    restore: MagicMock = create_autospec(CapacityRestorer, instance=True)
    restore.return_value = CapacityRestored(
        count_put_back=count, automated_sync_put_back=automated_sync
    )

    return restore


def _an_accelerator_pin_restorer_that_puts_back(
    pin: bool = True,
    automated_sync: bool = True
) -> MagicMock:
    restore: MagicMock = create_autospec(AcceleratorPinRestorer, instance=True)
    restore.return_value = AcceleratorPinRestored(
        pin_put_back=pin, automated_sync_put_back=automated_sync
    )

    return restore


def _the_restorer_was_not_asked(restore: MagicMock, which: str) -> Assertion[UndoAttempt]:
    def assertion(dont_care_attempt: UndoAttempt) -> bool:
        if restore.called:
            raise AssertionError(
                f"Expected the change to be put back by its own restorer, and "
                f"{which} was asked {restore.call_args_list}."
            )

        return True

    return assertion


def _a_collaborator_raising(spec: type, failure: Exception | None = None) -> MagicMock:
    """`spec`, raising `failure` - a platform that would not answer, by default."""
    collaborator: MagicMock = create_autospec(spec, instance=True)
    collaborator.side_effect = (
        failure if failure is not None else RuntimeError("the platform would not answer")
    )

    return collaborator


def _a_rollout_of(wanted: int,
                  serving: int,
                  updated: int,
                  paused: bool = False,
                  failed: bool = False) -> RolloutProgress:
    return RolloutProgress(
        replicas_wanted=wanted,
        replicas_serving=serving,
        replicas_updated=updated,
        is_paused=paused,
        has_failed=failed
    )


def _a_rollout_reporting(wanted: int,
                         serving: int,
                         updated: int,
                         paused: bool = False,
                         failed: bool = False) -> MagicMock:
    """A platform answering with one rollout's counts, however often it is asked."""
    rollouts: MagicMock = create_autospec(RolloutReader, instance=True)
    rollouts.return_value = _a_rollout_of(wanted, serving, updated, paused, failed)

    return rollouts


def _rollouts_reading(*progress: RolloutProgress) -> MagicMock:
    """A platform answering each read with the next of these, in turn."""
    rollouts: MagicMock = create_autospec(RolloutReader, instance=True)
    rollouts.side_effect = list(progress)

    return rollouts


def _the_arrival_is(expected: Arrival) -> Assertion[Arrival]:
    """That the kind read the counts as this state of arrival."""
    def the_arrival_is(arrival: Arrival) -> bool:
        if arrival is not expected:
            raise AssertionError(
                f"Expected the arrival [{expected}], got [{arrival}]."
            )

        return True

    return the_arrival_is


def _the_looks_answered(expected: list[Arrival]) -> Assertion[list[Arrival]]:
    def assertion(answered: list[Arrival]) -> bool:
        if answered != expected:
            raise AssertionError(
                f"Expected the looks to answer {expected}, got {answered}"
            )

        return True

    return assertion


def _the_rollout_was_asked_about(rollouts: MagicMock,
                                 service: str) -> Assertion[Arrival]:
    """`call_args_list` compared directly, for the reason `_the_write_was_asked`
    gives."""
    def assertion(dont_care_arrival: Arrival) -> bool:
        if rollouts.call_args_list != [call(service)]:
            raise AssertionError(
                f"Expected the rollout of [{service}] to be read once, got "
                f"{rollouts.call_args_list}"
            )

        return True

    return assertion


def _each_kind_waits_for(expected: dict[str, Arrival]) -> Assertion[dict[str, Arrival]]:
    """That every kind of action read this one window the way its own change
    arrives.

    Every kind named in one assertion rather than one test each, because a kind
    answering `ARRIVED` for everything satisfies all but the one that waits, and
    is the bug this exists to catch.
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
@pytest.mark.parametrize(("kind", "an_action", "a_plan", "write", "spec"),
                         EVERY_KIND_OF_PLANNED_WRITE)
def test_a_change_made_is_said_from_its_action_and_its_way_back_as_its_write_said_it(
    kind: UndoableKind[Any], an_action: Callable[[], Action],
    a_plan: Callable[[], Planned[Any]], write: str, spec: type
) -> None:
    # One sentence for a change, whoever builds it: the write that made it, and
    # a resumed walk holding only the action and the row's way back - which
    # puts the change back, or watches it, in the words the first walk would
    # have used.
    the_action = an_action()
    some_change_made = a_plan().descriptor
    as_its_write_said_it = kind.perform(
        the_action, a_plan(), the_writes(**{write: _a_write_answering(spec, some_change_made)})
    ).said

    Scenario() \
        .given(
            the_action
        ) \
        .when(
            lambda: kind.said(the_action, some_change_made)
        ) \
        .then(
            the_answer_was(as_its_write_said_it)
        )


def _a_write_answering(spec: type, change_made: UndoDescriptor) -> MagicMock:
    """`spec`, answering that it made `change_made`."""
    write: MagicMock = create_autospec(spec, instance=True)
    write.return_value = change_made

    return write


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "an_action", "a_plan", "write", "spec"),
                         EVERY_KIND_OF_PLANNED_WRITE)
def test_a_change_as_recorded_is_the_change_its_write_performed(
    kind: UndoableKind[Any], an_action: Callable[[], Action],
    a_plan: Callable[[], Planned[Any]], write: str, spec: type
) -> None:
    # What a resumed walk holds of a change it did not make is the action and
    # the row's way back. Rebuilt from those, it is what the write produced -
    # the same words and the same way back - so a change watched or put back by
    # a walk that did not make it is said as the walk that made it said it.
    the_action = an_action()
    some_change_made = a_plan().descriptor
    as_its_write_performed_it = kind.perform(
        the_action, a_plan(), the_writes(**{write: _a_write_answering(spec, some_change_made)})
    )

    Scenario() \
        .given(
            the_action
        ) \
        .when(
            lambda: performed_as_recorded(the_action, some_change_made)
        ) \
        .then(
            the_answer_was(as_its_write_performed_it)
        )


@pytest.mark.unit
def test_a_change_as_recorded_is_said_by_the_kind_that_made_it() -> None:
    # Whose words are the kind's that made the change, found by the change -
    # the way a change is put back by the kind that made it.
    some_change_made = an_undo_descriptor_for(SOME_FLAG)
    some_words_for_it = "set the kuki flag the buki way"

    Scenario() \
        .given(
            a_kind := _a_kind_saying(some_words_for_it)
        ) \
        .when(
            lambda: performed_as_recorded(an_action_setting(SOME_FLAG, enabled=True),
                                          some_change_made,
                                          undoing_kinds=lambda dont_care_descriptor: a_kind)
        ) \
        .then(
            the_answer_was(Performed(said=some_words_for_it, undo_descriptor=some_change_made))
        )


def _a_kind_saying(words: str) -> MagicMock:
    """A kind of change whose words for any change are `words`."""
    kind: MagicMock = create_autospec(UndoableKind, instance=True)
    kind.said.return_value = words

    return kind


# Every kind of change, with the kind that made it, the plan the claim carried
# for it, the part of the write tier that reads whether the change is still as
# Argus left it, what that part is, and what it is asked of the plan the call
# hands it - `None` where a claim kept none - and the change: the change as the
# row records it, and for a flag the plan beside it, since a flag's history is
# read from the plan's own read, as the write reads it. A flag with no plan is
# asked nothing (`None`); every other kind asks of the change alone all the same.
EVERY_KIND_OF_CHECK = [
    pytest.param(RevertFeatureFlagKind(),
                 lambda: a_plan_of(a_planned_flag_change_for(SOME_FLAG, was_enabled=False)),
                 "flag_still_argus_s", FlagStillArgusS,
                 lambda planned, change: None if planned is None else (planned, change),
                 id="flag"),
    pytest.param(RollBackDeploymentKind(),
                 lambda: a_plan_of(a_rollback_descriptor_for(SOME_APPLICATION)),
                 "rollback_still_argus_s", RollbackStillArgusS,
                 lambda dont_care_planned, change: (change,), id="rollback"),
    pytest.param(ScaleOutKind(), lambda: a_plan_of(a_resize_descriptor_for(SOME_APPLICATION)),
                 "scale_out_still_argus_s", ScaleOutStillArgusS,
                 lambda dont_care_planned, change: (change,), id="scale-out"),
    pytest.param(PinAutoscalerKind(), lambda: a_plan_of(a_pin_descriptor_for(SOME_APPLICATION)),
                 "autoscaler_pin_still_argus_s", AutoscalerPinStillArgusS,
                 lambda dont_care_planned, change: (change,), id="autoscaler-pin"),
    pytest.param(PinToAcceleratorKind(),
                 lambda: a_plan_of(a_card_pin_descriptor_for(SOME_APPLICATION)),
                 "accelerator_pin_still_argus_s", AcceleratorPinStillArgusS,
                 lambda dont_care_planned, change: (change,), id="card-pin")
]
# What a kind's read is asked of the plan a call hands it and the change -
# `None` where it asks the tier nothing.
type WhatTheReadIsAsked = Callable[[Planned[Any] | None, Any], tuple[object, ...] | None]

# What the write tier found of a change, in its own words: somebody's change
# since, and why nobody can say.
SOMEBODY_S_CHANGE_FOUND = "somebody set it to something else since"
WHY_NOBODY_CAN_SAY = "the platform did not answer"

# What the write tier can answer about a change Argus made, in its own words
# where it has any: still as Argus left it, changed since, or nobody can say.
EVERY_ANSWER_ABOUT_A_CHANGE = [
    pytest.param(lambda: ChangeFound(still_argus_s=True), id="still-argus-s"),
    pytest.param(lambda: ChangeFound(still_argus_s=False, found=SOMEBODY_S_CHANGE_FOUND),
                 id="changed-since"),
    pytest.param(lambda: ChangeFound(still_argus_s=None, found=WHY_NOBODY_CAN_SAY),
                 id="nobody-can-say")
]


@pytest.mark.unit
@pytest.mark.parametrize("an_answer", EVERY_ANSWER_ABOUT_A_CHANGE)
@pytest.mark.parametrize(("kind", "a_plan", "check", "spec", "asked"), EVERY_KIND_OF_CHECK)
def test_each_kind_asks_the_write_tier_whether_its_change_is_still_argus_s(
    kind: UndoableKind[Any], a_plan: Callable[[], Planned[Any]], check: str, spec: type,
    asked: WhatTheReadIsAsked, an_answer: Callable[[], ChangeFound]
) -> None:
    # The write's own "made" rule, asked without the write: through the tier the
    # write compares through, with what that kind's read takes. What the tier
    # answers is the answer - nothing here reads the estate, and nothing turns
    # "nobody can say" into either of the others.
    the_plan = a_plan()
    the_answer = an_answer()

    Scenario() \
        .given(
            asking := _a_collaborator_answering(spec, the_answer)
        ) \
        .when(
            lambda: kind.still_argus_s(the_plan, the_plan.descriptor,
                                       the_writes(**{check: asking}))
        ) \
        .then(all_of(
            _asked_as_its_read_needs(asking, asked(the_plan, the_plan.descriptor)),
            the_answer_was(the_answer)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "a_plan", "check", "spec", "asked"), EVERY_KIND_OF_CHECK)
def test_each_kind_asked_of_a_change_whose_claim_kept_no_plan_asks_what_its_read_needs(
    kind: UndoableKind[Any], a_plan: Callable[[], Planned[Any]], check: str, spec: type,
    asked: WhatTheReadIsAsked
) -> None:
    # Every kind but a flag reads the change alone, and asks the tier all the
    # same. A flag's history is read from the plan's own read, so with none
    # nobody can say, saying why - and the tier is asked nothing.
    no_plan = None
    the_change = a_plan().descriptor

    Scenario() \
        .given(
            asking := _a_collaborator_answering(spec, ChangeFound(still_argus_s=True))
        ) \
        .when(
            lambda: kind.still_argus_s(no_plan, the_change, the_writes(**{check: asking}))
        ) \
        .then(
            _asked_as_its_read_needs(asking, asked(no_plan, the_change))
        )


def _asked_as_its_read_needs(asking: MagicMock,
                             expected: tuple[object, ...] | None) -> Assertion[ChangeFound]:
    """The tier asked once with `expected` - or, where `expected` is `None`,
    asked nothing and nobody able to say, saying why."""
    def assertion(found: ChangeFound) -> bool:
        if expected is not None:
            return _the_check_was_asked(asking, *expected)(found)

        if asking.called or found.still_argus_s is not None or not found.found:
            raise AssertionError(
                f"Expected the tier asked nothing and nobody able to say, saying why, got "
                f"[{found.still_argus_s}] finding [{found.found}], the tier asked "
                f"{asking.call_args_list}."
            )

        return True

    return assertion


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "a_plan", "check", "spec", "dont_care_asked"),
                         EVERY_KIND_OF_CHECK)
def test_asking_whether_a_change_is_still_argus_s_writes_nothing(
    kind: UndoableKind[Any], a_plan: Callable[[], Planned[Any]], check: str, spec: type,
    dont_care_asked: WhatTheReadIsAsked
) -> None:
    # A resumed walk asks it before it watches a change it did not make, and a
    # question that wrote would be a second change made on a guess.
    the_plan = a_plan()

    Scenario() \
        .given(
            writes := the_writes(**{check: _a_collaborator_answering(
                spec, ChangeFound(still_argus_s=True)
            )})
        ) \
        .when(
            lambda: kind.still_argus_s(the_plan, the_plan.descriptor, writes)
        ) \
        .then(
            _nothing_was_written_through(writes)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("dont_care_kind", "a_plan", "check", "spec", "asked"),
                         EVERY_KIND_OF_CHECK)
def test_whether_a_change_is_still_argus_s_is_asked_by_the_kind_that_made_it(
    dont_care_kind: UndoableKind[Any], a_plan: Callable[[], Planned[Any]], check: str,
    spec: type, asked: WhatTheReadIsAsked
) -> None:
    # A resumed walk holds the claim's plan and the row's way back, and nothing
    # saying which kind made the change but the way back itself - so the change
    # finds its kind, as it does to be put back. Every other check in the bundle
    # is a spy nobody wired: a change asked of the wrong kind's read fails on
    # the call.
    the_plan = a_plan()
    the_answer = ChangeFound(still_argus_s=True)

    Scenario() \
        .given(
            asking := _a_collaborator_answering(spec, the_answer)
        ) \
        .when(
            lambda: still_argus_s(the_plan, the_plan.descriptor,
                                  writes=the_writes(**{check: asking}))
        ) \
        .then(all_of(
            _asked_as_its_read_needs(asking, asked(the_plan, the_plan.descriptor)),
            the_answer_was(the_answer)
        ))


def _the_check_was_asked(check: MagicMock, *about: object) -> Assertion[object]:
    """Asked once, about `about` - the change as the row records it, the plan
    the claim carries, or both. `call_args_list` compared directly, for the
    reason `_the_write_was_asked` gives."""
    def assertion(dont_care_answer: object) -> bool:
        if check.call_args_list != [call(*about)]:
            raise AssertionError(
                f"Expected the write tier asked once about {list(about)}, got "
                f"{check.call_args_list}."
            )

        return True

    return assertion


# Every kind of action that is planned, with a plan of it, the part of the write
# tier that reads whether a claim's change on that plan was made, and what that
# part is.
EVERY_KIND_OF_MADE_READ = [
    pytest.param(RevertFeatureFlagKind(), lambda: an_action_setting(SOME_FLAG, enabled=True),
                 lambda: a_plan_of(a_planned_flag_change_for(SOME_FLAG, was_enabled=False)),
                 "whether_flag_was_made", WhetherAFlagWasMade, id="flag"),
    pytest.param(RollBackDeploymentKind(), lambda: RollBackDeployment(application=SOME_APPLICATION),
                 lambda: a_plan_of(a_rollback_descriptor_for(SOME_APPLICATION)),
                 "whether_rollback_was_made", WhetherARollbackWasMade, id="rollback"),
    pytest.param(ScaleOutKind(), lambda: ScaleOut(application=SOME_APPLICATION),
                 lambda: a_plan_of(a_resize_descriptor_for(SOME_APPLICATION)),
                 "whether_scale_out_was_made", WhetherAScaleOutWasMade, id="scale-out"),
    pytest.param(PinAutoscalerKind(), lambda: PinAutoscaler(application=SOME_APPLICATION),
                 lambda: a_plan_of(a_pin_descriptor_for(SOME_APPLICATION)),
                 "whether_autoscaler_pin_was_made", WhetherAnAutoscalerPinWasMade,
                 id="autoscaler-pin"),
    pytest.param(PinToAcceleratorKind(), lambda: a_pin_to(THE_CARD_IT_WAS_HELD_TO),
                 lambda: a_plan_of(a_card_pin_descriptor_for(SOME_APPLICATION)),
                 "whether_accelerator_pin_was_made", WhetherAnAcceleratorPinWasMade,
                 id="card-pin")
]

# What the write tier can answer about a claim's change on its plan, built from
# the plan: made - the plan's change, and when - or not made, carrying nothing,
# or carrying the plan where the suspension before the change landed alone.
EVERY_ANSWER_ABOUT_A_CLAIM = [
    pytest.param(lambda planned: Made(descriptor=planned.descriptor,
                                      made_at=THE_WRITE_LANDED_AT), id="made"),
    pytest.param(lambda dont_care_planned: NotMade(left_behind=None), id="nothing-landed"),
    pytest.param(lambda planned: NotMade(left_behind=planned.descriptor),
                 id="its-suspension-alone-landed")
]

# What a read refused for, in the tier's own words: somebody's change since the
# plan, and an answer it could not read.
SOMEBODY_CHANGED_IT_SINCE_THE_PLAN = "somebody changed it since the plan"
AN_ANSWER_NOBODY_COULD_READ = "the platform's answer could not be read"

# The two refusals a read can raise, as the transport raises them: somebody's
# change since the plan, and a refusal that says nothing of what is there.
EVERY_REFUSAL_OF_A_READ = [
    pytest.param(lambda: ChangedSince(
        a_change_made_since(SOMEBODY_CHANGED_IT_SINCE_THE_PLAN, None), None
    ), ChangedSince, id="changed-since"),
    pytest.param(lambda: McpToolError(AN_ANSWER_NOBODY_COULD_READ),
                 McpToolError, id="nobody-can-say")
]


@pytest.mark.unit
@pytest.mark.parametrize("an_answer", EVERY_ANSWER_ABOUT_A_CLAIM)
@pytest.mark.parametrize(("kind", "an_action", "a_plan", "read", "spec"),
                         EVERY_KIND_OF_MADE_READ)
def test_each_kind_asks_the_write_tier_whether_the_claim_s_change_was_made(
    kind: UndoableKind[Any], an_action: Callable[[], Action],
    a_plan: Callable[[], Planned[Any]], read: str, spec: type,
    an_answer: Callable[[Planned[Any]], Made[Any] | NotMade[Any]]
) -> None:
    # A resumed walk asks before anything else, on the plan the claim carries:
    # through the tier the write compares through, the write's own rule without
    # the write. What the tier answers is the answer - made, with when, or not
    # made, with what it left - and nothing here works either out again.
    the_plan = a_plan()
    the_answer = an_answer(the_plan)

    Scenario() \
        .given(
            asking := _a_collaborator_answering(spec, the_answer)
        ) \
        .when(
            lambda: kind.whether_it_was_made(an_action(), the_plan,
                                             the_writes(**{read: asking}))
        ) \
        .then(all_of(
            _the_check_was_asked(asking, the_plan),
            the_answer_was(the_answer)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("kind", "an_action", "a_plan", "read", "spec"),
                         EVERY_KIND_OF_MADE_READ)
def test_asking_whether_the_claim_s_change_was_made_writes_nothing(
    kind: UndoableKind[Any], an_action: Callable[[], Action],
    a_plan: Callable[[], Planned[Any]], read: str, spec: type
) -> None:
    # Asked before the walk decides whether to act again: a question that wrote
    # would be the second write the read exists to rule out.
    Scenario() \
        .given(
            writes := the_writes(**{read: _a_collaborator_answering(
                spec, NotMade(left_behind=None)
            )})
        ) \
        .when(
            lambda: kind.whether_it_was_made(an_action(), a_plan(), writes)
        ) \
        .then(
            _nothing_was_written_through(writes)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("a_refusal", "raised"), EVERY_REFUSAL_OF_A_READ)
@pytest.mark.parametrize(("kind", "an_action", "a_plan", "read", "spec"),
                         EVERY_KIND_OF_MADE_READ)
def test_a_read_refused_reaches_whoever_asked_whether_it_was_made_as_the_tier_raised_it(
    kind: UndoableKind[Any], an_action: Callable[[], Action],
    a_plan: Callable[[], Planned[Any]], read: str, spec: type,
    a_refusal: Callable[[], McpToolError], raised: type[McpToolError]
) -> None:
    # Somebody's change since the plan, or an estate nobody can read: which it
    # was decides whether the walk escalates carrying what landed or says nobody
    # can say - from the exception's own type. A kind that caught it, or wrapped
    # it, would turn the one into the other.
    Scenario() \
        .given(
            refusing := _a_collaborator_raising(spec, a_refusal())
        ) \
        .when(attempting(
            lambda: kind.whether_it_was_made(an_action(), a_plan(),
                                             the_writes(**{read: refusing}))
        )) \
        .then(
            an_error_was_raised(raised)
        )
