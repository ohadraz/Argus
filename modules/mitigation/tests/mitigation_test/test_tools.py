"""Asking the flag provider whether a half-finished action actually landed.

A worker that died between taking an action and recording what came of it
leaves a claim with no outcome. Only the provider knows whether the change was
made, and this is the one place Argus asks it that question about itself.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import NamedTuple, Protocol
from unittest.mock import MagicMock, Mock, create_autospec

import pytest
from argus_testkit import Assertion, Scenario, all_of, one_record_was_logged, the_answer_was
from core import to_iso
from core.mcp_transport import ActionExhausted, McpClient, an_exhausted_action
from core.models import (
    AcceleratorPinUndo,
    ChangeEvent,
    DeploymentRollbackUndo,
    FlagChange,
    FlagHistory,
    FlagUndo,
    Planned,
)
from mitigation.tools import (
    DeploymentsBetween,
    FlagChangesSince,
    MitigationSettings,
    PerformingWrites,
    accelerator_pin_restorer_over,
    argus_changed_flag_since,
    deployment_restorer_over,
    deployment_roller_over,
    deployments_over,
    fetch_recent_deployments,
    fetch_recent_flag_changes,
    flag_changes_over,
    flag_setter_over,
    performing_writes_over,
    putting_back_over,
    recent_metrics_over,
    rollout_progress_over,
    rules_read_over,
    somebody_else_changed_flag_since,
)

from mitigation_test.framework.builders import (
    a_deployment,
)

SOME_FLAG = "kukibuki"
SOME_ARGUS_USER = "Shuki Tuki"
THE_MOMENT_IT_WAS_CLAIMED = datetime(2026, 9, 4, 22, 15, tzinfo=UTC)
SOME_MOMENT = to_iso(THE_MOMENT_IT_WAS_CLAIMED)
# When the write tier read the state a plan was worked out from: before the
# claim, which is the whole of what this moment says.
SOME_MOMENT_THE_PLAN_WAS_READ = THE_MOMENT_IT_WAS_CLAIMED - timedelta(seconds=2)

ROLLOUT_PROGRESS_TOOL = "get_rollout_progress"

METRICS_TOOL = "get_metrics_summary"
ALERT_RULE_TOOL = "get_alert_rule"
FLAG_CHANGES_TOOL = "get_recent_flag_changes"
ARGUS_CHANGED_FLAG_TOOL = "was_flag_changed_by_argus_since"
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

CHANGE_EVENTS_TOOL = "get_change_events"

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


class _AboutAFlag(Protocol):
    """Either question asked about one flag's history over the write tier."""

    def __call__(self, flag: str, since: datetime, *, client: McpClient) -> bool | None: ...


@pytest.mark.integration
@pytest.mark.parametrize(("ask", "tool"), [
    (argus_changed_flag_since, ARGUS_CHANGED_FLAG_TOOL),
    (somebody_else_changed_flag_since, OTHERS_CHANGED_FLAG_TOOL)
], ids=["whether argus changed it", "whether anybody else did"])
def test_whose_change_a_flag_was_is_asked_over_the_write_tier(
    ask: _AboutAFlag, tool: str
) -> None:
    # The provider serves its event log to admin credentials alone, so the two
    # questions about it are the write tier's. Bound to the read tier they would
    # not error; they would be refused as tools that do not exist, at the moment
    # a resumed walk or an undo needed the answer.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_answers_with(None)
        ) \
        .when(
            _asking(read, write, lambda: ask(SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED, client=write))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(tool)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("ask", [argus_changed_flag_since, somebody_else_changed_flag_since],
                         ids=["whether argus changed it", "whether anybody else did"])
@pytest.mark.parametrize("answer", [True, False, None],
                         ids=["yes", "no", "nobody can say"])
def test_what_the_write_tier_answers_about_a_flag_is_the_answer(
    ask: _AboutAFlag, answer: bool | None
) -> None:
    # The provider's adapter decides each, from who the provider says made each
    # change; this side carries the answer and adds nothing - least of all a
    # `False` where the tier said nobody can say.
    Scenario() \
        .given(
            write := _a_session_that_answers_with(answer)
        ) \
        .when(
            lambda: ask(SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED, client=write)
        ) \
        .then(
            _it_answers(answer)
        )


@pytest.mark.unit
@pytest.mark.parametrize("ask", [argus_changed_flag_since, somebody_else_changed_flag_since],
                         ids=["whether argus changed it", "whether anybody else did"])
def test_a_write_tier_that_cannot_be_reached_answers_nothing(ask: _AboutAFlag) -> None:
    # The case that must not read as "no change was made": a resumed walk would
    # then act a second time on an action that may already have been taken, and
    # an undo would overwrite whatever somebody did since.
    Scenario() \
        .given(
            the_write_tier_is_down := _a_session_that_fails()
        ) \
        .when(
            lambda: ask(SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED, client=the_write_tier_is_down)
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
    # decided to make it. Written from the plan the claim carries, and nothing
    # planned again: the plan was asked for before the claim.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write,
                    lambda: performing_writes_over(write).set_state(A_FLAG_PLAN, True))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(SET_FLAG_TOOL)
        ))


