"""Holding an autoscaler still through the platform, and letting it move again.

The first action here that stops something rather than adding or restoring
something, and what is worth pinning is that it stops it by *raising a floor* -
the controller is left running, with nowhere left to scale down to. Nothing is
removed, nothing is deleted, and the ceiling a human declared is never moved.

Where the autoscaler is is discovered rather than configured, which is what
separates this from the restart and the scale-out beside it. The platform names
every resource an application has, so a pin asks it where to write instead of
being told - and an autoscaler named something other than its application is
then addressed correctly rather than plausibly.

The bounds are live state only the platform holds, as the scale-out's count is.
The repository says what the autoscaler is asked to converge on, which is a
different pair of numbers the moment anybody pins - so a floor derived from
anything else would be derived from a fact nobody here has.

A pin is planned before it is made, as the scale-out is. The plan reads the
bounds and the sync, works out the floor to ask for, is dated by the platform's
own clock, and changes nothing. The write takes the plan and compares before it
writes: the floor and the sync switch are each written only where they are still
what the plan found, taken as made only where they are what it asked for under
this claim's mark, and refused as changed since otherwise - with nothing written.
A refusal says what this claim's marks show already landed: where its suspension
still stands, the plan travels on the refusal as what it left behind. And since
the write takes the floor rather than working it out, it checks both of the
floor's bounds again where it writes - the ceiling as read then, and the most
Argus may ask for.

The order is the platform's rule, as it is for the other two actions that change
live state under a GitOps controller: a reconciling application has the
autoscaler's whole manifest re-applied at its next sync, floor included. The
restore's order is the same rule read backwards - reconciliation last, because
turning it on first would have the platform put the floor back on its own,
unverifiably, at a moment nothing here chose.

And a withdrawal puts back only what is still Argus's. A floor that is still the
one Argus asked for is put back; one already back where Argus found it needs no
write; any other is somebody's since, and is left as they set it - with the
reconciliation Argus suspended left suspended where it still is, since resuming
it would have the platform re-apply git over them.

How Argo CD is asked any of this - the tree, the selectors, a merge patch carried
as text - is the adapter's, and pinned in its own suite.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    an_error_was_raised,
    attempting,
    calling,
    one_record_was_logged,
    the_error_mentioned,
)
from core.models import AutoscalerUndo, AutoscalingRestored, Planned
from deployment_platform import (
    Autoscaler,
    AutoscalerBounds,
    DeploymentPlatformWrites,
    MarkedObject,
    MarkFound,
    PlatformRefused,
    PlatformUnreachable,
)
from mcp_transport import (
    EXHAUSTED_ACTION_MARKER,
    LEFT_BEHIND_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    what_was_left_behind,
)
from write_mcp_server.pinning import (
    AlreadyHeldStill,
    PinRefused,
    pin_autoscaler,
    plan_autoscaler_pin,
    restore_autoscaler_floor,
    still_argus_s,
    whether_it_was_made,
)
from write_mcp_server.scaling import THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR

from write_mcp_server_test.framework.marks import (
    ANOTHER_CLAIM,
    THE_MOMENT_A_MARK_SAYS,
    THIS_CLAIM,
    a_mark,
    a_mark_found,
    every_write_carried,
)
from write_mcp_server_test.framework.putting_back import (
    it_was_left_because,
    it_was_not_left_alone,
    the_suspension_is_said_to_stand,
)
from write_mcp_server_test.framework.refusals import (
    it_is_marked_unreachable,
    it_left_behind,
    it_was_refused_as,
    it_was_refused_as_changed_since,
    its_change_is_said_performed,
    what_it_left_is_known,
)
from write_mcp_server_test.framework.resuming import (
    it_is_not_said_changed_since,
    it_is_still_argus_s,
    it_refused_as_the_write_does,
    it_was_changed_since,
    it_was_made,
    nobody_can_say,
    nothing_landed,
)

SOME_APPLICATION = "io-shop"
# What every pin and restore here is made under. One for the file: which action
# a write is for is the caller's, and what is asserted is only that the writes
# carry it.
SOME_MARK = a_mark()
# What the platform says when it fails or refuses a call: whatever it says, the
# refusal here is decided by which call failed and how.
DONT_CARE_PLATFORM_WORDS = "the platform did not do it"

# The platform's own clock when a plan reads it.
SOME_TIME_ON_THE_PLATFORM = datetime(2026, 11, 18, 13, 4, 30, tzinfo=UTC)
# When the platform answered the write it was asked for, by its own clock.
THE_MOMENT_THE_PLATFORM_ANSWERED = SOME_TIME_ON_THE_PLATFORM + timedelta(seconds=2)
# When a plan handed to a write was read. The write compares what it finds with
# what the plan says, never with when.
DONT_CARE_SINCE = datetime(2026, 11, 18, 13, 0, tzinfo=UTC)

# What the autoscaler is called and where it lives, as the platform reports them.
# Deliberately not the application's name: an autoscaler named after its
# application is the common case and not the contract, and a module that sent the
# application's name would pass every test that used one name for both.
SOME_AUTOSCALER = Autoscaler(name="io-shop-cpu", namespace="shopping")

# The bounds the fixture's own values file declares: a controller free to move
# between three replicas and six, which is what makes a flap possible at all.
THE_FLOOR = 3
THE_CEILING = 6
# A floor somebody set since, which is neither the one Argus found nor the one
# it asked for.
A_FLOOR_SOMEBODY_SET = THE_FLOOR + 1

# What a pin leaves where it suspended the sync and the floor never moved.
# `min_replicas_asked_for` is the ceiling only while the ceiling is at or below
# the most replicas Argus may ask for, which six is.
THE_SUSPENSION = AutoscalerUndo(
    application=SOME_APPLICATION,
    was_min_replicas=THE_FLOOR,
    min_replicas_asked_for=THE_CEILING,
    was_syncing_itself=True
)


def a_platform(floor: int = THE_FLOOR,
               ceiling: int = THE_CEILING,
               reconciling_itself: bool = True,
               holding_an_autoscaler: bool = True,
               marked: Mapping[MarkedObject, str | MarkFound] | None = None) -> Any:
    """A platform whose autoscaler holds `floor`, its objects carrying the claims
    `marked` names by object - none, unless a case says so."""
    platform = create_autospec(DeploymentPlatformWrites, instance=True)
    platform.autoscaler_of.return_value = (
        SOME_AUTOSCALER if holding_an_autoscaler else None
    )
    platform.autoscaler_bounds.return_value = AutoscalerBounds(
        floor=floor, ceiling=ceiling
    )
    platform.is_syncing_itself.return_value = reconciling_itself
    platform.now.return_value = SOME_TIME_ON_THE_PLATFORM
    # A write whose answer said no moment, unless a case gives it one.
    platform.set_autoscaler_floor.return_value = None

    marks = marked or {}
    def mark_on(dont_care_application: str, kind: MarkedObject) -> MarkFound | None:
        found = marks.get(kind)

        return a_mark_found(found) if isinstance(found, str) else found

    platform.mark_on.side_effect = mark_on

    return platform


def a_platform_as_the_pin_left_it(floor: int = THE_CEILING,
                                  reconciling_itself: bool = False,
                                  holding_an_autoscaler: bool = True) -> Any:
    """A platform a pin of Argus's has been through: its autoscaler held at the
    floor the pin asked for unless a case names another, and not syncing
    itself, because the pin suspended that, unless a case says somebody turned
    it back on."""
    return a_platform(floor=floor, reconciling_itself=reconciling_itself,
                      holding_an_autoscaler=holding_an_autoscaler)


@pytest.mark.unit
def test_a_plan_raises_the_floor_to_the_ceiling() -> None:
    # To the ceiling and no further, because the ceiling is a bound a human
    # declared. The count is not Argus's to choose even in principle: what it is
    # choosing is that the count should stop moving.
    platform = a_platform(floor=THE_FLOOR, ceiling=THE_CEILING)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform)) \
        .then(_the_plan_records_the_floor_it_asks_for(THE_CEILING))


@pytest.mark.unit
def test_the_bounds_a_plan_reads_are_the_autoscaler_the_platform_named() -> None:
    # Discovered rather than configured, and not assumed to be named after its
    # application: the platform says what the resource is called and where it
    # lives, and both travel into the read that follows.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform)) \
        .then(_the_bounds_were_read_of(platform, SOME_AUTOSCALER))


@pytest.mark.unit
def test_an_application_with_no_autoscaler_is_refused_by_the_plan() -> None:
    # Nothing to pin, and the one thing a caller reading this cannot check for
    # itself: a pin performed against a controller that does not exist would be
    # confirmed against a world that does not exist either.
    platform = a_platform(holding_an_autoscaler=False)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform))) \
        .then(all_of(
            an_error_was_raised(PinRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_ceiling_past_what_argus_may_ask_for_is_clamped_to_it() -> None:
    # One estate, one bound on its capacity. The ceiling is a human's declaration
    # and this is Argus's own limit on what it may hold a deployment at, and where
    # the two disagree the smaller wins. The case that makes the recorded floor
    # worth having: a sentence naming the destination as "its ceiling" is false
    # exactly here.
    platform = a_platform(
        floor=THE_FLOOR, ceiling=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 1
    )

    Scenario() \
        .given(platform) \
        .when(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform)) \
        .then(_the_plan_records_the_floor_it_asks_for(THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR))


@pytest.mark.unit
def test_a_plan_records_the_floor_and_the_policy_it_found() -> None:
    platform = a_platform(floor=THE_FLOOR, reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform)) \
        .then(all_of(
            _the_plan_records_the_floor(THE_FLOOR),
            _the_plan_records_sync_was(True)
        ))


@pytest.mark.unit
def test_a_plan_records_sync_as_it_was_found_off() -> None:
    # Never a default. An application somebody had already stopped reconciling
    # must be left stopped, and a descriptor that recorded the usual arrangement
    # would have a withdrawal start something Argus did not stop.
    platform = a_platform(reconciling_itself=False)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform)) \
        .then(_the_plan_records_sync_was(False))


@pytest.mark.unit
def test_a_plan_is_dated_by_the_platforms_own_clock() -> None:
    # What a resumed walk asks "has anybody changed it since?" from.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform)) \
        .then(_the_plan_is_dated(SOME_TIME_ON_THE_PLATFORM))


@pytest.mark.unit
def test_a_plan_reads_the_platforms_clock_before_the_state_it_dates() -> None:
    # A time read after the state could postdate a change the plan never saw,
    # and a later "nothing changed since" would then hide it.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform)) \
        .then(_the_time_was_read_first(platform))


@pytest.mark.unit
def test_a_plan_changes_nothing() -> None:
    # It is read before the claim is written, so anything it wrote would be a
    # change no claim accounts for.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform)) \
        .then(_nothing_was_written(platform))


@pytest.mark.unit
def test_an_autoscaler_already_held_still_is_refused_by_the_plan() -> None:
    # A floor already at the ceiling is a count that is not moving, so there is
    # nothing here to stop. Refused rather than planned as a no-op: a caller
    # told "done" would record a mitigation that never happened and then judge
    # the service against it.
    platform = a_platform(floor=THE_CEILING, ceiling=THE_CEILING)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform))) \
        .then(all_of(
            an_error_was_raised(AlreadyHeldStill),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_an_autoscaler_held_at_one_replica_is_refused_in_the_singular() -> None:
    # A floor and a ceiling of one: "[1] replicas" is the line a reader stops at.
    platform = a_platform(floor=1, ceiling=1)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform))) \
        .then(all_of(
            an_error_was_raised(AlreadyHeldStill),
            the_error_mentioned("may fall to [1] replica and")
        ))


@pytest.mark.unit
def test_a_floor_already_past_what_argus_may_ask_for_is_refused() -> None:
    # The clamp and the refusal are one question asked once: where the floor is
    # already at or above the most Argus may pin it at, a pin would lower it - and
    # reducing a deployment's capacity is the thing nothing here does on its own.
    platform = a_platform(
        floor=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 2,
        ceiling=THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 4
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform))) \
        .then(all_of(
            an_error_was_raised(AlreadyHeldStill),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_an_autoscaler_with_no_room_refuses_in_a_way_a_caller_can_recognise() -> None:
    # The pin's half of the same claim. Both of this tier's exhaustion refusals
    # have to be recognisable, and they are two exceptions in two modules - so a
    # marker applied to one and forgotten on the other is exactly the shape this
    # catches.
    platform = a_platform(floor=THE_CEILING, ceiling=THE_CEILING)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform))) \
        .then(_the_refusal_says_the_action_is_exhausted())


@pytest.mark.unit
def test_a_platform_that_will_not_answer_is_not_planned_on() -> None:
    platform = a_platform()
    platform.autoscaler_of.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform))) \
        .then(all_of(
            an_error_was_raised(PinRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_bounds_the_platform_would_not_report_are_not_planned_on() -> None:
    # The platform named the autoscaler and then would not say its bounds - a
    # refusal, or a manifest without them. A different failure from an
    # application with no autoscaler at all, and both have to leave the
    # deployment untouched: a guessed ceiling would hold a shop at a size nobody
    # declared.
    platform = a_platform()
    platform.autoscaler_bounds.side_effect = PlatformRefused(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform))) \
        .then(all_of(
            an_error_was_raised(PinRefused),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_platform_that_never_answered_the_read_is_reported_as_unreachable() -> None:
    # A pin begins by asking the platform what the application is made of, so on
    # a platform that is down this is where it finds out. Nothing has been
    # touched, which is what makes the report honest.
    platform = a_platform()
    platform.autoscaler_of.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_platform_that_would_not_say_its_time_is_not_planned_on() -> None:
    # A plan with no date is one a resumed walk could not ask "since when?" of.
    platform = a_platform()
    platform.now.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_bounds_the_platform_would_not_give_are_known_to_have_changed_nothing() -> None:
    # Nothing had been asked to change, so however the read failed, nothing did.
    platform = a_platform()
    platform.autoscaler_bounds.side_effect = PlatformRefused(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform))) \
        .then(all_of(
            it_was_refused_as(PinRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_asking_whether_it_syncs_itself_is_a_read_and_changes_nothing() -> None:
    platform = a_platform()
    platform.is_syncing_itself.side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=False
    )

    Scenario() \
        .given(platform) \
        .when(attempting(lambda: plan_autoscaler_pin(SOME_APPLICATION, platform))) \
        .then(all_of(
            it_is_marked_unreachable(True),
            what_it_left_is_known(True),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_pin_raises_the_floor_its_plan_asked_for_on_the_autoscaler_the_platform_names() -> None:
    # The plan's floor, written where the platform says the autoscaler is now.
    platform = a_platform(floor=THE_FLOOR)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)) \
        .then(_it_asked_for_a_floor_of(platform, THE_CEILING))


@pytest.mark.unit
def test_a_pin_answers_with_the_descriptor_its_plan_carried() -> None:
    platform = a_platform(floor=THE_FLOOR)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)) \
        .then(_it_answered_with(a_plan.descriptor))


@pytest.mark.unit
def test_every_write_a_pin_makes_carries_its_actions_mark() -> None:
    # The suspension and the floor alike: either left on the platform unmarked
    # is a change nobody can tell from a person's.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)) \
        .then(all_of(
            every_write_carried(platform, "suspend_sync", SOME_MARK),
            every_write_carried(platform, "set_autoscaler_floor", SOME_MARK)
        ))


@pytest.mark.unit
def test_reconciliation_is_suspended_before_the_floor_is_raised() -> None:
    # The platform's rule rather than a preference: a reconciling application has
    # the autoscaler's manifest re-applied at its next sync, floor and all, so a
    # pin taken under automated sync is a mitigation with a timer on it.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)) \
        .then(_it_was_asked_in_order(platform, "suspend_sync", "set_autoscaler_floor"))


@pytest.mark.unit
def test_an_application_nobody_was_reconciling_is_left_alone() -> None:
    platform = a_platform(reconciling_itself=False)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=False)) \
        .when(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)) \
        .then(_the_sync_policy_was_not_touched(platform))


@pytest.mark.unit
def test_a_floor_where_the_plan_found_it_under_another_claims_mark_is_raised() -> None:
    # An earlier change of Argus's, under another claim, is what the plan found
    # and what it planned from - not a change since.
    platform = a_platform(floor=THE_FLOOR, marked={MarkedObject.AUTOSCALER: ANOTHER_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)) \
        .then(_it_asked_for_a_floor_of(platform, THE_CEILING))


@pytest.mark.unit
@pytest.mark.parametrize("was_syncing_itself", [True, False],
                         ids=["argus-suspended-the-sync", "the-sync-was-already-off"])
def test_a_pin_this_claim_already_made_is_answered_as_made_and_writes_nothing(
    was_syncing_itself: bool
) -> None:
    # The same write asked again - a reply lost on the way back, a walk resumed
    # after its worker died. The floor is the one asked for and the autoscaler
    # carries this claim's mark, so the first asking made it: answered as made,
    # not as exhausted, and nothing written twice. The Application carries this
    # claim's mark only where this claim suspended its sync.
    suspended_by_this_claim = {MarkedObject.APPLICATION: THIS_CLAIM} if was_syncing_itself else {}
    platform = a_platform(floor=THE_CEILING, reconciling_itself=False,
                          marked={MarkedObject.AUTOSCALER: THIS_CLAIM, **suspended_by_this_claim})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=was_syncing_itself)) \
        .when(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_answered_with(a_plan.descriptor)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("marked_by", [None, ANOTHER_CLAIM],
                         ids=["unmarked", "under-another-claim"])
def test_a_floor_at_what_the_plan_asked_for_without_this_claims_mark_is_changed_since(
    marked_by: str | None
) -> None:
    # The right number by somebody else's hand. Taking it as made would claim
    # a change Argus did not make, and a withdrawal would then put back a floor
    # that was never Argus's.
    platform = a_platform(floor=THE_CEILING,
                          marked={} if marked_by is None else {MarkedObject.AUTOSCALER: marked_by})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("floor", [THE_FLOOR, A_FLOOR_SOMEBODY_SET],
                         ids=["back-where-the-plan-found-it", "somewhere-else"])
def test_a_floor_under_this_claims_mark_but_not_what_it_asked_for_is_changed_since(
    floor: int
) -> None:
    # This claim's change landed - the suspension and the floor, both under its
    # mark - and somebody moved the floor after it, back where it was included.
    # Redoing it would write over them. The suspension still stands, so the
    # refusal carries the plan, which is what a withdrawal puts it back from.
    platform = a_platform(floor=floor, reconciling_itself=False,
                          marked={MarkedObject.AUTOSCALER: THIS_CLAIM,
                                  MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(True),
            it_left_behind(a_plan.descriptor),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_floor_somebody_set_since_the_plan_is_refused_before_anything_is_written() -> None:
    # Before the sync switch too: a suspension written ahead of a refused floor
    # would be a change the refusal does not account for.
    platform = a_platform(floor=A_FLOOR_SOMEBODY_SET, reconciling_itself=True)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            it_is_marked_unreachable(False),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_floor_somebody_set_under_this_claims_suspension_leaves_the_suspension() -> None:
    # The suspension landed under this claim and the floor did not, and
    # somebody set a floor of their own in between. Nothing is written over
    # them, and the switch this claim turned off is still off - so the refusal
    # carries the plan, which is what puts it back on.
    platform = a_platform(floor=A_FLOOR_SOMEBODY_SET, reconciling_itself=False,
                          marked={MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            it_left_behind(a_plan.descriptor),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_plan_asking_past_the_autoscaler_s_ceiling_is_refused_by_the_write() -> None:
    # The write takes its floor from the plan rather than working it out, so the
    # ceiling - a human's declaration, read where the floor is written - is
    # checked again there. A floor above it is one the controller was never
    # declared to reach.
    past_the_ceiling = THE_CEILING + 1
    platform = a_platform(floor=THE_FLOOR, ceiling=THE_CEILING)

    Scenario() \
        .given(a_plan := _a_plan_asking_for(past_the_ceiling)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as(PinRefused),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_plan_asking_past_what_argus_may_ask_for_is_refused_by_the_write() -> None:
    # The other bound on the same floor, checked again where it is written: a
    # ceiling declared past Argus's own limit does not lift that limit, so a
    # floor inside the ceiling and past the limit is still refused.
    past_what_argus_may_ask_for = THE_MOST_REPLICAS_ARGUS_MAY_ASK_FOR + 1
    platform = a_platform(floor=THE_FLOOR, ceiling=past_what_argus_may_ask_for + 1)

    Scenario() \
        .given(a_plan := _a_plan_asking_for(past_what_argus_may_ask_for)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as(PinRefused),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("floor", [THE_FLOOR - 1, THE_FLOOR],
                         ids=["below-the-floor-it-found", "the-floor-it-found"])
def test_a_plan_asking_for_no_higher_floor_than_it_found_is_refused_by_the_write(
    floor: int
) -> None:
    # The write holds the plan to the plan step's own rule from the plan's own
    # "was": a floor raised. A plan asking for a lower one would have a pin take
    # capacity away, and one asking for the floor it found would be a change
    # judged as though it had been made. Refused plainly, before the sync switch
    # is touched.
    platform = a_platform(floor=THE_FLOOR, ceiling=THE_CEILING)

    Scenario() \
        .given(a_plan := _a_plan_asking_for(floor)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as(PinRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_re_ask_past_a_ceiling_lowered_since_still_carries_the_suspension() -> None:
    # The first asking's suspension landed under this claim and its floor did
    # not, and the ceiling has been lowered under the plan's floor since. The
    # floor is not written - and the refusal says what this claim left out
    # there, which a withdrawal puts back.
    platform = a_platform(floor=THE_FLOOR, ceiling=THE_CEILING - 1, reconciling_itself=False,
                          marked={MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as(PinRefused),
            what_it_left_is_known(True),
            it_left_behind(a_plan.descriptor),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_an_autoscaler_removed_since_the_plan_is_changed_since() -> None:
    # Somebody took away the controller the plan meant to hold still. A pin
    # now would have nowhere to go, and is not Argus's to put back.
    platform = a_platform(holding_an_autoscaler=False)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_sync_this_claim_suspended_is_not_suspended_again() -> None:
    # The suspension landed under this claim and the floor did not: the floor is
    # raised, and the switch is left where this claim put it.
    platform = a_platform(floor=THE_FLOOR, reconciling_itself=False,
                          marked={MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_asked_for_a_floor_of(platform, THE_CEILING)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("marked_by", [None, ANOTHER_CLAIM],
                         ids=["unmarked", "under-another-claim"])
def test_a_sync_suspended_since_the_plan_without_this_claims_mark_is_changed_since(
    marked_by: str | None
) -> None:
    # The plan found it reconciling, and somebody else has stopped it since. A
    # descriptor saying Argus suspended it would have a withdrawal resume what
    # they stopped.
    platform = a_platform(reconciling_itself=False,
                          marked={} if marked_by is None else {MarkedObject.APPLICATION: marked_by})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_sync_running_again_under_this_claims_mark_is_changed_since() -> None:
    # Argus suspended it under this claim and it is reconciling again, so
    # somebody turned it back on. Suspending it again would overrule them.
    platform = a_platform(floor=THE_FLOOR, reconciling_itself=True,
                          marked={MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_sync_turned_on_since_a_plan_that_found_it_off_is_changed_since() -> None:
    # A floor raised now would be put back at the next sync, and the descriptor
    # would say the sync was never Argus's to put back.
    platform = a_platform(floor=THE_FLOOR, reconciling_itself=True)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=False)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("read", ["autoscaler_of", "autoscaler_bounds",
                                  "is_syncing_itself", "mark_on"])
def test_a_pin_that_could_not_read_what_is_there_now_writes_nothing(read: str) -> None:
    # The compare is what makes the write safe to ask, and a compare against a
    # read that never came back is no compare at all.
    platform = a_platform(floor=THE_FLOOR)
    getattr(platform, read).side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as(PinRefused),
            what_it_left_is_known(True),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_every_write_a_restore_makes_carries_its_mark() -> None:
    platform = a_platform_as_the_pin_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(descriptor, platform, SOME_MARK)) \
        .then(all_of(
            every_write_carried(platform, "set_autoscaler_floor", SOME_MARK),
            every_write_carried(platform, "resume_sync", SOME_MARK)
        ))


@pytest.mark.unit
def test_restoring_puts_back_the_floor_the_autoscaler_had() -> None:
    platform = a_platform_as_the_pin_left_it()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _it_asked_for_a_floor_of(platform, THE_FLOOR),
            _it_reports_restored(floor=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_asks_again_where_the_autoscaler_is() -> None:
    # Hours later, and nothing in the descriptor says where the resource lives -
    # deliberately, because where it lives is the platform's to say at the moment
    # the question is asked. A record of it taken when the pin was performed would
    # be a record that can have gone stale.
    platform = a_platform_as_the_pin_left_it()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _the_autoscaler_was_asked_for(platform),
            _it_asked_for_a_floor_of(platform, THE_FLOOR)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("was_syncing_itself", "syncing_now", "still_suspended"),
    [
        pytest.param(True, False, True, id="argus-suspended-it-and-it-is-still-off"),
        pytest.param(True, True, False, id="somebody-turned-it-back-on"),
        pytest.param(False, False, False, id="it-was-off-before-argus-came")
    ]
)
def test_an_autoscaler_somebody_removed_since_is_left_removed(
    was_syncing_itself: bool, syncing_now: bool, still_suspended: bool
) -> None:
    # Argus pinned an autoscaler that is no longer there, so somebody took it
    # away - a change of theirs like any other. Nothing is written, and sync is
    # not resumed: the platform would re-apply git and bring back what they
    # removed. Whether Argus's suspension still stands is read as it is for
    # every change left as somebody set it.
    platform = a_platform_as_the_pin_left_it(holding_an_autoscaler=False,
                                             reconciling_itself=syncing_now)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=was_syncing_itself)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _nothing_was_written(platform),
            it_was_left_because("no autoscaler"),
            the_suspension_is_said_to_stand(still_suspended)
        ))


@pytest.mark.unit
def test_the_floor_is_put_back_before_reconciliation_is() -> None:
    # The order that leaves nothing to chance. Turning sync on first would have the
    # platform re-apply the manifest itself - to the same floor, and unverifiably,
    # at a moment nothing here chose.
    platform = a_platform_as_the_pin_left_it()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(_it_was_asked_in_order(platform, "set_autoscaler_floor", "resume_sync"))


@pytest.mark.unit
def test_restoring_leaves_reconciliation_off_where_argus_found_it_off() -> None:
    platform = a_platform_as_the_pin_left_it()

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=False)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_reports_restored(floor=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_that_only_managed_the_floor_says_so() -> None:
    # The half that fails is the quiet one: an autoscaler back at its declared
    # floor looks right from every angle a reader has, while the application
    # receives nothing anybody ships to it.
    platform = a_platform_as_the_pin_left_it()
    platform.resume_sync.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(_it_reports_restored(floor=True, automated_sync=False))


@pytest.mark.unit
def test_a_restore_that_could_not_reach_the_platform_at_all_says_so() -> None:
    platform = a_platform_as_the_pin_left_it()
    platform.set_autoscaler_floor.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)
    platform.resume_sync.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(_it_reports_restored(floor=False, automated_sync=False))


@pytest.mark.unit
def test_a_floor_still_argus_s_is_put_back_and_said_to_be_nobody_else_s() -> None:
    # The autoscaler holds the floor Argus asked for, so nobody has moved it.
    platform = a_platform_as_the_pin_left_it(floor=THE_CEILING)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _it_asked_for_a_floor_of(platform, THE_FLOOR),
            _it_reports_restored(floor=True, automated_sync=True),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_floor_already_back_where_argus_found_it_is_not_written_again() -> None:
    # Somebody - anybody - has already let it fall back. Nothing is written for
    # the floor, and it counts as put back; the sync Argus suspended is still
    # Argus's to resume.
    platform = a_platform_as_the_pin_left_it(floor=THE_FLOOR)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _the_floor_was_not_written(platform),
            every_write_carried(platform, "resume_sync", SOME_MARK),
            _it_reports_restored(floor=True, automated_sync=True),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_floor_somebody_set_since_is_left_as_they_set_it() -> None:
    # Setting it back would replace their decision, and resuming sync would have
    # the platform re-apply git over it - so neither is written, and what was
    # found is said.
    platform = a_platform_as_the_pin_left_it(floor=A_FLOOR_SOMEBODY_SET)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _nothing_was_written(platform),
            it_was_left_because(f"[{A_FLOOR_SOMEBODY_SET}]")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("was_syncing_itself", "syncing_now", "still_suspended"),
    [
        pytest.param(True, False, True, id="argus-suspended-it-and-it-is-still-off"),
        pytest.param(True, True, False, id="somebody-turned-it-back-on"),
        pytest.param(False, False, False, id="it-was-off-before-argus-came")
    ]
)
def test_a_floor_left_as_somebody_set_it_says_whether_argus_s_suspension_still_stands(
    was_syncing_itself: bool, syncing_now: bool, still_suspended: bool
) -> None:
    # Read from the platform, because only it knows: a person who reverted in
    # git and turned sync back on has ended Argus's suspension themselves, and
    # one sync was off for before Argus came was never suspended by Argus.
    platform = a_platform_as_the_pin_left_it(floor=A_FLOOR_SOMEBODY_SET,
                                             reconciling_itself=syncing_now)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=was_syncing_itself)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _nothing_was_written(platform),
            the_suspension_is_said_to_stand(still_suspended)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("read", ["autoscaler_of", "autoscaler_bounds"])
def test_a_restore_that_could_not_read_whose_the_floor_is_writes_nothing(read: str) -> None:
    # Writing on a reading that never came back is the blind put-back the check
    # exists to prevent - so neither half is written, neither is said to be
    # back, and nothing is said to have been found. An autoscaler the platform
    # could not be asked about is not one somebody removed.
    platform = a_platform_as_the_pin_left_it()
    getattr(platform, read).side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(floor=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_restore_that_could_not_read_whether_sync_is_back_on_writes_nothing() -> None:
    # The last read, made only where the floor is somebody's: without it nobody
    # can say whether Argus's suspension still stands, and the answer says
    # nothing it could not establish.
    platform = a_platform_as_the_pin_left_it(floor=A_FLOOR_SOMEBODY_SET)
    platform.is_syncing_itself.side_effect = PlatformRefused(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(a_descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(floor=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_platform_unavailable_when_sync_is_suspended_is_reported_as_unreachable() -> None:
    # The suspension is the first thing a pin changes, so a platform that said
    # it did not handle it has left the estate as it found it.
    platform = a_platform()
    platform.suspend_sync.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS,
                                                            known_not_applied=True)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_platform_that_died_before_a_pin_that_changed_nothing_is_unreachable() -> None:
    # An application nobody was reconciling needs no suspension, so the patch is
    # the first write - and a platform that stopped answering before it took
    # nothing with it.
    platform = a_platform(reconciling_itself=False)
    platform.set_autoscaler_floor.side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=True
    )

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=False)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(_it_is_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_pin_that_left_sync_suspended_says_so_and_still_reports_the_platform() -> None:
    # The last of the three. The platform is gone and the floor never moved, so
    # what is left behind is the suspension alone - and it travels on the
    # failure, so the walk can narrow itself and still know an application is
    # sitting un-reconciled.
    #
    # `min_replicas_asked_for` is the ceiling only while the arrangement's
    # ceiling is at or below the most replicas Argus may ask for. It is six here,
    # so the two coincide; a case that raised the ceiling past that cap would
    # have to name the cap instead.
    platform = a_platform(reconciling_itself=True)
    platform.set_autoscaler_floor.side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=True
    )

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _it_says_what_it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_suspension_whose_answer_was_lost_is_not_said_to_have_changed_nothing() -> None:
    platform = a_platform()
    platform.suspend_sync.side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=False
    )

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as(PinRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(False),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_pin_rejected_after_sync_was_suspended_says_the_suspension_is_left() -> None:
    platform = a_platform(reconciling_itself=True)
    platform.set_autoscaler_floor.side_effect = PlatformRefused(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=True
    )

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_pin_whose_answer_was_lost_carries_the_suspension_and_no_more() -> None:
    # The floor may be rising this second. The suspension is carried, and
    # nothing is said to be all of it.
    platform = a_platform(reconciling_itself=True)
    platform.set_autoscaler_floor.side_effect = PlatformUnreachable(
        DONT_CARE_PLATFORM_WORDS, known_not_applied=False
    )

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(False),
            it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_platform_that_answered_and_refused_is_not_reported_as_unreachable() -> None:
    # Reachable, and this patch is what it would not take. The restart and the
    # scale-out are still worth reaching for, and what a person has to look at
    # is the refusal rather than the platform.
    platform = a_platform(reconciling_itself=False)
    platform.set_autoscaler_floor.side_effect = PlatformRefused(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=False)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(_it_is_not_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_a_pin_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production, and what it changed.
    platform = a_platform()

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            a_plan := _a_plan(was_syncing_itself=True)
        ) \
        .when(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.pinning", logging.INFO,
                                  "autoscaler floor raised",
                                  values={"application": SOME_APPLICATION,
                                          "from_floor": THE_FLOOR,
                                          "to_floor": THE_CEILING})
        )


@pytest.mark.unit
def test_a_pin_refused_after_sync_was_suspended_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The refusal leaves reconciliation off on purpose, and the line says so:
    # an application nobody is reconciling looks healthy until the next deploy
    # quietly does not arrive.
    platform = a_platform(reconciling_itself=True)
    platform.set_autoscaler_floor.side_effect = PlatformRefused(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_autoscaler(a_plan, platform, SOME_MARK))) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.pinning", logging.WARNING,
                                  "autoscaler pin refused",
                                  values={"application": SOME_APPLICATION,
                                          "sync_suspended": True})
        )


@pytest.mark.unit
def test_a_complete_restore_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production as much as the action was.
    platform = a_platform_as_the_pin_left_it()

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            descriptor := _a_descriptor(was_syncing_itself=True)
        ) \
        .when(lambda: restore_autoscaler_floor(descriptor, platform, SOME_MARK)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.pinning", logging.INFO,
                                  "autoscaler floor restored",
                                  values={"application": SOME_APPLICATION})
        )


@pytest.mark.unit
def test_a_restore_that_only_managed_the_floor_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The quiet half. The application looks put back and is receiving nothing
    # anybody ships to it, and no other line would say so.
    platform = a_platform_as_the_pin_left_it()
    platform.resume_sync.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(descriptor, platform, SOME_MARK)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.pinning", logging.WARNING,
                                  "autoscaler floor not fully restored",
                                  values={"application": SOME_APPLICATION,
                                          "floor_put_back": True,
                                          "automated_sync_put_back": False})
        )


@pytest.mark.unit
def test_a_restore_step_that_failed_is_logged_as_an_error(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The restore reports which half it lost, never why. The why is here, and
    # it is what a person putting the other half back by hand needs first.
    platform = a_platform_as_the_pin_left_it()
    platform.resume_sync.side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_autoscaler_floor(descriptor, platform, SOME_MARK)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.pinning", logging.ERROR,
                                  "restore step failed",
                                  values={"application": SOME_APPLICATION,
                                          "step": "automated sync"},
                                  failure=PlatformUnreachable)
        )


def _it_is_reported_as_an_unreachable_platform() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, PinRefused):
            raise AssertionError(
                f"Expected the pin to be refused, and what was raised was "
                f"{raised!r}."
            )

        if UNREACHABLE_PLATFORM_MARKER not in str(raised):
            raise AssertionError(
                f"Expected the refusal to report a platform that could not be "
                f"reached, and it reported [{raised}]."
            )

        return True

    return assertion


def _it_is_not_reported_as_an_unreachable_platform() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, PinRefused):
            raise AssertionError(
                f"Expected the pin to be refused, and what was raised was "
                f"{raised!r}."
            )

        if UNREACHABLE_PLATFORM_MARKER in str(raised):
            raise AssertionError(
                f"Expected the refusal to be reported as this action's own, and "
                f"it reported a platform that could not be reached: [{raised}]."
            )

        return True

    return assertion


def _the_refusal_says_the_action_is_exhausted() -> Assertion[Exception | None]:
    """The refusal carries the marker the transport turns into a type.

    Asserted against the marker rather than the sentence, because the sentence is
    allowed to change and the marker is not. The kernel's suite proves a marked
    refusal arrives as `ActionExhausted`; this proves this refusal is marked, and
    this is the end that has to remember to apply it.
    """
    def assertion(refusal: Exception | None) -> bool:
        if refusal is None or EXHAUSTED_ACTION_MARKER not in str(refusal):
            raise AssertionError(
                f"Expected the refusal to carry [{EXHAUSTED_ACTION_MARKER}], so "
                f"that a caller can tell an exhausted action from a broken "
                f"platform, and it said [{refusal}]."
            )

        return True

    return assertion


def _a_descriptor(was_syncing_itself: bool) -> AutoscalerUndo:
    return AutoscalerUndo(
        application=SOME_APPLICATION,
        was_min_replicas=THE_FLOOR,
        min_replicas_asked_for=THE_CEILING,
        was_syncing_itself=was_syncing_itself
    )


def _a_plan(was_syncing_itself: bool) -> Planned[AutoscalerUndo]:
    """The plan a pin of the fixture's autoscaler makes: its floor to its ceiling."""
    return Planned(descriptor=_a_descriptor(was_syncing_itself), since=DONT_CARE_SINCE)


