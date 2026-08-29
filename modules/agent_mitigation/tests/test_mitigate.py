from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import create_autospec

import pytest
from agent_mitigation import Action, Outcome, Verdict, mitigate, propose_action, take_action
from agent_mitigation.tools import fetch_recent_flag_changes, fetch_recent_metrics, set_flag
from argus_core.models.cause import CauseType
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import to_iso_minute


@pytest.mark.unit
def test_a_flag_that_was_switched_on_is_proposed_to_be_switched_off() -> None:
    some_flag = "monthly-spend-feature"

    action = propose_action(
        a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
        flag_changes=[an_enabling_of(some_flag)],
    )

    assert action is not None
    assert action.flag == some_flag
    assert action.enabled is False


@pytest.mark.unit
def test_a_flag_that_was_switched_off_is_proposed_to_be_switched_on() -> None:
    # A flag causes an incident by *changing*, and off is a direction it can
    # change in: a fallback disabled, traffic moved back to a path that has
    # since rotted. An agent that only ever turns flags off cannot mitigate
    # this incident at all - it would take an action that changes nothing.
    some_flag = "monthly-spend-feature"

    action = propose_action(
        a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
        flag_changes=[a_disabling_of(some_flag)],
    )

    assert action is not None
    assert action.flag == some_flag
    assert action.enabled is True


@pytest.mark.unit
def test_undoing_a_switch_on_records_that_the_flag_had_been_on() -> None:
    # The gate node rejects an action whose undo descriptor is empty before
    # anything mutating is called, so the descriptor has to exist at proposal
    # time - not be filled in by the write that it exists to guard.
    some_flag = "monthly-spend-feature"

    action = propose_action(
        a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
        flag_changes=[an_enabling_of(some_flag)],
    )

    assert action is not None
    assert action.undo_descriptor["flag"] == some_flag
    assert action.undo_descriptor["was_enabled"] is True


@pytest.mark.unit
def test_undoing_a_switch_off_records_that_the_flag_had_been_off() -> None:
    action = propose_action(
        a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
        flag_changes=[a_disabling_of(DONT_CARE_FLAG)],
    )

    assert action is not None
    assert action.undo_descriptor["was_enabled"] is False


@pytest.mark.unit
def test_a_flag_toggled_more_than_once_is_put_back_to_its_state_before_the_latest_change() -> None:
    # The incident is live, so the state to undo is the one the service is in
    # now - not whatever it was at the far edge of the window.
    some_flag = "monthly-spend-feature"

    action = propose_action(
        a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
        flag_changes=[
            a_disabling_of(some_flag, at=EARLIER_IN_THE_WINDOW),
            an_enabling_of(some_flag, at=LATER_IN_THE_WINDOW),
        ],
    )

    assert action is not None
    assert action.enabled is False


@pytest.mark.unit
def test_a_cause_with_no_reversible_action_proposes_nothing() -> None:
    # A bad deployment has no controllable condition until the git write path
    # exists. Proposing an approximate action for it is how an agent takes a
    # confident-looking action on a cause it cannot address.
    action = propose_action(
        a_hypothesis_blaming(CauseType.BAD_DEPLOYMENT),
        flag_changes=[an_enabling_of(DONT_CARE_FLAG)],
    )

    assert action is None


@pytest.mark.unit
def test_a_hypothesis_that_identified_no_cause_proposes_nothing() -> None:
    action = propose_action(
        an_undetermined_hypothesis(),
        flag_changes=[an_enabling_of(DONT_CARE_FLAG)],
    )

    assert action is None


@pytest.mark.unit
def test_more_than_one_changed_flag_proposes_nothing_rather_than_guessing() -> None:
    # "The evidence says a flag, and I cannot tell which" is a real state, and
    # a human resolves it in seconds. Reverting one of two at random is a
    # production change made on a coin flip.
    action = propose_action(
        a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
        flag_changes=[
            an_enabling_of("monthly-spend-feature"),
            a_disabling_of("some-other-feature"),
        ],
    )

    assert action is None


@pytest.mark.unit
def test_the_flag_the_hypothesis_names_is_the_one_proposed() -> None:
    # The case this exists for. Two flags moved recently - a previous
    # incident's, and this one's - and the Investigator already worked out
    # which. Deriving the answer again from the history alone throws that
    # away and escalates an incident that was solved.
    the_blamed_flag = "legacy-checkout-fallback"

    action = propose_action(
        a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE, subject=the_blamed_flag),
        flag_changes=[
            an_enabling_of("monthly-spend-feature"),
            a_disabling_of(the_blamed_flag),
        ],
    )

    assert action is not None
    assert action.flag == the_blamed_flag