@pytest.mark.integration
def test_putting_a_flag_back_plans_it_and_writes_it_over_the_write_tier() -> None:
    # A put-back has no claim to have carried a plan, and the tier writes a flag
    # only from one - so the plan is read immediately before the write it is
    # for, both over the tier that holds the admin credential the plan's read
    # needs. The plan first: a write asked first would have nothing to compare.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write,
                    lambda: putting_back_over(write).set_state(SOME_FLAG, False))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(PLAN_FLAG_TOOL, SET_FLAG_TOOL)
        ))


@pytest.mark.integration
def test_the_flag_setter_on_its_own_plans_and_writes_over_the_write_tier() -> None:
    # The binding `putting_back_over` is built from, asked directly, so a
    # setter bound to the read client fails here rather than at the moment a
    # refuted flag is being put back.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write, lambda: flag_setter_over(write)(SOME_FLAG, True))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(PLAN_FLAG_TOOL, SET_FLAG_TOOL)
        ))


@pytest.mark.integration
def test_a_flag_the_plan_finds_already_back_is_not_written_again() -> None:
    # A put-back whose answer was lost, asked again. The undo has just found
    # nobody but Argus has changed the flag since Argus set it, so a flag the
    # plan finds already in the state asked for is Argus's own put-back having
    # landed - and writing it a second time is a write nothing asked for.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_refusing_the_flag_as_already_as_asked()
        ) \
        .when(
            _asking(read, write,
                    lambda: flag_setter_over(write)(SOME_FLAG, THE_STATE_IT_IS_ALREADY_BACK_IN))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(PLAN_FLAG_TOOL)
        ))


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
            lambda: flag_setter_over(write)(SOME_FLAG, THE_STATE_IT_IS_ALREADY_BACK_IN)
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
    # bound to the read client, or left out of the bundle, fails here rather
    # than at the moment a walk is about to claim an action.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write, lambda: plan(performing_writes_over(write)))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(tool)
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
            _asking(read, write, lambda: recent_metrics_over(read)(None))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(METRICS_TOOL),
            _the_write_tier_was_asked_for()
        ))


@pytest.mark.integration
def test_the_service_is_re_read_for_the_series_the_rule_watches() -> None:
    # The rule travels to the read tier as the tool's own argument, because the
    # read tier is where it is resolved into a query. A seam that dropped it would
    # come back with the five fixed series and nothing saying it had.
    some_rule = "some-rule"

    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _the_rules_asked_for(read, lambda: recent_metrics_over(read)(some_rule))
        ) \
        .then(
            _the_rules_were([some_rule])
        )


@pytest.mark.integration
def test_the_rule_that_paged_is_read_over_the_read_tier() -> None:
    # Where a rule stands is read and never changed, so it is asked of the tier
    # that holds no credential to change anything.
    some_rule = "some-rule"

    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write, lambda: rules_read_over(read)(some_rule))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(ALERT_RULE_TOOL),
            _the_write_tier_was_asked_for()
        ))


@pytest.mark.integration
def test_how_far_a_rollout_has_got_is_asked_over_the_read_tier() -> None:
    # What a change's arrival is read off, and a read - so the read tier, the
    # same reason the metrics are asked there. Asserted because the two clients
    # are interchangeable at the type level and a seam bound to the wrong one
    # fails at the moment the walk has already changed production, with the
    # incident still happening.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write, lambda: rollout_progress_over(read)(SOME_APPLICATION))
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
                    lambda: deployment_roller_over(write)(A_ROLLBACK_PLAN))
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