def _a_plan_asking_for(floor: int) -> Planned[AutoscalerUndo]:
    """A plan of the fixture's autoscaler, asking for `floor` rather than its
    ceiling - one the plan step would never have made."""
    return Planned(
        descriptor=_a_descriptor(was_syncing_itself=True).model_copy(
            update={"min_replicas_asked_for": floor}
        ),
        since=DONT_CARE_SINCE
    )


def _the_plan_records_the_floor(floor: int) -> Assertion[Planned[AutoscalerUndo]]:
    def assertion(plan: Planned[AutoscalerUndo]) -> bool:
        if plan.descriptor.was_min_replicas != floor:
            raise AssertionError(
                f"Expected the plan to record [{floor}] replicas as the floor the "
                f"autoscaler had, and it records [{plan.descriptor.was_min_replicas}]."
            )

        return True

    return assertion


def _the_plan_records_the_floor_it_asks_for(floor: int) -> Assertion[Planned[AutoscalerUndo]]:
    def assertion(plan: Planned[AutoscalerUndo]) -> bool:
        if plan.descriptor.min_replicas_asked_for != floor:
            raise AssertionError(
                f"Expected the plan to ask for a floor of [{floor}] replicas, and it "
                f"asks for [{plan.descriptor.min_replicas_asked_for}]."
            )

        return True

    return assertion


