"""What Mitigation asks of the write tier, and the windows it reads its history over.

Whose a flag change was, the flag and deploy histories' windows, and the two
bundles - the writes and the reads beside them, and what puts a change back.
Which tier a seam is bound over is the type checker's to hold: the two tiers are
two classes, and a write bound to the read tier is not there to bind. What a
bundle can still get wrong is which of the tier's tools a member asks, and that
is what these say.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, Mock, create_autospec

import pytest
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged, the_answer_was
from core import to_iso
from core.models import (
    AcceleratorPinUndo,
    AutoscalerUndo,
    ChangeEvent,
    DeploymentRollbackUndo,
    FlagChange,
    FlagHistory,
    FlagUndo,
    Planned,
    ReplicaUndo,
)
from mcp_transport import ActionExhausted, McpClient, an_exhausted_action
from mitigation.tools import (
    DeploymentsBetween,
    FlagChangesSince,
    MitigationSettings,
    PerformingWrites,
    fetch_recent_deployments,
    fetch_recent_flag_changes,
    performing_writes_over,
    putting_back_over,
    set_flag,
    somebody_else_changed_flag_since,
)
from pydantic import BaseModel
from write_mcp_client import WriteTier

from mitigation_test.framework.builders import a_deployment

SOME_FLAG = "kukibuki"
THE_MOMENT_IT_WAS_CLAIMED = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)
SOME_MOMENT = to_iso(THE_MOMENT_IT_WAS_CLAIMED)
# When the write tier read the state a plan was worked out from: before the
# claim, which is the whole of what this moment says.
SOME_MOMENT_THE_PLAN_WAS_READ = THE_MOMENT_IT_WAS_CLAIMED - timedelta(seconds=2)

OTHERS_CHANGED_FLAG_TOOL = "was_flag_changed_by_others_since"
SET_FLAG_TOOL = "set_feature_flag"
ROLL_BACK_TOOL = "roll_back_deployment"
RESTORE_CONFIGURATION_TOOL = "restore_deployment"
PIN_TO_ACCELERATOR_TOOL = "pin_to_accelerator"
RESTORE_ACCELERATOR_PIN_TOOL = "restore_accelerator_pin"
PLAN_FLAG_TOOL = "plan_flag"
PLAN_ROLLBACK_TOOL = "plan_rollback"
PLAN_SCALE_OUT_TOOL = "plan_scale_out"
PLAN_AUTOSCALER_PIN_TOOL = "plan_autoscaler_pin"
PLAN_ACCELERATOR_PIN_TOOL = "plan_accelerator_pin"
FLAG_STILL_ARGUS_S_TOOL = "flag_still_argus_s"
ROLLBACK_STILL_ARGUS_S_TOOL = "rollback_still_argus_s"
SCALE_OUT_STILL_ARGUS_S_TOOL = "scale_out_still_argus_s"
AUTOSCALER_PIN_STILL_ARGUS_S_TOOL = "autoscaler_pin_still_argus_s"
ACCELERATOR_PIN_STILL_ARGUS_S_TOOL = "accelerator_pin_still_argus_s"
WHETHER_FLAG_WAS_MADE_TOOL = "whether_flag_was_made"
WHETHER_ROLLBACK_WAS_MADE_TOOL = "whether_rollback_was_made"
WHETHER_SCALE_OUT_WAS_MADE_TOOL = "whether_scale_out_was_made"
WHETHER_AUTOSCALER_PIN_WAS_MADE_TOOL = "whether_autoscaler_pin_was_made"
WHETHER_ACCELERATOR_PIN_WAS_MADE_TOOL = "whether_accelerator_pin_was_made"


SOME_APPLICATION = "io-shop"
A_ROLLBACK_TO_PUT_BACK = DeploymentRollbackUndo(
    application=SOME_APPLICATION,
    was_on_history_id=2,
    was_on_revision="0d8e826225f0de73958a8a8dd3d867b2ae249e72",
    was_syncing_itself=True
)
A_ROLLBACK_PLAN = Planned(descriptor=A_ROLLBACK_TO_PUT_BACK, since=SOME_MOMENT_THE_PLAN_WAS_READ)

SOME_CARD = "Tesla-V100-SXM2-16GB"
A_PIN_TO_PUT_BACK = AcceleratorPinUndo(
    application=SOME_APPLICATION,
    was_pinned_to=None,
    pinned_to=SOME_CARD,
    was_syncing_itself=True
)
A_PIN_PLAN = Planned(descriptor=A_PIN_TO_PUT_BACK, since=SOME_MOMENT_THE_PLAN_WAS_READ)

A_FLAG_CHANGE = FlagUndo(flag=SOME_FLAG, was_enabled=False)
# The state a put-back asks a flag back into, and finds it already in: Argus's
# own put-back, landed, whose answer was lost.
THE_STATE_IT_IS_ALREADY_BACK_IN = False
A_FLAG_PLAN = Planned(descriptor=A_FLAG_CHANGE, since=SOME_MOMENT_THE_PLAN_WAS_READ)


@pytest.mark.integration
def test_whether_anybody_else_changed_a_flag_is_asked_of_the_write_tier() -> None:
    # The provider serves its event log to admin credentials alone, so the
    # question about it is the write tier's, and it is the one tool asked:
    # whose each change was is the provider's adapter's to say, never this
    # side's to work out from the history.
    Scenario() \
        .given(
            write := _a_session_that_answers_with(None)
        ) \
        .when(
            _asking(write, lambda tier: somebody_else_changed_flag_since(
                SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED, write=tier
            ))
        ) \
        .then(
            _the_write_tier_was_asked_for(OTHERS_CHANGED_FLAG_TOOL)
        )


@pytest.mark.unit
@pytest.mark.parametrize("answer", [True, False, None],
                         ids=["yes", "no", "nobody can say"])
def test_what_the_write_tier_answers_about_a_flag_is_the_answer(answer: bool | None) -> None:
    # The provider's adapter decides each, from who the provider says made each
    # change; this side carries the answer and adds nothing - least of all a
    # `False` where the tier said nobody can say.
    Scenario() \
        .given(
            write := _a_session_that_answers_with(answer)
        ) \
        .when(
            lambda: somebody_else_changed_flag_since(SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED,
                                                     write=WriteTier(write))
        ) \
        .then(
            _it_answers(answer)
        )


@pytest.mark.unit
def test_a_write_tier_that_cannot_be_reached_answers_nothing() -> None:
    # The case that must not read as "nobody changed it": an undo would then
    # overwrite whatever somebody did since.
    Scenario() \
        .given(
            the_write_tier_is_down := _a_session_that_fails()
        ) \
        .when(
            lambda: somebody_else_changed_flag_since(SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED,
                                                     write=WriteTier(the_write_tier_is_down))
        ) \
        .then(
            _it_answers(None)
        )


@pytest.mark.unit
def test_the_way_back_answers_nobody_can_say_when_the_write_tier_cannot_be_reached() -> None:
    # The bundle's own question, not the tier's. The tier's method has the same
    # shape and would type-check in its place - and raise out of the undo where
    # this answers that nobody can say, which is what leaves a flag as found.
    Scenario() \
        .given(
            the_write_tier_is_down := _a_session_that_fails()
        ) \
        .when(
            lambda: putting_back_over(WriteTier(the_write_tier_is_down)).changed_from_outside(
                SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED
            )
        ) \
        .then(
            _it_answers(None)
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
            ).changes
        ) \
        .then(
            _it_returned_only(the_one_that_moved_at_the_onset)
        )


@pytest.mark.unit
def test_a_change_inside_the_onset_s_minute_is_in_the_window() -> None:
    # The onset is dated to its minute, and a flag switched on a few seconds
    # into the minute it broke began it. Ended at the minute's start, the window
    # would drop a flag the Investigator blames, leaving Mitigation nothing to revert.
    an_onset = THE_MOMENT_IT_WAS_CLAIMED - timedelta(days=7)
    the_one_that_moved_inside_its_minute = _a_change_at(an_onset + timedelta(seconds=5))

    Scenario() \
        .given(
            fetch := _a_provider_reporting(the_one_that_moved_inside_its_minute)
        ) \
        .when(
            lambda: fetch_recent_flag_changes(
                _some_mitigation_settings(),
                fetch=fetch,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED,
                onset=an_onset
            ).changes
        ) \
        .then(
            _it_returned_only(the_one_that_moved_inside_its_minute)
        )


@pytest.mark.unit
def test_changes_argus_made_itself_are_left_out() -> None:
    # Once Argus can act more than once on an incident its own revert lands in
    # this window, and a window carrying it turns the unambiguous case - one
    # flag changed, so that is the one to revert - into two, and refuses.
    somebody_elses = _a_change(made_by_argus=False)

    Scenario() \
        .given(
            fetch := _a_provider_reporting(
                _a_change(made_by_argus=True), somebody_elses
            )
        ) \
        .when(
            lambda: fetch_recent_flag_changes(
                _some_mitigation_settings(),
                fetch=fetch,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED
            ).changes
        ) \
        .then(
            _it_returned_only(somebody_elses)
        )


@pytest.mark.unit
def test_a_change_nobody_can_say_was_argus_own_is_kept() -> None:
    # Where Argus and its operators share one credential the provider cannot
    # tell whose a change was. Dropping it would act on a guess, and the costly
    # mistake is discarding a human's change - the real evidence.
    a_change_nobody_can_attribute = _a_change(made_by_argus=None)

    Scenario() \
        .given(
            fetch := _a_provider_reporting(a_change_nobody_can_attribute)
        ) \
        .when(
            lambda: fetch_recent_flag_changes(
                _some_mitigation_settings(),
                fetch=fetch,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED
            ).changes
        ) \
        .then(
            _it_returned_only(a_change_nobody_can_attribute)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("onset", "since", "until"), [
    (None, THE_MOMENT_IT_WAS_CLAIMED - timedelta(minutes=30), THE_MOMENT_IT_WAS_CLAIMED),
    (datetime(2026, 8, 28, 22, 15, tzinfo=UTC), datetime(2026, 8, 28, 21, 45, tzinfo=UTC),
     datetime(2026, 8, 28, 22, 16, tzinfo=UTC))
], ids=["ending-now", "ending-with-a-stated-onset-s-minute"])
def test_the_history_says_the_window_it_was_read_over(onset: datetime | None,
                                                      since: datetime,
                                                      until: datetime) -> None:
    # What the walk says it read: none changed over these minutes, rather than
    # "lately", which has no span. Ending where the filter ended it, so the
    # window said is the one the changes were kept from.
    Scenario() \
        .given(
            fetch := _a_provider_reporting()
        ) \
        .when(
            lambda: fetch_recent_flag_changes(
                _some_mitigation_settings(lookback=timedelta(minutes=30)),
                fetch=fetch,
                now=lambda: THE_MOMENT_IT_WAS_CLAIMED,
                onset=onset
            )
        ) \
        .then(
            the_answer_was(FlagHistory(changes=[], since=since, until=until))
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
                fetch, SOME_APPLICATION, a_week_earlier - some_lookback,
                a_week_earlier + timedelta(minutes=1)
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
def test_the_deploy_history_is_asked_to_leave_out_argus_s_own_deployments() -> None:
    # Argus's own flag reverts are left out, and for the same reason: where no
    # onset was stated the window ends now, so a round after Argus rolled back
    # would read its rollback as the newest deployment - and propose rolling
    # that back. Which deployments are Argus's is the platform adapter's to say,
    # so the history is asked to leave them out rather than told Argus's name.
    Scenario() \
        .given(
            fetch := _a_deploy_history_reporting()
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
            _it_asked_for_others_deployments_alone(fetch)
        )


@pytest.mark.integration
def test_the_one_write_argus_makes_goes_over_the_write_tier() -> None:
    # The tier split is enforced by absence: no read server has this tool at
    # all (spec §12.1, §13), and the read tier's class has no method for it.
    # Written from the plan the claim carries, and nothing planned again: the
    # plan was asked for before the claim.
    Scenario() \
        .given(
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(write,
                    lambda tier: performing_writes_over(tier).set_state(A_FLAG_PLAN, True))
        ) \
        .then(
            _the_write_tier_was_asked_for(SET_FLAG_TOOL)
        )


@pytest.mark.integration
def test_putting_a_flag_back_plans_it_and_writes_it_over_the_write_tier() -> None:
    # A put-back has no claim to have carried a plan, and the tier writes a flag
    # only from one - so the plan is read immediately before the write it is
    # for, both over the tier that holds the admin credential the plan's read
    # needs. The plan first: a write asked first would have nothing to compare.
    Scenario() \
        .given(
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(write,
                    lambda tier: putting_back_over(tier).set_state(SOME_FLAG, False))
        ) \
        .then(
            _the_write_tier_was_asked_for(PLAN_FLAG_TOOL, SET_FLAG_TOOL)
        )


@pytest.mark.integration
def test_a_flag_the_plan_finds_already_back_is_not_written_again() -> None:
    # A put-back whose answer was lost, asked again. The undo has just found
    # nobody but Argus has changed the flag since Argus set it, so a flag the
    # plan finds already in the state asked for is Argus's own put-back having
    # landed - and writing it a second time is a write nothing asked for.
    Scenario() \
        .given(
            write := _a_session_refusing_the_flag_as_already_as_asked()
        ) \
        .when(
            _asking(write, lambda tier: set_flag(SOME_FLAG, THE_STATE_IT_IS_ALREADY_BACK_IN,
                                                 write=tier))
        ) \
        .then(
            _the_write_tier_was_asked_for(PLAN_FLAG_TOOL)
        )


@pytest.mark.unit
def test_a_flag_the_plan_finds_already_back_is_answered_as_in_that_state() -> None:
    # Answered as put there rather than refused as spent: the put-back reads a
    # refusal as a flag it could not put back, and reports a change that is
    # back where Argus found it as one nobody can account for.
    Scenario() \
        .given(
            write := _a_session_refusing_the_flag_as_already_as_asked()
        ) \
        .when(
            lambda: set_flag(SOME_FLAG, THE_STATE_IT_IS_ALREADY_BACK_IN, write=WriteTier(write))
        ) \
        .then(
            the_answer_was(FlagUndo(flag=SOME_FLAG, was_enabled=THE_STATE_IT_IS_ALREADY_BACK_IN))
        )


@pytest.mark.integration
@pytest.mark.parametrize(("plan", "tool"), [
    pytest.param(lambda writes: writes.plan_flag(SOME_FLAG, True), PLAN_FLAG_TOOL, id="flag"),
    pytest.param(lambda writes: writes.plan_rollback(SOME_APPLICATION), PLAN_ROLLBACK_TOOL,
                 id="rollback"),
    pytest.param(lambda writes: writes.plan_scale_out(SOME_APPLICATION), PLAN_SCALE_OUT_TOOL,
                 id="scale-out"),
    pytest.param(lambda writes: writes.plan_autoscaler_pin(SOME_APPLICATION),
                 PLAN_AUTOSCALER_PIN_TOOL, id="autoscaler-pin"),
    pytest.param(lambda writes: writes.plan_accelerator_pin(SOME_APPLICATION, SOME_CARD),
                 PLAN_ACCELERATOR_PIN_TOOL, id="card-pin")
])
def test_each_plan_is_asked_of_the_write_tier(
    plan: Callable[[PerformingWrites], object], tool: str
) -> None:
    # A plan is a read, and still the write tier's: it is what that tier's
    # write compares the estate with, read through the same port the compare
    # reads through - and a flag's plan needs the admin credential only that
    # tier holds. Asked of the bundle a walk performs through, so a planner
    # bound to the wrong tool fails here rather than at the moment a walk is
    # about to claim an action.
    Scenario() \
        .given(
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(write, lambda tier: plan(performing_writes_over(tier)))
        ) \
        .then(
            _the_write_tier_was_asked_for(tool)
        )


@pytest.mark.integration
def test_returning_a_deployment_to_an_earlier_revision_goes_over_the_write_tier() -> None:
    # The third write, and one no read server has either. Asked of the bundle a
    # walk performs through, so a roller bound to the wrong tool fails here
    # rather than at the moment the walk had already decided to roll production
    # back - with the incident it was mitigating still happening.
    Scenario() \
        .given(
            write := _a_session_that_answers_with(A_ROLLBACK_TO_PUT_BACK)
        ) \
        .when(
            _asking(write, lambda tier: performing_writes_over(tier).roll_back(A_ROLLBACK_PLAN))
        ) \
        .then(
            _the_write_tier_was_asked_for(ROLL_BACK_TOOL)
        )


@pytest.mark.integration
def test_putting_a_rolled_back_deployment_back_goes_over_the_write_tier() -> None:
    # Undoing a rollback is its own tool rather than the same call reversed,
    # which is what separates it from a flag: a flag's undo is `set_state` with
    # the state the descriptor recorded, and a rollback's undo has two pieces of
    # prior state and a platform that refuses one order of them.
    Scenario() \
        .given(
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(write, lambda tier: putting_back_over(tier).restore_deployment(
                A_ROLLBACK_TO_PUT_BACK
            ))
        ) \
        .then(
            _the_write_tier_was_asked_for(RESTORE_CONFIGURATION_TOOL)
        )


@pytest.mark.integration
def test_holding_a_deployment_to_a_card_goes_over_the_write_tier() -> None:
    # Asked of the bundle a walk performs its actions through, so a pin bound to
    # the wrong tool fails here rather than at the moment a walk has decided to
    # move production's pods.
    Scenario() \
        .given(
            write := _a_session_that_answers_with(A_PIN_TO_PUT_BACK)
        ) \
        .when(
            _asking(write, lambda tier: performing_writes_over(tier).pin_to_accelerator(
                A_PIN_PLAN
            ))
        ) \
        .then(
            _the_write_tier_was_asked_for(PIN_TO_ACCELERATOR_TOOL)
        )


@pytest.mark.integration
def test_the_way_back_lets_a_deployment_off_its_card_over_the_write_tier() -> None:
    # Asked of the bundle an undo puts changes back through, as the pin above is
    # asked of the one a walk performs through - so a restorer bound to the
    # wrong tool fails here rather than at the moment a refuted pin or a
    # withdrawn incident is putting production's pods back.
    Scenario() \
        .given(
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(write, lambda tier: putting_back_over(tier).restore_accelerator_pin(
                A_PIN_TO_PUT_BACK
            ))
        ) \
        .then(
            _the_write_tier_was_asked_for(RESTORE_ACCELERATOR_PIN_TOOL)
        )


def _a_session_that_remembers_what_it_was_asked() -> Mock:
    """A session that answers nothing and records the question.

    Specced against `McpClient`, the session a `WriteTier` is asked over, so
    what a bundle's member asks is read off the one call the tier made.
    """
    client: Mock = create_autospec(McpClient, instance=True)

    return client


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


def _asking(write: Mock, ask: Callable[[WriteTier], object]) -> Callable[[], list[str]]:
    """Runs one seam over the write tier `write` is the session of, and reports
    which tools that session was asked for, in the order it was asked."""
    def step() -> list[str]:
        ask(WriteTier(write))

        return [asked.args[0] for asked in write.call.call_args_list]

    return step


def _the_write_tier_was_asked_for(*tools: str) -> Assertion[list[str]]:
    def assertion(asked: list[str]) -> bool:
        if asked != list(tools):
            raise AssertionError(
                f"Expected the write tier to be asked for {list(tools)}, "
                f"got {asked}."
            )

        return True

    return assertion


def _a_session_refusing_the_flag_as_already_as_asked() -> Mock:
    """The write tier refusing every question as an action already spent - the
    plan of a flag already in the state asked for, in the words of the refusal
    the tier builds, as the transport raises it."""
    client: Mock = create_autospec(McpClient, instance=True)
    client.call.side_effect = ActionExhausted(
        an_exhausted_action(f"flag [{SOME_FLAG}] is already OFF").words
    )

    return client


def _a_session_that_fails() -> Mock:
    """The write tier cannot be reached at all."""
    client: Mock = create_autospec(McpClient, instance=True)
    client.call.side_effect = ConnectionError("the write tier is down")

    return client


def _it_asked_from(fetch: MagicMock, moment: str) -> Assertion[object]:
    def assertion(_answer: object) -> bool:
        if fetch.call_args.kwargs != {"since": moment}:
            raise AssertionError(
                f"Expected the provider to be asked from [{moment}], "
                f"got {fetch.call_args.kwargs}."
            )

        return True

    return assertion


def _a_change(made_by_argus: bool | None) -> FlagChange:
    """A change whose only interesting property is whether the provider's
    adapter said Argus made it. The actor it was read off is the adapter's
    business, and nothing here reads it."""
    dont_care_actor = "dont-care-actor"

    return FlagChange(
        flag=SOME_FLAG, enabled=True,
        occurred_at=to_iso(THE_MOMENT_IT_WAS_CLAIMED), actor=dont_care_actor,
        made_by_argus=made_by_argus
    )


def _a_change_at(moment: datetime) -> FlagChange:
    """A change by somebody other than Argus, at a moment that matters.

    Separate from `_a_change` because the two tests care about different
    halves of the same record: that one is about who moved the flag, this is
    about when - and a builder taking both would make every call site state a
    fact it does not care about.
    """
    return FlagChange(
        flag=SOME_FLAG, enabled=True, occurred_at=to_iso(moment), actor="some-human",
        made_by_argus=False
    )


def _a_provider_reporting(*changes: FlagChange) -> MagicMock:
    fetch: MagicMock = create_autospec(FlagChangesSince)
    fetch.return_value = list(changes)

    return fetch


def _it_answers(expected: bool | None) -> Assertion[bool | None]:
    """`is` rather than `==`: `None` and `False` are the whole distinction here."""
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
    lookback: timedelta = timedelta(minutes=30)
) -> MitigationSettings:
    """How Mitigation behaves, as this suite sets it.

    The lookback is what these tests are about - how far back the window
    reaches. Whose a change was is not here: the adapter that read it says so
    on the change. The wait is never reached here, since nothing in this file
    takes an action, and neither is the cap - nothing here proposes a second
    attempt on anything.
    """
    a_wait_nothing_here_reaches = 180.0

    return MitigationSettings(
        mitigation_change_lookback_minutes=int(lookback.total_seconds() // 60),
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
        asked = {name: value for name, value in fetch.call_args.kwargs.items()
                 if name in expected}

        if asked != expected:
            raise AssertionError(
                f"Expected the deploy history to be asked for {expected}, "
                f"got {fetch.call_args.kwargs}."
            )

        return True

    return assertion


def _it_asked_for_others_deployments_alone(fetch: MagicMock) -> Assertion[list[ChangeEvent]]:
    def assertion(dont_care_deployments: list[ChangeEvent]) -> bool:
        if fetch.call_args.kwargs.get("excluding_argus_s_own") is not True:
            raise AssertionError(
                f"Expected the deploy history to be asked to leave Argus's own "
                f"deployments out, got {fetch.call_args.kwargs}."
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


# ---- what it logs ----


@pytest.mark.unit
def test_a_write_tier_that_cannot_say_whose_change_a_flag_was_is_logged(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Answered as nobody-can-say, which is right, and which loses the reason -
    # so the reason is logged here, where the exception still is.
    Scenario() \
        .given(
            the_write_tier_is_down := _a_session_that_fails()
        ) \
        .when(
            lambda: somebody_else_changed_flag_since(SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED,
                                                     write=WriteTier(the_write_tier_is_down))
        ) \
        .then(
            one_record_was_logged(caplog, "mitigation.tools", logging.WARNING,
                                  "flag history could not be read",
                                  values={"flag": SOME_FLAG}, failure=ConnectionError)
        )


SOME_REVISION_ROLLED_BACK_TO = "9a1b2c3d4e5f60718293a4b5c6d7e8f901234567"
SOME_ENTRY_ROLLED_BACK_TO = 1
SOME_COUNT_IT_WAS_RUNNING = 3
SOME_COUNT_ASKED_FOR = SOME_COUNT_IT_WAS_RUNNING * 2
SOME_FLOOR_IT_HAD = 2
SOME_FLOOR_ASKED_FOR = 8

# One change of each undoable kind, as a row records it once it was made.
A_FLAG_ARGUS_SET = FlagUndo(flag=SOME_FLAG, was_enabled=False,
                            written_at=SOME_MOMENT_THE_PLAN_WAS_READ)
A_ROLLBACK_ARGUS_MADE = A_ROLLBACK_TO_PUT_BACK.model_copy(update={
    "rolled_back_to_revision": SOME_REVISION_ROLLED_BACK_TO,
    "rolled_back_to_history_id": SOME_ENTRY_ROLLED_BACK_TO
})
A_SCALE_OUT_ARGUS_MADE = ReplicaUndo(application=SOME_APPLICATION,
                                     was_replicas=SOME_COUNT_IT_WAS_RUNNING,
                                     replicas_asked_for=SOME_COUNT_ASKED_FOR,
                                     was_syncing_itself=True)
A_PIN_ARGUS_MADE = AutoscalerUndo(application=SOME_APPLICATION,
                                  was_min_replicas=SOME_FLOOR_IT_HAD,
                                  min_replicas_asked_for=SOME_FLOOR_ASKED_FOR,
                                  was_syncing_itself=True)


@pytest.mark.integration
@pytest.mark.parametrize(("ask", "handed", "tool"), [
    pytest.param(lambda writes: writes.flag_still_argus_s(A_FLAG_PLAN, A_FLAG_ARGUS_SET),
                 {"planned": A_FLAG_PLAN, "descriptor": A_FLAG_ARGUS_SET},
                 FLAG_STILL_ARGUS_S_TOOL, id="flag"),
    pytest.param(lambda writes: writes.rollback_still_argus_s(A_ROLLBACK_ARGUS_MADE),
                 {"descriptor": A_ROLLBACK_ARGUS_MADE}, ROLLBACK_STILL_ARGUS_S_TOOL,
                 id="rollback"),
    pytest.param(lambda writes: writes.scale_out_still_argus_s(A_SCALE_OUT_ARGUS_MADE),
                 {"descriptor": A_SCALE_OUT_ARGUS_MADE}, SCALE_OUT_STILL_ARGUS_S_TOOL,
                 id="scale-out"),
    pytest.param(lambda writes: writes.autoscaler_pin_still_argus_s(A_PIN_ARGUS_MADE),
                 {"descriptor": A_PIN_ARGUS_MADE}, AUTOSCALER_PIN_STILL_ARGUS_S_TOOL,
                 id="autoscaler-pin"),
    pytest.param(lambda writes: writes.accelerator_pin_still_argus_s(A_PIN_TO_PUT_BACK),
                 {"descriptor": A_PIN_TO_PUT_BACK}, ACCELERATOR_PIN_STILL_ARGUS_S_TOOL,
                 id="card-pin")
])
def test_whether_each_change_is_still_argus_s_is_asked_of_the_write_tier(
    ask: Callable[[PerformingWrites], object], handed: dict[str, BaseModel], tool: str
) -> None:
    # A read, and the write tier's, beside the plans: it is the write's own
    # "made" rule asked without the write, read through the port the write
    # compares through - and a flag's history needs the admin credential only
    # that tier holds. Asked of the bundle a walk performs through, so a check
    # bound to the wrong tool fails here rather than at the moment a resumed
    # walk is deciding whether to watch a change it did not make. A flag's is
    # handed the claim's plan beside the change, since its history is read from
    # the plan's own read, as the write reads it.
    Scenario() \
        .given(
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(write, lambda tier: ask(performing_writes_over(tier)))
        ) \
        .then(all_of(
            _the_write_tier_was_asked_for(tool),
            _the_write_tier_was_handed(write, handed)
        ))


def _the_write_tier_was_handed(write: Mock,
                               handed: dict[str, BaseModel]) -> Assertion[list[str]]:
    """The one question the write tier was asked named each of `handed` under
    its keyword - the change as the row records it, or the plan the claim
    carries, or both - in the JSON form a tool's arguments travel in."""
    def assertion(dont_care_asked: list[str]) -> bool:
        expected = {keyword: value.model_dump(mode="json") for keyword, value in handed.items()}
        asked = [{keyword: question.kwargs.get(keyword) for keyword in handed}
                 for question in write.call.call_args_list]

        if asked != [expected]:
            raise AssertionError(
                f"Expected the write tier to be handed {expected} once, got {asked}."
            )

        return True

    return assertion