@pytest.mark.integration
def test_holding_a_deployment_to_a_card_goes_over_the_write_tier() -> None:
    # Asked of the bundle a walk performs its actions through, so a pin bound to
    # the read client - or left out of the bundle - fails here rather than at
    # the moment a walk has decided to move production's pods.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_answers_with(A_PIN_TO_PUT_BACK)
        ) \
        .when(
            _asking(read, write, lambda: performing_writes_over(write).pin_to_accelerator(
                A_PIN_PLAN
            ))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(PIN_TO_ACCELERATOR_TOOL)
        ))


@pytest.mark.integration
def test_the_way_back_lets_a_deployment_off_its_card_over_the_write_tier() -> None:
    # Asked of the bundle an undo puts changes back through, as the pin above is
    # asked of the one a walk performs through - so a restorer bound to the read
    # client, or left out of the bundle, fails here rather than at the moment a
    # refuted pin or a withdrawn incident is putting production's pods back.
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write, lambda: putting_back_over(write).restore_accelerator_pin(
                A_PIN_TO_PUT_BACK
            ))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(RESTORE_ACCELERATOR_PIN_TOOL)
        ))


@pytest.mark.integration
def test_letting_a_deployment_off_its_card_goes_over_the_write_tier() -> None:
    Scenario() \
        .given(
            read := _a_session_that_remembers_what_it_was_asked(),
            write := _a_session_that_remembers_what_it_was_asked()
        ) \
        .when(
            _asking(read, write,
                    lambda: accelerator_pin_restorer_over(write)(A_PIN_TO_PUT_BACK))
        ) \
        .then(all_of(
            _the_read_tier_was_asked_for(),
            _the_write_tier_was_asked_for(RESTORE_ACCELERATOR_PIN_TOOL)
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


def _the_rules_asked_for(read: Mock, ask: Callable[[], object]) -> Callable[[], list[object]]:
    """Runs one seam and reports which rule each call to the tier named."""
    def step() -> list[object]:
        ask()

        return [asked.kwargs.get("rule") for asked in read.call.call_args_list]

    return step


def _the_rules_were(rules: list[str]) -> Assertion[list[object]]:
    def assertion(asked: list[object]) -> bool:
        if asked != rules:
            raise AssertionError(
                f"Expected the read tier to be asked for the rules {rules}, got {asked}."
            )

        return True

    return assertion


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


def _a_session_refusing_the_flag_as_already_as_asked() -> Mock:
    """The write tier refusing every question as an action already spent - the
    plan of a flag already in the state asked for, in the tier's own words and
    marked the way the tier marks it."""
    client: Mock = create_autospec(McpClient, instance=True)
    client.call.side_effect = ActionExhausted(
        an_exhausted_action(f"flag [{SOME_FLAG}] is already OFF")
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
    actor: str = SOME_ARGUS_USER,
    lookback: timedelta = timedelta(minutes=30)
) -> MitigationSettings:
    """How Mitigation behaves, as this suite sets it.

    The actor and the lookback are what these tests are about - who a
    deployment is attributed to, and how far back the window reaches. Whose a
    flag change was is not here: the provider's adapter says so on the change.
    The wait is never reached here, since nothing in this file takes an action,
    and neither is the cap - nothing here proposes a second attempt on anything.
    """
    a_wait_nothing_here_reaches = 180.0

    return MitigationSettings(
        mitigation_change_lookback_minutes=int(lookback.total_seconds() // 60),
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


# ---- what it logs ----


@pytest.mark.unit
@pytest.mark.parametrize("ask", [argus_changed_flag_since, somebody_else_changed_flag_since],
                         ids=["whether argus changed it", "whether anybody else did"])
def test_a_write_tier_that_cannot_say_whose_change_a_flag_was_is_logged(
    ask: _AboutAFlag, caplog: pytest.LogCaptureFixture
) -> None:
    # Answered as nobody-can-say, which is right, and which loses the reason -
    # so the reason is logged here, where the exception still is.
    Scenario() \
        .given(
            the_write_tier_is_down := _a_session_that_fails()
        ) \
        .when(
            lambda: ask(SOME_FLAG, THE_MOMENT_IT_WAS_CLAIMED, client=the_write_tier_is_down)
        ) \
        .then(
            one_record_was_logged(caplog, "mitigation.tools", logging.WARNING,
                                  "flag history could not be read",
                                  values={"flag": SOME_FLAG}, failure=ConnectionError)
        )