def _the_plan_records_sync_was(syncing: bool) -> Assertion[Planned[AutoscalerUndo]]:
    def assertion(plan: Planned[AutoscalerUndo]) -> bool:
        if plan.descriptor.was_syncing_itself != syncing:
            raise AssertionError(
                f"Expected the plan to record automated sync as [{syncing}] when "
                f"Argus found it, and it records [{plan.descriptor.was_syncing_itself}]."
            )

        return True

    return assertion


def _the_plan_is_dated(since: datetime) -> Assertion[Planned[AutoscalerUndo]]:
    def assertion(plan: Planned[AutoscalerUndo]) -> bool:
        if plan.since != since:
            raise AssertionError(
                f"Expected the plan dated [{since}], and it is dated [{plan.since}]."
            )

        return True

    return assertion


def _the_time_was_read_first(platform: Any) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        asked = [name for name, _args, _kwargs in platform.method_calls]

        if not asked or asked[0] != "now":
            raise AssertionError(
                f"Expected the platform's time read before anything else, and the "
                f"platform was asked {asked}."
            )

        return True

    return assertion


def _it_answered_with(expected: AutoscalerUndo) -> Assertion[AutoscalerUndo]:
    def assertion(descriptor: AutoscalerUndo) -> bool:
        if descriptor != expected:
            raise AssertionError(
                f"Expected the pin to answer with {expected!r}, and it answered "
                f"with {descriptor!r}."
            )

        return True

    return assertion