@pytest.mark.unit
def test_the_direction_comes_from_the_recorded_change_not_from_the_hypothesis() -> None:
    # The hypothesis says *which*; the provider says *which way*. A model that
    # described the toggle backwards in its prose must not be able to turn a
    # flag the wrong way, so the direction is never read from it.
    the_blamed_flag = "legacy-checkout-fallback"

    action = propose_action(
        a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE, subject=the_blamed_flag),
        flag_changes=[a_disabling_of(the_blamed_flag)],
    )

    assert action is not None
    assert action.enabled is True


@pytest.mark.unit
def test_a_named_flag_the_provider_never_recorded_proposes_nothing() -> None:
    # Two authorities disagreeing about one incident. Falling back to the
    # single-change rule here would act on a flag the Investigator did not
    # blame while its stated conclusion went uncorroborated - and a name that
    # is in no recorded change may be one the model invented.
    a_flag_nobody_recorded_changing = "a-flag-that-never-moved"

    action = propose_action(
        a_hypothesis_blaming(
            CauseType.FEATURE_FLAG_TOGGLE, subject=a_flag_nobody_recorded_changing
        ),
        flag_changes=[an_enabling_of("monthly-spend-feature")],
    )

    assert action is None


@pytest.mark.unit
def test_no_flag_change_proposes_nothing() -> None:
    action = propose_action(
        a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
        flag_changes=[],
    )

    assert action is None


@pytest.mark.unit
def test_taking_an_action_sets_the_flag_to_the_state_it_names() -> None:
    some_flag = "monthly-spend-feature"
    tier = a_write_tier()

    take_action(
        an_action_setting(some_flag, enabled=True),
        set_state=tier.set_state,
        fetch_metrics=metrics_reading(a_recovered_window()),
        now=a_clock_frozen_at(ACTION_TIME),
        sleep=dont_care_sleep,
    )

    assert tier.set_state.call_args.args == (some_flag, True)


@pytest.mark.unit
def test_a_service_that_returns_to_baseline_confirms_the_hypothesis() -> None:
    tier = a_write_tier()

    outcome = take_action(
        an_action_setting(DONT_CARE_FLAG, enabled=False),
        set_state=tier.set_state,
        fetch_metrics=metrics_reading(a_recovered_window()),
        now=a_clock_frozen_at(ACTION_TIME),
        sleep=dont_care_sleep,
    )

    assert outcome.verdict is Verdict.CONFIRMED


@pytest.mark.unit
def test_a_service_still_departing_when_the_time_allowed_runs_out_is_refuted() -> None:
    # An expired verification is refuted rather than an error: the action was
    # taken and did not visibly help within the time allowed, which is exactly
    # what refuted means.
    tier = a_write_tier()

    outcome = take_action(
        an_action_setting(DONT_CARE_FLAG, enabled=False),
        set_state=tier.set_state,
        fetch_metrics=metrics_reading(a_still_failing_window()),
        now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
        sleep=dont_care_sleep,
    )

    assert outcome.verdict is Verdict.REFUTED


@pytest.mark.unit
def test_the_verdict_waits_for_a_minute_that_began_after_the_action() -> None:
    # The newest bucket covers the minute in progress, aggregated over the
    # seconds elapsed so far - mostly pre-action seconds. A verdict read off
    # that minute describes the incident, not the mitigation.
    tier = a_write_tier()
    metrics = create_autospec(fetch_recent_metrics)
    metrics.side_effect = [a_window_ending_at_the_action(), a_recovered_window()]

    outcome = take_action(
        an_action_setting(DONT_CARE_FLAG, enabled=False),
        set_state=tier.set_state,
        fetch_metrics=metrics,
        now=a_clock_frozen_at(ACTION_TIME),
        sleep=dont_care_sleep,
    )

    assert metrics.call_count == 2
    assert outcome.verdict is Verdict.CONFIRMED


