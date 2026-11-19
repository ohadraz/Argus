"""Holding a deployment to one card through the platform, and letting it go.

A drain: the pods move off a class of hardware and nothing deployed changes. What
is worth pinning is the order and the record. The order is the platform's rule,
as it is for every action that changes live state under a GitOps controller - a
reconciling application has its declared pod template re-applied at the next
sync, selector included, so reconciliation is suspended first and resumed last.
The record is what the selector was before, including that there was none,
because "there was no pin" and "nobody wrote down what there was" lead an undo
to opposite actions.

Which card to pin to is not decided here. It arrives worked out from a placement
recorded before anything was done; this tier is told it, as the scale-out is told
nothing and the rollback is told nothing, and does the work.

A pin is planned before it is made, as the tier's other changes are. The plan
reads which card the pods are held to and whether the platform reconciles the
application, is dated by the platform's own clock, and changes nothing. The write
takes the plan and compares before it writes: the selector and the sync switch
are each written only where they are still what the plan found, taken as made
only where they are what it asked for under this claim's mark, and refused as
changed since otherwise - with nothing written. A refusal says what this claim's
marks show already landed: where its suspension still stands, the plan travels
on the refusal as what it left behind.

And a withdrawal lets go only of what is still Argus's. Pods still held to the card
Argus pinned them to are let go; pods already back where Argus found them need no
write; any other selector is somebody's since, and is left as they set it - with
the reconciliation Argus suspended left suspended where it still is, since
resuming it would have the platform re-apply git over them.

How Argo CD is asked any of this - the selectors, a merge patch carried as text,
a null that removes a key - is the adapter's, and pinned in its own suite.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
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
)
from core.mcp_transport import (
    EXHAUSTED_ACTION_MARKER,
    LEFT_BEHIND_MARKER,
    UNREACHABLE_PLATFORM_MARKER,
    what_was_left_behind,
)
from core.models import AcceleratorPinRestored, AcceleratorPinUndo, Planned
from deployment_platform import (
    DeploymentPlatformWrites,
    MarkedObject,
    PlatformRefused,
    PlatformUnreachable,
)
from write_mcp_server.accelerators import (
    AcceleratorPinRefused,
    AlreadyPinned,
    pin_to_accelerator,
    plan_accelerator_pin,
    restore_accelerator_pin,
)

from write_mcp_server_test.framework.marks import (
    ANOTHER_CLAIM,
    THIS_CLAIM,
    a_mark,
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

SOME_APPLICATION = "io-shop"
# What every pin and restore here is made under. One for the file: which action
# a write is for is the caller's, and what is asserted is only that the writes
# carry it.
SOME_MARK = a_mark()

# The platform's own clock when a plan reads it.
SOME_TIME_ON_THE_PLATFORM = datetime(2026, 11, 18, 13, 4, 30, tzinfo=UTC)
# When a plan handed to a write was read. The write compares what it finds with
# what the plan says, never with when.
DONT_CARE_SINCE = datetime(2026, 11, 18, 13, 0, tzinfo=UTC)

THE_FLEETS_CARD = "Tesla-V100-SXM2-16GB"
SOME_OTHER_CARD = "NVIDIA-A100-SXM4-40GB"
# A card somebody held the pods to since, which is neither of the two above.
A_CARD_SOMEBODY_CHOSE = "Tesla-T4"

# What a pin onto a deployment held to no card leaves, where it suspended the
# sync and the pods were never moved.
THE_SUSPENSION = AcceleratorPinUndo(
    application=SOME_APPLICATION,
    was_pinned_to=None,
    pinned_to=THE_FLEETS_CARD,
    was_syncing_itself=True
)


def a_platform(pinned_to: str | None = None,
               reconciling_itself: bool = True,
               marked: dict[MarkedObject, str] | None = None) -> Any:
    """A platform whose pods are held to `pinned_to`, its objects carrying the
    claims `marked` names by object - none, unless a case says so."""
    platform = create_autospec(DeploymentPlatformWrites, instance=True)
    platform.accelerator_pin_of.return_value = pinned_to
    platform.is_syncing_itself.return_value = reconciling_itself
    platform.now.return_value = SOME_TIME_ON_THE_PLATFORM

    marks = marked or {}
    platform.mark_on.side_effect = lambda application, kind: marks.get(kind)

    return platform


def a_platform_as_the_pin_left_it(pinned_to: str | None = THE_FLEETS_CARD,
                                  reconciling_itself: bool = False) -> Any:
    """A platform a pin of Argus's has been through: the pods held to the card
    the pin named unless a case names another, and not syncing itself, because
    the pin suspended that, unless a case says somebody turned it back on."""
    return a_platform(pinned_to=pinned_to, reconciling_itself=reconciling_itself)


@pytest.mark.unit
def test_a_plan_records_no_pin_where_there_was_none() -> None:
    platform = a_platform(pinned_to=None, reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_accelerator_pin(SOME_APPLICATION, THE_FLEETS_CARD, platform)) \
        .then(_the_plan_carries(AcceleratorPinUndo(
            application=SOME_APPLICATION,
            was_pinned_to=None,
            pinned_to=THE_FLEETS_CARD,
            was_syncing_itself=True
        )))


@pytest.mark.unit
def test_a_plan_records_the_pin_it_replaces_and_sync_as_found_off() -> None:
    platform = a_platform(pinned_to=SOME_OTHER_CARD, reconciling_itself=False)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_accelerator_pin(SOME_APPLICATION, THE_FLEETS_CARD, platform)) \
        .then(_the_plan_carries(AcceleratorPinUndo(
            application=SOME_APPLICATION,
            was_pinned_to=SOME_OTHER_CARD,
            pinned_to=THE_FLEETS_CARD,
            was_syncing_itself=False
        )))


@pytest.mark.unit
def test_a_plan_is_dated_by_the_platforms_own_clock() -> None:
    # What a resumed walk asks "has anybody changed it since?" from.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: plan_accelerator_pin(SOME_APPLICATION, THE_FLEETS_CARD, platform)) \
        .then(_the_plan_is_dated(SOME_TIME_ON_THE_PLATFORM))


@pytest.mark.unit
def test_a_plan_reads_the_platforms_clock_before_the_state_it_dates() -> None:
    # A time read after the state could postdate a change the plan never saw,
    # and a later "nothing changed since" would then hide it.
    platform = a_platform()

    Scenario() \
        .given(platform) \
        .when(lambda: plan_accelerator_pin(SOME_APPLICATION, THE_FLEETS_CARD, platform)) \
        .then(_the_time_was_read_first(platform))


@pytest.mark.unit
def test_a_plan_changes_nothing() -> None:
    # It is read before the claim is written, so anything it wrote would be a
    # change no claim accounts for.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(platform) \
        .when(lambda: plan_accelerator_pin(SOME_APPLICATION, THE_FLEETS_CARD, platform)) \
        .then(_nothing_was_written(platform))


@pytest.mark.unit
def test_a_deployment_already_pinned_to_the_card_is_refused_by_the_plan() -> None:
    # Nothing to move. A caller told "done" would record a mitigation that never
    # happened and judge the service against it, so the action is reported
    # exhausted and the walk moves on.
    platform = a_platform(pinned_to=THE_FLEETS_CARD)

    Scenario() \
        .given(platform) \
        .when(attempting(
            lambda: plan_accelerator_pin(SOME_APPLICATION, THE_FLEETS_CARD, platform)
        )) \
        .then(all_of(
            an_error_was_raised(AlreadyPinned),
            _the_refusal_says_the_action_is_exhausted(),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_platform_that_never_answered_the_read_is_reported_as_unreachable() -> None:
    platform = a_platform()
    platform.accelerator_pin_of.side_effect = PlatformUnreachable("503")

    Scenario() \
        .given(platform) \
        .when(attempting(
            lambda: plan_accelerator_pin(SOME_APPLICATION, THE_FLEETS_CARD, platform)
        )) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_platform_that_refused_the_read_is_not_reported_as_unreachable() -> None:
    # It answered, so every other action through it is still there to try - and
    # nothing was touched, because the read is the first thing a pin asks.
    platform = a_platform()
    platform.accelerator_pin_of.side_effect = PlatformRefused("403")

    Scenario() \
        .given(platform) \
        .when(attempting(
            lambda: plan_accelerator_pin(SOME_APPLICATION, THE_FLEETS_CARD, platform)
        )) \
        .then(all_of(
            _it_is_not_reported_as_an_unreachable_platform(),
            _it_pinned(platform, [])
        ))


@pytest.mark.unit
def test_a_platform_that_would_not_say_its_time_is_not_planned_on() -> None:
    # A plan with no date is one a resumed walk could not ask "since when?" of.
    platform = a_platform()
    platform.now.side_effect = PlatformUnreachable("503")

    Scenario() \
        .given(platform) \
        .when(attempting(
            lambda: plan_accelerator_pin(SOME_APPLICATION, THE_FLEETS_CARD, platform)
        )) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_card_the_platform_would_not_name_is_known_to_have_changed_nothing() -> None:
    # Nothing had been asked to change, so however the read failed, nothing did.
    platform = a_platform()
    platform.accelerator_pin_of.side_effect = PlatformRefused("403")

    Scenario() \
        .given(platform) \
        .when(attempting(
            lambda: plan_accelerator_pin(SOME_APPLICATION, THE_FLEETS_CARD, platform)
        )) \
        .then(all_of(
            it_was_refused_as(AcceleratorPinRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_asking_whether_it_syncs_itself_is_a_read_and_changes_nothing() -> None:
    platform = a_platform()
    platform.is_syncing_itself.side_effect = PlatformUnreachable(
        "timed out", known_not_applied=False
    )

    Scenario() \
        .given(platform) \
        .when(attempting(
            lambda: plan_accelerator_pin(SOME_APPLICATION, THE_FLEETS_CARD, platform)
        )) \
        .then(all_of(
            it_is_marked_unreachable(True),
            what_it_left_is_known(True),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_pin_holds_the_deployment_to_the_card_its_plan_named() -> None:
    platform = a_platform(pinned_to=None)

    Scenario() \
        .given(a_plan := _a_plan()) \
        .when(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK)) \
        .then(_it_pinned(platform, [THE_FLEETS_CARD]))


@pytest.mark.unit
def test_a_pin_answers_with_the_descriptor_its_plan_carried() -> None:
    platform = a_platform(pinned_to=None)

    Scenario() \
        .given(a_plan := _a_plan()) \
        .when(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK)) \
        .then(_it_answered_with(a_plan.descriptor))


@pytest.mark.unit
def test_reconciliation_is_suspended_before_the_pin() -> None:
    # A pin taken under automated sync is a mitigation with a timer on it: the
    # next sync re-applies the declared template and takes the selector off.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK)) \
        .then(_it_was_asked_in_order(platform, "suspend_sync", "pin_to_accelerator"))


@pytest.mark.unit
def test_every_write_a_pin_makes_carries_its_actions_mark() -> None:
    # The suspension and the selector alike: either left on the platform
    # unmarked is a change nobody can tell from a person's.
    platform = a_platform(reconciling_itself=True)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK)) \
        .then(all_of(
            every_write_carried(platform, "suspend_sync", SOME_MARK),
            every_write_carried(platform, "pin_to_accelerator", SOME_MARK)
        ))


@pytest.mark.unit
def test_an_application_nobody_was_reconciling_is_left_alone() -> None:
    platform = a_platform(reconciling_itself=False)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=False)) \
        .when(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK)) \
        .then(_the_sync_policy_was_not_touched(platform))


@pytest.mark.unit
def test_a_pin_replacing_another_card_where_the_plan_found_it_is_written() -> None:
    # Held to the card the plan found, under an earlier claim of Argus's: what
    # the plan planned from, not a change since.
    platform = a_platform(pinned_to=SOME_OTHER_CARD,
                          marked={MarkedObject.DEPLOYMENT: ANOTHER_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_pinned_to=SOME_OTHER_CARD)) \
        .when(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK)) \
        .then(_it_pinned(platform, [THE_FLEETS_CARD]))


@pytest.mark.unit
@pytest.mark.parametrize("was_syncing_itself", [True, False],
                         ids=["argus-suspended-the-sync", "the-sync-was-already-off"])
def test_a_pin_this_claim_already_made_is_answered_as_made_and_writes_nothing(
    was_syncing_itself: bool
) -> None:
    # The same write asked again - a reply lost on the way back, a walk resumed
    # after its worker died. The pods are held to the card asked for and the
    # Deployment carries this claim's mark, so the first asking made it:
    # answered as made, not as exhausted, and nothing written twice. The
    # Application carries this claim's mark only where this claim suspended its
    # sync.
    suspended_by_this_claim = {MarkedObject.APPLICATION: THIS_CLAIM} if was_syncing_itself else {}
    platform = a_platform(pinned_to=THE_FLEETS_CARD, reconciling_itself=False,
                          marked={MarkedObject.DEPLOYMENT: THIS_CLAIM, **suspended_by_this_claim})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=was_syncing_itself)) \
        .when(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_answered_with(a_plan.descriptor)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("marked_by", [None, ANOTHER_CLAIM],
                         ids=["unmarked", "under-another-claim"])
def test_pods_on_the_card_the_plan_named_without_this_claims_mark_are_changed_since(
    marked_by: str | None
) -> None:
    # The right card by somebody else's hand. Taking it as made would claim a
    # change Argus did not make, and a withdrawal would then let go of a pin
    # that was never Argus's.
    platform = a_platform(pinned_to=THE_FLEETS_CARD,
                          marked={} if marked_by is None else {MarkedObject.DEPLOYMENT: marked_by})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("held_to", [None, A_CARD_SOMEBODY_CHOSE],
                         ids=["back-where-the-plan-found-them", "on-another-card"])
def test_pods_under_this_claims_mark_but_not_on_its_card_are_changed_since(
    held_to: str | None
) -> None:
    # This claim's pin landed - the suspension and the selector, both under its
    # mark - and somebody moved the pods after it, back where they were
    # included. Redoing it would write over them. The suspension still stands,
    # so the refusal carries the plan, which is what a withdrawal puts it back
    # from.
    platform = a_platform(pinned_to=held_to, reconciling_itself=False,
                          marked={MarkedObject.DEPLOYMENT: THIS_CLAIM,
                                  MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_pinned_to=None, was_syncing_itself=True)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(True),
            it_left_behind(a_plan.descriptor),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("held_to", [A_CARD_SOMEBODY_CHOSE, None],
                         ids=["held-to-another-card", "let-go-of-every-card"])
def test_a_pin_somebody_changed_since_the_plan_is_refused_before_anything_is_written(
    held_to: str | None
) -> None:
    # Before the sync switch too: a suspension written ahead of a refused pin
    # would be a change the refusal does not account for. A selector somebody
    # took off is a change as much as one somebody moved.
    platform = a_platform(pinned_to=held_to, reconciling_itself=True)

    Scenario() \
        .given(a_plan := _a_plan(was_pinned_to=SOME_OTHER_CARD)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            it_is_marked_unreachable(False),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_pods_somebody_moved_under_this_claims_suspension_leave_the_suspension() -> None:
    # The suspension landed under this claim and the pin did not, and somebody
    # held the pods to a card of their own in between. Nothing is written over
    # them, and the switch this claim turned off is still off - so the refusal
    # carries the plan, which is what puts it back on.
    platform = a_platform(pinned_to=A_CARD_SOMEBODY_CHOSE, reconciling_itself=False,
                          marked={MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_pinned_to=None, was_syncing_itself=True)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            it_left_behind(a_plan.descriptor),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("found_on", [THE_FLEETS_CARD, SOME_OTHER_CARD],
                         ids=["the-fleet-s-card", "another-card"])
def test_a_plan_pinning_the_pods_where_it_found_them_is_refused_by_the_write(
    found_on: str
) -> None:
    # The write holds the plan to the plan step's own rule from the plan's own
    # "was": a pin moves the pods somewhere they were not held. One naming where
    # it found them moves nothing, and would be judged as though it had. Refused
    # plainly, before the sync switch is touched.
    platform = a_platform(pinned_to=found_on)
    pinning_where_found = Planned[AcceleratorPinUndo](
        descriptor=AcceleratorPinUndo(application=SOME_APPLICATION, was_pinned_to=found_on,
                                      pinned_to=found_on, was_syncing_itself=True),
        since=DONT_CARE_SINCE
    )

    Scenario() \
        .given(pinning_where_found) \
        .when(attempting(lambda: pin_to_accelerator(pinning_where_found, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as(AcceleratorPinRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_sync_this_claim_suspended_is_not_suspended_again() -> None:
    # The suspension landed under this claim and the pin did not: the pin is
    # written, and the switch is left where this claim put it.
    platform = a_platform(pinned_to=None, reconciling_itself=False,
                          marked={MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_pinned(platform, [THE_FLEETS_CARD])
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
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_sync_running_again_under_this_claims_mark_is_changed_since() -> None:
    # Argus suspended it under this claim and it is reconciling again, so
    # somebody turned it back on. Suspending it again would overrule them.
    platform = a_platform(pinned_to=None, reconciling_itself=True,
                          marked={MarkedObject.APPLICATION: THIS_CLAIM})

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_sync_turned_on_since_a_plan_that_found_it_off_is_changed_since() -> None:
    # A pin written now would be taken off at the next sync, and the descriptor
    # would say the sync was never Argus's to put back.
    platform = a_platform(pinned_to=None, reconciling_itself=True)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=False)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as_changed_since(),
            its_change_is_said_performed(False),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("read", ["accelerator_pin_of", "is_syncing_itself", "mark_on"])
def test_a_pin_that_could_not_read_what_is_there_now_writes_nothing(read: str) -> None:
    # The compare is what makes the write safe to ask, and a compare against a
    # read that never came back is no compare at all.
    platform = a_platform(pinned_to=None)
    getattr(platform, read).side_effect = PlatformUnreachable("503")

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as(AcceleratorPinRefused),
            what_it_left_is_known(True),
            it_left_behind(None),
            _nothing_was_changed(platform)
        ))


@pytest.mark.unit
def test_a_platform_unavailable_when_sync_is_suspended_is_reported_as_unreachable() -> None:
    # The suspension is the first thing a pin changes, so a platform that said
    # it did not handle it has left the estate as it found it, and the card was
    # never asked for.
    platform = a_platform(reconciling_itself=True)
    platform.suspend_sync.side_effect = PlatformUnreachable("503", known_not_applied=True)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _it_pinned(platform, [])
        ))


@pytest.mark.unit
def test_a_pin_that_left_sync_suspended_says_so_and_still_reports_the_platform() -> None:
    # The platform went away between the suspension and the pin, so what is left
    # behind is the suspension alone - and it travels on the failure, so the walk
    # can narrow itself and still know an application is sitting un-reconciled.
    platform = a_platform(pinned_to=None, reconciling_itself=True)
    platform.pin_to_accelerator.side_effect = PlatformUnreachable(
        "no route to host", known_not_applied=True
    )

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            _it_is_reported_as_an_unreachable_platform(),
            _it_says_what_it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_suspension_whose_answer_was_lost_is_not_said_to_have_changed_nothing() -> None:
    platform = a_platform()
    platform.suspend_sync.side_effect = PlatformUnreachable(
        "timed out", known_not_applied=False
    )

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_was_refused_as(AcceleratorPinRefused),
            it_is_marked_unreachable(False),
            what_it_left_is_known(False),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_pin_rejected_after_sync_was_suspended_says_the_suspension_is_left() -> None:
    platform = a_platform(pinned_to=None, reconciling_itself=True)
    platform.pin_to_accelerator.side_effect = PlatformRefused("400", known_not_applied=True)

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(True),
            it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_pin_whose_answer_was_lost_carries_the_suspension_and_no_more() -> None:
    # The pods may be moving this second. The suspension is carried, and
    # nothing is said to be all of it.
    platform = a_platform(pinned_to=None, reconciling_itself=True)
    platform.pin_to_accelerator.side_effect = PlatformUnreachable(
        "timed out", known_not_applied=False
    )

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(all_of(
            it_is_marked_unreachable(False),
            what_it_left_is_known(False),
            it_left_behind(THE_SUSPENSION)
        ))


@pytest.mark.unit
def test_a_platform_that_answered_and_refused_is_not_reported_as_unreachable() -> None:
    platform = a_platform(reconciling_itself=False)
    platform.pin_to_accelerator.side_effect = PlatformRefused("400")

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=False)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(_it_is_not_reported_as_an_unreachable_platform())


@pytest.mark.unit
def test_every_write_a_restore_makes_carries_its_mark() -> None:
    platform = a_platform_as_the_pin_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(all_of(
            every_write_carried(platform, "pin_to_accelerator", SOME_MARK),
            every_write_carried(platform, "resume_sync", SOME_MARK)
        ))


@pytest.mark.unit
def test_restoring_takes_the_pin_off_where_there_was_none() -> None:
    platform = a_platform_as_the_pin_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_pinned_to=None)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _it_pinned(platform, [None]),
            _it_reports_restored(pin=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_restoring_puts_back_the_pin_somebody_else_had_set() -> None:
    platform = a_platform_as_the_pin_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_pinned_to=SOME_OTHER_CARD)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(_it_pinned(platform, [SOME_OTHER_CARD]))


@pytest.mark.unit
def test_the_pin_is_put_back_before_reconciliation_is() -> None:
    # Turning reconciliation on first would have the platform take the selector
    # off on its own - unverifiably, at a moment nothing here chose.
    platform = a_platform_as_the_pin_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(_it_was_asked_in_order(platform, "pin_to_accelerator", "resume_sync"))


@pytest.mark.unit
def test_restoring_leaves_reconciliation_off_where_argus_found_it_off() -> None:
    platform = a_platform_as_the_pin_left_it()

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=False)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _the_sync_policy_was_not_touched(platform),
            _it_reports_restored(pin=True, automated_sync=True)
        ))


@pytest.mark.unit
def test_a_restore_that_only_managed_the_pin_says_so() -> None:
    platform = a_platform_as_the_pin_left_it()
    platform.resume_sync.side_effect = PlatformRefused("409")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(_it_reports_restored(pin=True, automated_sync=False))


@pytest.mark.unit
def test_a_restore_that_could_not_reach_the_platform_at_all_says_so() -> None:
    platform = a_platform_as_the_pin_left_it()
    platform.pin_to_accelerator.side_effect = PlatformUnreachable("503")
    platform.resume_sync.side_effect = PlatformUnreachable("503")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(_it_reports_restored(pin=False, automated_sync=False))


@pytest.mark.unit
def test_a_pin_still_argus_s_is_let_go_and_said_to_be_nobody_else_s() -> None:
    # The pods are still held to the card Argus pinned them to.
    platform = a_platform_as_the_pin_left_it(pinned_to=THE_FLEETS_CARD)

    Scenario() \
        .given(descriptor := _a_descriptor(was_pinned_to=None)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _it_pinned(platform, [None]),
            _it_reports_restored(pin=True, automated_sync=True),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_pods_already_back_where_argus_found_them_are_not_written_again() -> None:
    # Somebody - anybody - has already let them go. Nothing is written for the
    # pin, and it counts as put back; the sync Argus suspended is still Argus's
    # to resume.
    platform = a_platform_as_the_pin_left_it(pinned_to=SOME_OTHER_CARD)

    Scenario() \
        .given(descriptor := _a_descriptor(was_pinned_to=SOME_OTHER_CARD)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _it_pinned(platform, []),
            every_write_carried(platform, "resume_sync", SOME_MARK),
            _it_reports_restored(pin=True, automated_sync=True),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
@pytest.mark.parametrize("somebody_s", [A_CARD_SOMEBODY_CHOSE, None],
                         ids=["held-to-another-card", "let-go-of-every-card"])
def test_a_pin_somebody_changed_since_is_left_as_they_set_it(somebody_s: str | None) -> None:
    # Putting the selector back would replace their decision, and resuming sync
    # would have the platform re-apply git over it - so neither is written. A
    # selector somebody took off is a change as much as one somebody moved.
    platform = a_platform_as_the_pin_left_it(pinned_to=somebody_s)

    Scenario() \
        .given(descriptor := _a_descriptor(was_pinned_to=SOME_OTHER_CARD)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _nothing_was_written(platform),
            it_was_left_because(*([] if somebody_s is None else [f"[{somebody_s}]"]))
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
def test_a_pin_left_as_somebody_set_it_says_whether_argus_s_suspension_still_stands(
    was_syncing_itself: bool, syncing_now: bool, still_suspended: bool
) -> None:
    # Read from the platform, because only it knows: a person who reverted in
    # git and turned sync back on has ended Argus's suspension themselves, and
    # one sync was off for before Argus came was never suspended by Argus.
    platform = a_platform_as_the_pin_left_it(pinned_to=A_CARD_SOMEBODY_CHOSE,
                                             reconciling_itself=syncing_now)

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=was_syncing_itself)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _nothing_was_written(platform),
            the_suspension_is_said_to_stand(still_suspended)
        ))


@pytest.mark.unit
def test_a_restore_that_could_not_read_which_card_the_pods_are_held_to_writes_nothing(
) -> None:
    # Writing on a reading that never came back is the blind put-back the check
    # exists to prevent - so neither half is written, neither is said to be
    # back, and nothing is said to have been found.
    platform = a_platform_as_the_pin_left_it()
    platform.accelerator_pin_of.side_effect = PlatformUnreachable("503")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(pin=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_restore_that_could_not_read_whether_sync_is_back_on_writes_nothing() -> None:
    # The last read, made only where the pin is somebody's: without it nobody
    # can say whether Argus's suspension still stands, and the answer says
    # nothing it could not establish.
    platform = a_platform_as_the_pin_left_it(pinned_to=A_CARD_SOMEBODY_CHOSE)
    platform.is_syncing_itself.side_effect = PlatformRefused("403")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(all_of(
            _nothing_was_written(platform),
            _it_reports_restored(pin=False, automated_sync=False),
            it_was_not_left_alone()
        ))


@pytest.mark.unit
def test_a_pin_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production, and what it changed.
    platform = a_platform()

    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            a_plan := _a_plan()
        ) \
        .when(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.accelerators", logging.INFO,
                                  "deployment pinned to accelerator",
                                  values={"application": SOME_APPLICATION,
                                          "accelerator": THE_FLEETS_CARD})
        )


@pytest.mark.unit
def test_a_pin_refused_after_sync_was_suspended_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The refusal leaves reconciliation off on purpose, and the line says so:
    # an application nobody is reconciling looks healthy until the next deploy
    # quietly does not arrive.
    platform = a_platform(reconciling_itself=True)
    platform.pin_to_accelerator.side_effect = PlatformRefused("400")

    Scenario() \
        .given(a_plan := _a_plan(was_syncing_itself=True)) \
        .when(attempting(lambda: pin_to_accelerator(a_plan, platform, SOME_MARK))) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.accelerators", logging.WARNING,
                                  "accelerator pin refused",
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
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.accelerators", logging.INFO,
                                  "accelerator pin restored",
                                  values={"application": SOME_APPLICATION})
        )


@pytest.mark.unit
def test_a_restore_that_only_managed_the_pin_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The quiet half. The application looks put back and is receiving nothing
    # anybody ships to it, and no other line would say so.
    platform = a_platform_as_the_pin_left_it()
    platform.resume_sync.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.accelerators", logging.WARNING,
                                  "accelerator pin not fully restored",
                                  values={"application": SOME_APPLICATION,
                                          "pin_put_back": True,
                                          "automated_sync_put_back": False})
        )


@pytest.mark.unit
def test_a_restore_step_that_failed_is_logged_as_an_error(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The restore reports which half it lost, never why. The why is here, and
    # it is what a person putting the other half back by hand needs first.
    platform = a_platform_as_the_pin_left_it()
    platform.resume_sync.side_effect = PlatformUnreachable("no route to host")

    Scenario() \
        .given(descriptor := _a_descriptor(was_syncing_itself=True)) \
        .when(lambda: restore_accelerator_pin(descriptor, platform, SOME_MARK)) \
        .then(
            one_record_was_logged(caplog, "write_mcp_server.accelerators", logging.ERROR,
                                  "restore step failed",
                                  values={"application": SOME_APPLICATION,
                                          "step": "automated sync"},
                                  failure=PlatformUnreachable)
        )


def _a_descriptor(was_pinned_to: str | None = None,
                  was_syncing_itself: bool = True) -> AcceleratorPinUndo:
    return AcceleratorPinUndo(
        application=SOME_APPLICATION,
        was_pinned_to=was_pinned_to,
        pinned_to=THE_FLEETS_CARD,
        was_syncing_itself=was_syncing_itself
    )


def _a_plan(was_pinned_to: str | None = None,
            was_syncing_itself: bool = True) -> Planned[AcceleratorPinUndo]:
    """The plan a pin to the fleet's card makes, from the card it found."""
    return Planned(descriptor=_a_descriptor(was_pinned_to, was_syncing_itself),
                   since=DONT_CARE_SINCE)