def _the_floor_was_not_written(platform: Any) -> Assertion[AutoscalingRestored]:
    def assertion(dont_care_restored: AutoscalingRestored) -> bool:
        if platform.set_autoscaler_floor.called:
            raise AssertionError(
                f"Expected no floor written, and the platform was asked "
                f"{platform.set_autoscaler_floor.call_args_list}."
            )

        return True

    return assertion


def _nothing_was_written(platform: Any) -> Assertion[object]:
    """Neither the floor nor the sync policy - the reads are what an action
    that left the autoscaler alone did ask."""
    def assertion(dont_care_result: object) -> bool:
        written = [name for name, operation in (
            ("the floor", platform.set_autoscaler_floor),
            ("the sync policy", platform.resume_sync),
            ("the sync policy", platform.suspend_sync)
        ) if operation.called]

        if written:
            raise AssertionError(
                f"Expected nothing written, and {written} were: "
                f"{platform.method_calls}."
            )

        return True

    return assertion


def _it_asked_for_a_floor_of(platform: Any, floor: int) -> Assertion[object]:
    """One floor written, to the autoscaler the platform named - the mark it
    carried is `every_write_carried`'s to say."""
    def assertion(dont_care_result: object) -> bool:
        asked = [call.args[:3] for call in platform.set_autoscaler_floor.call_args_list]

        if asked != [(SOME_APPLICATION, SOME_AUTOSCALER, floor)]:
            raise AssertionError(
                f"Expected one floor of [{floor}] written to {SOME_AUTOSCALER} of "
                f"[{SOME_APPLICATION}], and the platform was asked {asked}."
            )

        return True

    return assertion