@pytest.mark.unit
def test_a_refuted_action_is_undone_in_whichever_direction_it_went() -> None:
    # The flag was not the cause, so leaving it changed means production state
    # was altered for nothing and the next person to look finds an environment
    # Argus quietly changed. Undoing a switch-off means switching it back off.
    some_flag = "monthly-spend-feature"
    tier = a_write_tier_that_changed(some_flag, was_enabled=False)

    take_action(
        an_action_setting(some_flag, enabled=True),
        set_state=tier.set_state,
        fetch_metrics=metrics_reading(a_still_failing_window()),
        now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
        sleep=dont_care_sleep,
    )

    assert tier.set_state.call_args.args == (some_flag, False)


@pytest.mark.unit
def test_a_confirmed_action_is_left_in_place() -> None:
    tier = a_write_tier()

    take_action(
        an_action_setting(DONT_CARE_FLAG, enabled=False),
        set_state=tier.set_state,
        fetch_metrics=metrics_reading(a_recovered_window()),
        now=a_clock_frozen_at(ACTION_TIME),
        sleep=dont_care_sleep,
    )

    assert tier.set_state.call_count == 1


@pytest.mark.unit
def test_an_undo_that_fails_escalates_carrying_both_facts() -> None:
    # An environment left in a state Argus cannot account for is precisely
    # what a human needs paging for - and the page has to say both what was
    # changed and that putting it back did not work.
    some_flag = "monthly-spend-feature"
    some_undo_failure = "flag [monthly-spend-feature] was accepted as on but still reads off"
    tier = a_write_tier()
    tier.set_state.side_effect = [
        an_undo_descriptor_for(some_flag),
        RuntimeError(some_undo_failure),
    ]

    outcome = take_action(
        an_action_setting(some_flag, enabled=False),
        set_state=tier.set_state,
        fetch_metrics=metrics_reading(a_still_failing_window()),
        now=a_clock_that_runs_out_after_one_look(ACTION_TIME),
        sleep=dont_care_sleep,
    )

    assert outcome.verdict is Verdict.ESCALATED
    assert some_flag in outcome.detail
    assert some_undo_failure in outcome.detail


@pytest.mark.unit
def test_an_action_that_could_not_be_taken_escalates_without_a_verdict() -> None:
    # Nothing was changed, so there is nothing to judge and nothing to undo. A
    # verdict formed here would describe an experiment that never ran.
    tier = a_write_tier()
    tier.set_state.side_effect = RuntimeError("the provider could not be reached")

    outcome = take_action(
        an_action_setting(DONT_CARE_FLAG, enabled=False),
        set_state=tier.set_state,
        fetch_metrics=metrics_reading(a_recovered_window()),
        now=a_clock_frozen_at(ACTION_TIME),
        sleep=dont_care_sleep,
    )

    assert outcome.verdict is Verdict.ESCALATED
    assert tier.set_state.call_count == 1


@pytest.mark.unit
def test_mitigating_a_flag_toggle_takes_the_action_proposed_for_it() -> None:
    some_flag = "monthly-spend-feature"
    changes = create_autospec(fetch_recent_flag_changes)
    changes.return_value = [a_disabling_of(some_flag)]
    take = create_autospec(take_action)
    take.return_value = a_confirmed_outcome()

    mitigate(
        a_hypothesis_blaming(CauseType.FEATURE_FLAG_TOGGLE),
        fetch_flag_changes=changes,
        take=take,
    )

    assert take.call_args.args[0].flag == some_flag
    assert take.call_args.args[0].enabled is True


@pytest.mark.unit
def test_mitigating_a_cause_with_no_action_escalates_without_touching_anything() -> None:
    changes = create_autospec(fetch_recent_flag_changes)
    changes.return_value = [an_enabling_of(DONT_CARE_FLAG)]
    take = create_autospec(take_action)

    outcome = mitigate(
        a_hypothesis_blaming(CauseType.BAD_DEPLOYMENT),
        fetch_flag_changes=changes,
        take=take,
    )

    assert outcome.verdict is Verdict.ESCALATED
    assert take.call_count == 0


DONT_CARE_FLAG = "dont-care-flag"
DONT_CARE_INCIDENT_ID = "3f0c6a8e-6f1e-4a9a-8c3d-2b7f9d1e5a44"
DONT_CARE_ACTOR = "dont-care-actor"

WINDOW_START = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
CALM_MINUTES = 6
FAILING_MINUTES = 5
ACTION_TIME = WINDOW_START + timedelta(minutes=CALM_MINUTES + FAILING_MINUTES - 1, seconds=30)