def _nothing_was_written(platform: Any) -> Assertion[object]:
    """Neither the selector nor the sync policy - the reads are what an action
    that left the pods alone did ask."""
    def assertion(dont_care_result: object) -> bool:
        written = [name for name, operation in (
            ("the pin", platform.pin_to_accelerator),
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


def _it_pinned(platform: Any, cards: list[str | None]) -> Assertion[object]:
    """The cards pinned to, in turn - the mark each carried is
    `every_write_carried`'s to say."""
    def assertion(dont_care_result: object) -> bool:
        asked = [call.args[:2] for call in platform.pin_to_accelerator.call_args_list]
        expected = [(SOME_APPLICATION, card) for card in cards]

        if asked != expected:
            raise AssertionError(
                f"Expected the platform to be asked to pin {expected}, and it was "
                f"asked {asked}."
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
                ("the pin", platform.pin_to_accelerator),
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


def _the_plan_carries(expected: AcceleratorPinUndo) -> Assertion[Planned[AcceleratorPinUndo]]:
    def assertion(plan: Planned[AcceleratorPinUndo]) -> bool:
        if plan.descriptor != expected:
            raise AssertionError(
                f"Expected the plan to carry {expected!r}, and it carries "
                f"{plan.descriptor!r}."
            )

        return True

    return assertion


def _the_plan_is_dated(since: datetime) -> Assertion[Planned[AcceleratorPinUndo]]:
    def assertion(plan: Planned[AcceleratorPinUndo]) -> bool:
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


def _it_answered_with(expected: AcceleratorPinUndo) -> Assertion[AcceleratorPinUndo]:
    def assertion(descriptor: AcceleratorPinUndo) -> bool:
        if descriptor != expected:
            raise AssertionError(
                f"Expected the pin to answer with {expected!r}, and it answered "
                f"with {descriptor!r}."
            )

        return True

    return assertion


def _the_refusal_says_the_action_is_exhausted() -> Assertion[Exception | None]:
    def assertion(refusal: Exception | None) -> bool:
        if refusal is None or EXHAUSTED_ACTION_MARKER not in str(refusal):
            raise AssertionError(
                f"Expected the refusal to carry [{EXHAUSTED_ACTION_MARKER}], so "
                f"that a caller can tell an exhausted action from a broken "
                f"platform, and it said [{refusal}]."
            )

        return True

    return assertion


def _it_is_reported_as_an_unreachable_platform() -> Assertion[Exception | None]:
    def assertion(raised: Exception | None) -> bool:
        if not isinstance(raised, AcceleratorPinRefused):
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
        if not isinstance(raised, AcceleratorPinRefused):
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


def _it_reports_restored(pin: bool,
                         automated_sync: bool) -> Assertion[AcceleratorPinRestored]:
    def assertion(restored: AcceleratorPinRestored) -> bool:
        reported = (restored.pin_put_back, restored.automated_sync_put_back)

        if reported != (pin, automated_sync):
            raise AssertionError(
                f"Expected the pin put back to be [{pin}] and automated sync to "
                f"be [{automated_sync}], and it reported {reported}."
            )

        return True

    return assertion


def _it_says_what_it_left_behind(
    expected: AcceleratorPinUndo
) -> Assertion[Exception | None]:
    """The refusal carries the descriptor, and carries the right one."""
    def assertion(raised: Exception | None) -> bool:
        if LEFT_BEHIND_MARKER not in str(raised):
            raise AssertionError(
                f"Expected the refusal to say what it left behind, and it said "
                f"[{raised}]."
            )

        left_behind = what_was_left_behind(str(raised))

        if left_behind != expected:
            raise AssertionError(
                f"Expected the refusal to leave behind {expected!r}, and it left "
                f"{left_behind!r}."
            )

        return True

    return assertion