def _the_bounds_were_read_of(platform: Any, autoscaler: Autoscaler) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        asked = [call.args for call in platform.autoscaler_bounds.call_args_list]

        if asked != [(SOME_APPLICATION, autoscaler)]:
            raise AssertionError(
                f"Expected the bounds of {autoscaler} to be read, as the platform "
                f"named it, and the platform was asked {asked}."
            )

        return True

    return assertion


def _the_autoscaler_was_asked_for(platform: Any) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        asked = [call.args for call in platform.autoscaler_of.call_args_list]

        if asked != [(SOME_APPLICATION,)]:
            raise AssertionError(
                f"Expected the platform to be asked where [{SOME_APPLICATION}]'s "
                f"autoscaler is, and it was asked {asked}."
            )

        return True

    return assertion


def _it_was_asked_in_order(platform: Any, *expected: str) -> Assertion[object]:
    """The named operations happened, and in this order relative to each other."""
    def assertion(dont_care_result: object) -> bool:
        asked = [name for name, _args, _kwargs in platform.method_calls]
        relevant = [name for name in asked if name in expected]

        if relevant != list(expected):
            raise AssertionError(
                f"Expected {list(expected)} in that order, and the platform was "
                f"asked {asked}."
            )

        return True

    return assertion


def _the_sync_policy_was_not_touched(platform: Any) -> Assertion[object]:
    def assertion(dont_care_result: object) -> bool:
        if platform.suspend_sync.called or platform.resume_sync.called:
            raise AssertionError(
                f"Expected the sync policy to be left as it was found, and the "
                f"platform was asked {platform.method_calls}."
            )

        return True

    return assertion