EARLIER_IN_THE_WINDOW = "2026-08-20T11:02:00Z"
LATER_IN_THE_WINDOW = "2026-08-20T11:05:00Z"

CALM_RATE = 0.01
FAILING_RATE = CALM_RATE * 30
CALM_P50_MS = 80
CALM_P95_MS = 200


class _WriteTier:
    def __init__(self) -> None:
        self.set_state: Any = create_autospec(set_flag)


def a_write_tier() -> _WriteTier:
    return a_write_tier_that_changed(DONT_CARE_FLAG, was_enabled=True)


def a_write_tier_that_changed(flag: str, was_enabled: bool) -> _WriteTier:
    tier = _WriteTier()
    tier.set_state.return_value = an_undo_descriptor_for(flag, was_enabled)
    return tier


def an_undo_descriptor_for(flag: str, was_enabled: bool = True) -> dict[str, Any]:
    return {
        "tool": "set_feature_flag",
        "flag": flag,
        "environment": "production",
        "was_enabled": was_enabled,
    }


def a_hypothesis_blaming(cause_type: CauseType, subject: str | None = None) -> Hypothesis:
    return Hypothesis(
        incident_id=DONT_CARE_INCIDENT_ID,
        summary=f"dont care - {cause_type}",
        cause_type=cause_type,
        confidence=0.9,
        supporting_evidence=[],
        subject=subject,
    )


def an_undetermined_hypothesis() -> Hypothesis:
    return Hypothesis(
        incident_id=DONT_CARE_INCIDENT_ID,
        summary="no cause determined",
        cause_type=None,
        confidence=None,
        supporting_evidence=[],
    )


def an_enabling_of(flag: str, at: str = LATER_IN_THE_WINDOW) -> FlagChange:
    return FlagChange(flag=flag, enabled=True, occurred_at=at, actor=DONT_CARE_ACTOR)


def a_disabling_of(flag: str, at: str = LATER_IN_THE_WINDOW) -> FlagChange:
    return FlagChange(flag=flag, enabled=False, occurred_at=at, actor=DONT_CARE_ACTOR)


def an_action_setting(flag: str, enabled: bool) -> Action:
    return Action(
        action_type="revert-feature-flag",
        flag=flag,
        enabled=enabled,
        undo_descriptor={
            "tool": "set_feature_flag",
            "flag": flag,
            "was_enabled": not enabled,
        },
    )


def a_confirmed_outcome() -> Outcome:
    return Outcome(verdict=Verdict.CONFIRMED, detail="dont care")


def a_clock_frozen_at(moment: datetime) -> Callable[[], datetime]:
    """A clock that never reaches any deadline, so a test decides how many
    looks the verification gets by what the metrics say, not by time."""
    return lambda: moment


def a_clock_that_runs_out_after_one_look(moment: datetime) -> Callable[[], datetime]:
    """Reads the action's own instant first, then an hour later - past any
    verification timeout a sane configuration allows."""
    readings = iter([moment])

    def clock() -> datetime:
        return next(readings, moment + timedelta(hours=1))

    return clock


def metrics_reading(window: list[MetricBucket]) -> Callable[[], list[MetricBucket]]:
    return lambda: window


def dont_care_sleep(seconds: float) -> None:
    return None


def a_window_ending_at_the_action() -> list[MetricBucket]:
    """Calm, then failing, and nothing after the action - the minute it fell
    inside is still in progress."""
    return a_window_of([CALM_RATE] * CALM_MINUTES + [FAILING_RATE] * FAILING_MINUTES)


def a_recovered_window() -> list[MetricBucket]:
    return a_window_of(
        [CALM_RATE] * CALM_MINUTES + [FAILING_RATE] * FAILING_MINUTES + [CALM_RATE] * 2
    )


def a_still_failing_window() -> list[MetricBucket]:
    return a_window_of(
        [CALM_RATE] * CALM_MINUTES + [FAILING_RATE] * (FAILING_MINUTES + 2)
    )


def a_window_of(error_rates: list[float]) -> list[MetricBucket]:
    dont_care_volume = 1000

    return [
        MetricBucket(
            bucket_id=to_iso_minute(WINDOW_START + timedelta(minutes=offset)),
            error_rate=error_rate,
            p50_ms=CALM_P50_MS,
            p95_ms=CALM_P95_MS,
            request_volume=dont_care_volume,
        )
        for offset, error_rate in enumerate(error_rates)
    ]