# The plans a claim carries for the two kinds the plans above leave out.
A_SCALE_OUT_PLAN = Planned(descriptor=A_SCALE_OUT_ARGUS_MADE, since=SOME_MOMENT_THE_PLAN_WAS_READ)
AN_AUTOSCALER_PIN_PLAN = Planned(descriptor=A_PIN_ARGUS_MADE,
                                 since=SOME_MOMENT_THE_PLAN_WAS_READ)


@pytest.mark.integration
@pytest.mark.parametrize(("ask", "planned", "tool"), [
    pytest.param(lambda writes: writes.whether_flag_was_made(A_FLAG_PLAN), A_FLAG_PLAN,
                 WHETHER_FLAG_WAS_MADE_TOOL, id="flag"),
    pytest.param(lambda writes: writes.whether_rollback_was_made(A_ROLLBACK_PLAN),
                 A_ROLLBACK_PLAN, WHETHER_ROLLBACK_WAS_MADE_TOOL, id="rollback"),
    pytest.param(lambda writes: writes.whether_scale_out_was_made(A_SCALE_OUT_PLAN),
                 A_SCALE_OUT_PLAN, WHETHER_SCALE_OUT_WAS_MADE_TOOL, id="scale-out"),
    pytest.param(lambda writes: writes.whether_autoscaler_pin_was_made(AN_AUTOSCALER_PIN_PLAN),
                 AN_AUTOSCALER_PIN_PLAN, WHETHER_AUTOSCALER_PIN_WAS_MADE_TOOL,
                 id="autoscaler-pin"),
    pytest.param(lambda writes: writes.whether_accelerator_pin_was_made(A_PIN_PLAN),
                 A_PIN_PLAN, WHETHER_ACCELERATOR_PIN_WAS_MADE_TOOL, id="card-pin")
])
def test_whether_each_claim_s_change_was_made_is_asked_of_the_write_tier(
    ask: Callable[[PerformingWrites], object], planned: Planned[Any], tool: str
) -> None:
    # The write's own rule on the claim's plan, asked without the write: a read,
    # and the write tier's for the plans' reason - what it compares is what the
    # write compares, through the same port. Asked of the bundle a walk performs
    # through, with the plan the claim carries, so a read bound to the wrong
    # tool, or handed anything but the plan, fails here rather than at the
    # moment a resumed walk is deciding whether to act again.
    Scenario() \
        .given(
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(write, lambda tier: ask(performing_writes_over(tier)))
        ) \
        .then(all_of(
            _the_write_tier_was_asked_for(tool),
            _the_write_tier_was_handed(write, {"planned": planned})
        ))