def _nothing_was_changed(platform: Any) -> Assertion[Exception | None]:
    def assertion(dont_care_error: Exception | None) -> bool:
        changed = [
            name for name, operation in (
                ("the floor", platform.set_autoscaler_floor),
                ("the sync policy", platform.suspend_sync)
            )
            if operation.called
        ]

        if changed:
            raise AssertionError(
                f"Expected a refusal to change nothing, and it wrote "
                f"{sorted(changed)}."
            )

        return True

    return assertion


def _it_reports_restored(floor: bool,
                         automated_sync: bool) -> Assertion[AutoscalingRestored]:
    def assertion(restored: AutoscalingRestored) -> bool:
        reported = (restored.floor_put_back, restored.automated_sync_put_back)

        if reported != (floor, automated_sync):
            raise AssertionError(
                f"Expected the floor put back to be [{floor}] and automated "
                f"sync to be [{automated_sync}], and it reported {reported}."
            )

        return True

    return assertion


def _it_says_what_it_left_behind(
    expected: AutoscalerUndo
) -> Assertion[Exception | None]:
    """The refusal carries the descriptor, and carries the right one.

    The third of the three, for the same reason and with the same shape. Not
    lifted anywhere shared: each compares a different descriptor type, and one
    version would take the union and stop telling a pin's from a scale-out's.
    """
    def assertion(raised: Exception | None) -> bool:
        if LEFT_BEHIND_MARKER not in str(raised):
            raise AssertionError(
                f"Expected the refusal to say what it left behind, and it said "
                f"[{raised}]."
            )

        carried = what_was_left_behind(str(raised))

        if carried != expected:
            raise AssertionError(
                f"Expected the refusal to leave {expected!r} to be put back, it "
                f"left {carried!r}."
            )

        return True

    return assertion


@pytest.mark.unit
def test_a_pin_made_is_answered_dated_by_the_platform_s_answer_to_it() -> None:
    # What the way back is dated by, on the platform's own clock - never the
    # mark's moment, which is Argus's.
    platform = a_platform(floor=THE_FLOOR)
    platform.set_autoscaler_floor.return_value = THE_MOMENT_THE_PLATFORM_ANSWERED

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)) \
        .then(_it_answered_with(
            a_plan.descriptor.model_copy(update={"written_at": THE_MOMENT_THE_PLATFORM_ANSWERED})
        ))


# What a pin of Argus's that suspended the sync left marked: the autoscaler's
# floor, and the switch.
MARKED_BY_THIS_CLAIM = {MarkedObject.AUTOSCALER: THIS_CLAIM,
                        MarkedObject.APPLICATION: THIS_CLAIM}


@pytest.mark.unit
@pytest.mark.parametrize(
    ("was_syncing_itself", "marked"),
    [
        pytest.param(True, MARKED_BY_THIS_CLAIM, id="argus-suspended-the-sync"),
        pytest.param(False, {MarkedObject.AUTOSCALER: THIS_CLAIM},
                     id="the-sync-was-already-off")
    ]
)
def test_a_pin_as_argus_left_it_is_still_argus_s(
    was_syncing_itself: bool, marked: dict[MarkedObject, str]
) -> None:
    # The floor it asked for under this claim's mark, and the sync off - under
    # this claim's mark where it suspended it, as it was found where it was
    # already off.
    platform = a_platform(floor=THE_CEILING, reconciling_itself=False, marked=marked)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=was_syncing_itself)) \
        .when(lambda: still_argus_s(a_descriptor, platform, THIS_CLAIM)) \
        .then(it_is_still_argus_s())


@pytest.mark.unit
@pytest.mark.parametrize("floor", [THE_FLOOR, A_FLOOR_SOMEBODY_SET],
                         ids=["back-where-the-plan-found-it", "somewhere-else"])
def test_a_floor_moved_since_the_pin_is_a_change_since(floor: int) -> None:
    # This claim's floor landed and somebody moved it after - back where it was
    # included. What was found says the floor the autoscaler has now.
    platform = a_platform(floor=floor, reconciling_itself=False, marked=MARKED_BY_THIS_CLAIM)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, THIS_CLAIM)) \
        .then(it_was_changed_since(f"[{floor}]"))


@pytest.mark.unit
@pytest.mark.parametrize("marked_by", [None, ANOTHER_CLAIM],
                         ids=["unmarked", "under-another-claim"])
def test_the_floor_asked_for_without_this_claims_mark_is_a_change_since(
    marked_by: str | None
) -> None:
    # The right floor by somebody else's hand - written over Argus's since,
    # whoever wrote it.
    floor_marked = {} if marked_by is None else {MarkedObject.AUTOSCALER: marked_by}
    platform = a_platform(floor=THE_CEILING, reconciling_itself=False,
                          marked={MarkedObject.APPLICATION: THIS_CLAIM, **floor_marked})

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, THIS_CLAIM)) \
        .then(it_was_changed_since())


@pytest.mark.unit
def test_an_autoscaler_taken_away_since_the_pin_is_a_change_since() -> None:
    # Somebody removed the controller the pin held still: there is nothing of
    # Argus's left on it to watch.
    platform = a_platform(holding_an_autoscaler=False, reconciling_itself=False,
                          marked={MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, THIS_CLAIM)) \
        .then(it_was_changed_since())


@pytest.mark.unit
@pytest.mark.parametrize(
    ("was_syncing_itself", "marked"),
    [
        pytest.param(True, MARKED_BY_THIS_CLAIM,
                     id="somebody-resumed-what-this-claim-suspended"),
        pytest.param(False, {MarkedObject.AUTOSCALER: THIS_CLAIM},
                     id="somebody-turned-on-a-sync-found-off")
    ]
)
def test_a_sync_running_again_since_the_pin_is_a_change_since(
    was_syncing_itself: bool, marked: dict[MarkedObject, str]
) -> None:
    # The floor is still the one asked for, and the platform is reconciling the
    # application again - it re-applies the declared floor at its next pass, so
    # the change is not Argus's to watch any more.
    platform = a_platform(floor=THE_CEILING, reconciling_itself=True, marked=marked)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=was_syncing_itself)) \
        .when(lambda: still_argus_s(a_descriptor, platform, THIS_CLAIM)) \
        .then(it_was_changed_since())


@pytest.mark.unit
@pytest.mark.parametrize("read", ["autoscaler_of", "autoscaler_bounds",
                                  "is_syncing_itself", "mark_on"])
def test_a_pin_whose_platform_could_not_be_read_is_nobody_s_to_say(read: str) -> None:
    # Not "changed since": a read that never came back found nothing.
    platform = a_platform(floor=THE_CEILING, reconciling_itself=False,
                          marked=MARKED_BY_THIS_CLAIM)
    getattr(platform, read).side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, THIS_CLAIM)) \
        .then(nobody_can_say())


@pytest.mark.unit
def test_a_pin_asked_after_by_no_claim_is_nobody_s_to_say() -> None:
    # Whose mark the floor carries is the whole question, and a call naming no
    # claim has none to compare it with.
    no_claim = None
    platform = a_platform(floor=THE_CEILING, reconciling_itself=False,
                          marked=MARKED_BY_THIS_CLAIM)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, no_claim)) \
        .then(nobody_can_say())


@pytest.mark.unit
@pytest.mark.parametrize("floor", [THE_CEILING, A_FLOOR_SOMEBODY_SET],
                         ids=["still-argus-s", "changed-since"])
def test_asking_whether_a_pin_is_still_argus_s_writes_nothing(floor: int) -> None:
    # A read, whatever it finds: a walk asking it has decided nothing yet.
    platform = a_platform(floor=floor, reconciling_itself=False, marked=MARKED_BY_THIS_CLAIM)

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, THIS_CLAIM)) \
        .then(_nothing_was_written(platform))


@pytest.mark.unit
@pytest.mark.parametrize("marked_by", [None, ANOTHER_CLAIM],
                         ids=["unmarked", "under-another-claim"])
def test_a_floor_back_where_it_was_with_this_claims_mark_gone_is_a_change_since(
    marked_by: str | None
) -> None:
    # Both halves of the pin gone - the floor back where the plan found it, and
    # this claim's mark off the autoscaler: somebody put it back, and there is
    # nothing of Argus's left on it to watch.
    floor_marked = {} if marked_by is None else {MarkedObject.AUTOSCALER: marked_by}
    platform = a_platform(floor=THE_FLOOR, reconciling_itself=False,
                          marked={MarkedObject.APPLICATION: THIS_CLAIM, **floor_marked})

    Scenario() \
        .given(a_descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: still_argus_s(a_descriptor, platform, THIS_CLAIM)) \
        .then(it_was_changed_since())


# When this claim's mark on the autoscaler says the floor was written - a moment
# of its own, apart from the switch's, so a case can tell which one dates it.
THE_MOMENT_THE_FLOOR_WAS_MARKED = THE_MOMENT_A_MARK_SAYS + timedelta(seconds=1)
# What an autoscaler carries where this claim's floor landed and its mark says so.
THE_FLOOR_S_MARK = a_mark_found(THIS_CLAIM, written_at=THE_MOMENT_THE_FLOOR_WAS_MARKED)


@pytest.mark.unit
def test_a_pin_this_claim_made_is_found_made_and_dated_by_its_mark() -> None:
    # The floor's mark, not the switch's: the floor is the change, and the
    # suspension only what it needed first.
    platform = a_platform(floor=THE_CEILING, reconciling_itself=False,
                          marked={MarkedObject.AUTOSCALER: THE_FLOOR_S_MARK,
                                  MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: whether_it_was_made(a_plan, platform, THIS_CLAIM)) \
        .then(all_of(
            it_was_made(a_plan.descriptor, made_at=THE_MOMENT_THE_FLOOR_WAS_MARKED),
            _nothing_was_written(platform)
        ))


@pytest.mark.unit
def test_a_pin_made_under_a_mark_saying_no_moment_is_found_made_undated() -> None:
    no_moment = None
    platform = a_platform(floor=THE_CEILING, reconciling_itself=False,
                          marked={MarkedObject.AUTOSCALER: a_mark_found(THIS_CLAIM, no_moment),
                                  MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: whether_it_was_made(a_plan, platform, THIS_CLAIM)) \
        .then(it_was_made(a_plan.descriptor, made_at=no_moment))


@pytest.mark.unit
def test_a_pin_nothing_of_which_landed_has_nothing_landed_and_nothing_left() -> None:
    # The floor where the plan found it, syncing itself as the plan found it,
    # under no mark of this claim's: the write is still to make, and nothing of
    # this claim's is out there.
    no_suspension = None
    platform = a_platform(floor=THE_FLOOR, reconciling_itself=True, marked={})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: whether_it_was_made(a_plan, platform, THIS_CLAIM)) \
        .then(all_of(
            nothing_landed(left_behind=no_suspension),
            _nothing_was_written(platform)
        ))


@pytest.mark.unit
def test_a_pin_planned_with_sync_off_nothing_of_which_landed_leaves_nothing() -> None:
    # The plan found the sync off, so the pin suspends nothing: still off and
    # under no mark, there is nothing of this claim's out there to carry.
    no_suspension = None
    platform = a_platform(floor=THE_FLOOR, reconciling_itself=False, marked={})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=False)) \
        .when(lambda: whether_it_was_made(a_plan, platform, THIS_CLAIM)) \
        .then(all_of(
            nothing_landed(left_behind=no_suspension),
            _nothing_was_written(platform)
        ))


@pytest.mark.unit
def test_a_pin_whose_suspension_alone_landed_has_nothing_landed_carrying_it() -> None:
    # The suspension before the floor landed under this claim's mark, and the
    # floor did not: the write is still to make, and the answer carries the
    # plan, so a walk stopped before it writes still has what puts the
    # suspension back.
    platform = a_platform(floor=THE_FLOOR, reconciling_itself=False,
                          marked={MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: whether_it_was_made(a_plan, platform, THIS_CLAIM)) \
        .then(all_of(
            nothing_landed(left_behind=a_plan.descriptor),
            _nothing_was_written(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "a_platform_changed_since",
    [
        pytest.param(lambda: a_platform(floor=A_FLOOR_SOMEBODY_SET, reconciling_itself=False,
                                        marked=MARKED_BY_THIS_CLAIM),
                     id="this-claim-s-floor-moved-since"),
        pytest.param(lambda: a_platform(floor=THE_CEILING, reconciling_itself=False,
                                        marked={MarkedObject.AUTOSCALER: ANOTHER_CLAIM,
                                                MarkedObject.APPLICATION: THIS_CLAIM}),
                     id="the-floor-asked-for-under-another-claim"),
        pytest.param(lambda: a_platform(floor=A_FLOOR_SOMEBODY_SET),
                     id="a-floor-somebody-set"),
        pytest.param(lambda: a_platform(holding_an_autoscaler=False),
                     id="the-autoscaler-taken-away"),
        pytest.param(lambda: a_platform(floor=THE_CEILING, reconciling_itself=True,
                                        marked=MARKED_BY_THIS_CLAIM),
                     id="a-sync-somebody-resumed")
    ]
)
def test_a_pin_changed_since_its_plan_is_refused_as_the_write_refuses_it(
    a_platform_changed_since: Callable[[], Any]
) -> None:
    # The same estate, the same answer: changed since, saying whether this
    # claim's floor landed, and leaving behind what the write would.
    platform = a_platform_changed_since()

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: whether_it_was_made(a_plan, platform, THIS_CLAIM))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            it_refused_as_the_write_does(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("read", ["autoscaler_of", "autoscaler_bounds",
                                  "is_syncing_itself", "mark_on"])
def test_a_pin_whose_platform_could_not_be_read_is_refused_as_the_write_refuses_it(
    read: str
) -> None:
    platform = a_platform(floor=THE_CEILING, reconciling_itself=False,
                          marked=MARKED_BY_THIS_CLAIM)
    getattr(platform, read).side_effect = PlatformUnreachable(DONT_CARE_PLATFORM_WORDS)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: whether_it_was_made(a_plan, platform, THIS_CLAIM))) \
        .then(all_of(
            it_was_refused_as(PinRefused),
            it_refused_as_the_write_does(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_pin_plan_past_the_ceiling_is_refused_as_the_write_refuses_it() -> None:
    # The ceiling is a human's declaration, read where the floor is asked
    # after, for the read as for the write.
    platform = a_platform(floor=THE_FLOOR, ceiling=THE_CEILING)

    Scenario() \
        .given(a_plan := _a_plan_asking_for(THE_CEILING + 1)) \
        .when(attempting(lambda: whether_it_was_made(a_plan, platform, THIS_CLAIM))) \
        .then(all_of(
            it_was_refused_as(PinRefused),
            it_refused_as_the_write_does(lambda: pin_autoscaler(a_plan, platform, SOME_MARK)),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_pin_asked_after_by_no_claim_is_refused_saying_nobody_can_say() -> None:
    no_claim = None
    platform = a_platform(floor=THE_CEILING, reconciling_itself=False,
                          marked=MARKED_BY_THIS_CLAIM)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: whether_it_was_made(a_plan, platform, no_claim))) \
        .then(all_of(
            it_was_refused_as(PinRefused),
            it_is_not_said_changed_since(),
            _nothing_was_changed(platform)
        ))
