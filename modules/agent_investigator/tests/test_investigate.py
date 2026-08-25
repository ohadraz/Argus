from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from unittest.mock import create_autospec

import pytest
from agent_investigator import investigate
from agent_investigator.reasoning import propose_hypothesis
from agent_investigator.retrieval import fetch_logs, fetch_metrics
from argus_core.config import get_settings
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso, to_iso_minute
from argus_testkit.assertions import Assertion, all_of
from argus_testkit.scenario import Scenario


@pytest.mark.unit
def test_investigate_returns_a_hypothesis_the_model_is_confident_enough_about() -> None:
    dont_care_logs: list[str] = []
    some_confident_hypothesis = a_hypothesis_at(a_confident_score())
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)
    the_hypothesis_proposer_returns = partial(_returning, hypothesis_proposer)

    Scenario() \
        .given(
            the_metrics_fetcher_returns(a_window_that_starts_calm()),
            the_log_fetcher_returns(dont_care_logs),
            the_hypothesis_proposer_returns(some_confident_hypothesis),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            _the_hypothesis_is(some_confident_hypothesis)
        )


@pytest.mark.unit
def test_investigate_stops_asking_once_a_hypothesis_is_confident_enough() -> None:
    # The first iteration answered, so the rest of the budget is not spent -
    # every further iteration would be another model call paid for nothing.
    dont_care_logs: list[str] = []
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)
    the_hypothesis_proposer_returns = partial(_returning, hypothesis_proposer)
    the_model_was_asked = partial(_the_model_was_asked, hypothesis_proposer)

    Scenario() \
        .given(
            the_metrics_fetcher_returns(a_window_that_starts_calm()),
            the_log_fetcher_returns(dont_care_logs),
            the_hypothesis_proposer_returns(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            the_model_was_asked(times=1)
        )


@pytest.mark.unit
def test_investigate_distrusts_a_confident_answer_from_a_mid_incident_window() -> None:
    # The failure confidence cannot catch. The window never contained the
    # incident's start, so the model read its tail, formed a plausible story
    # from that, and reported certainty about evidence it was never shown - it
    # cannot miss what it never saw. One widening is the price of being
    # believed here.
    dont_care_logs: list[str] = []
    the_first_answer_plus_one_widening = 2
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)
    the_hypothesis_proposer_returns = partial(_returning, hypothesis_proposer)
    the_model_was_asked = partial(_the_model_was_asked, hypothesis_proposer)

    Scenario() \
        .given(
            the_metrics_fetcher_returns(a_window_that_starts_mid_incident()),
            the_log_fetcher_returns(dont_care_logs),
            the_hypothesis_proposer_returns(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            the_model_was_asked(times=the_first_answer_plus_one_widening)
        )


@pytest.mark.unit
def test_investigate_returns_the_confident_answer_from_the_wider_window() -> None:
    # Having widened, the loop believes the better-informed answer - not the
    # first one, which is the one it distrusted enough to widen for.
    dont_care_logs: list[str] = []
    the_answer_from_the_narrow_window = a_hypothesis_at(a_confident_score())
    the_answer_from_the_wider_window = a_hypothesis_at(a_confident_score())
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)
    the_hypothesis_proposer_answers_in_turn = partial(
        _answering_in_turn, hypothesis_proposer
    )

    Scenario() \
        .given(
            the_metrics_fetcher_returns(a_window_that_starts_mid_incident()),
            the_log_fetcher_returns(dont_care_logs),
            the_hypothesis_proposer_answers_in_turn(
                the_answer_from_the_narrow_window,
                the_answer_from_the_wider_window,
            ),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            _the_hypothesis_is(the_answer_from_the_wider_window)
        )


@pytest.mark.unit
def test_investigate_keeps_a_confident_answer_the_budget_later_ran_out_after() -> None:
    # Withholding trust is not the same as throwing the answer away. If every
    # wider look comes back unsure, the one confident finding is still the best
    # thing Argus learned, and reporting "no cause" instead would be a lie
    # about its own evidence.
    dont_care_logs: list[str] = []
    iteration_budget = get_settings().investigation_max_iterations
    the_only_confident_answer = a_hypothesis_at(a_confident_score())
    every_later_answer = [
        a_hypothesis_at(an_unconfident_score()) for _ in range(iteration_budget - 1)
    ]
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)
    the_hypothesis_proposer_answers_in_turn = partial(
        _answering_in_turn, hypothesis_proposer
    )

    Scenario() \
        .given(
            the_metrics_fetcher_returns(a_window_that_starts_mid_incident()),
            the_log_fetcher_returns(dont_care_logs),
            the_hypothesis_proposer_answers_in_turn(
                the_only_confident_answer, *every_later_answer
            ),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            _the_hypothesis_is(the_only_confident_answer)
        )


@pytest.mark.unit
def test_investigate_never_asks_more_times_than_the_iteration_budget() -> None:
    dont_care_logs: list[str] = []
    iteration_budget = get_settings().investigation_max_iterations
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)
    the_hypothesis_proposer_returns = partial(_returning, hypothesis_proposer)
    the_model_was_asked = partial(_the_model_was_asked, hypothesis_proposer)

    Scenario() \
        .given(
            the_metrics_fetcher_returns(a_window_that_starts_mid_incident()),
            the_log_fetcher_returns(dont_care_logs),
            the_hypothesis_proposer_returns(a_hypothesis_at(an_unconfident_score())),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            the_model_was_asked(times=iteration_budget)
        )


@pytest.mark.unit
def test_investigate_reaches_further_back_when_the_window_opens_mid_incident() -> None:
    # No calm stretch is visible, so the onset predates everything retrieved
    # and the next iteration has to widen. Structural: it does not depend on
    # how confident the model happened to sound.
    dont_care_logs: list[str] = []
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)
    the_hypothesis_proposer_returns = partial(_returning, hypothesis_proposer)
    each_log_window_reached_further_back = partial(
        _each_log_window_reached_further_back, log_fetcher
    )

    Scenario() \
        .given(
            the_metrics_fetcher_returns(a_window_that_starts_mid_incident()),
            the_log_fetcher_returns(dont_care_logs),
            the_hypothesis_proposer_returns(a_hypothesis_at(an_unconfident_score())),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            each_log_window_reached_further_back()
        )


@pytest.mark.unit
def test_investigate_anchors_the_log_window_before_the_onset() -> None:
    # A flag toggle lands in a minute that still looks healthy - the error rate
    # reacts only afterwards - so a window starting *at* the onset would
    # structurally exclude the cause.
    dont_care_logs: list[str] = []
    window = a_window_that_starts_calm()
    onset = window[CALM_MINUTES].bucket_id
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)
    the_hypothesis_proposer_returns = partial(_returning, hypothesis_proposer)
    the_log_window_started_before = partial(_the_log_window_started_before, log_fetcher)

    Scenario() \
        .given(
            the_metrics_fetcher_returns(window),
            the_log_fetcher_returns(dont_care_logs),
            the_hypothesis_proposer_returns(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            the_log_window_started_before(onset)
        )


@pytest.mark.unit
def test_investigate_reports_no_cause_when_the_iteration_budget_is_spent() -> None:
    # The honest outcome: the incident began before anything Argus can read.
    # A hypothesis manufactured to fill the field would be indistinguishable
    # from a real diagnosis to whoever picks the incident up.
    dont_care_logs: list[str] = []
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)
    the_hypothesis_proposer_returns = partial(_returning, hypothesis_proposer)

    Scenario() \
        .given(
            the_metrics_fetcher_returns(a_window_that_starts_mid_incident()),
            the_log_fetcher_returns(dont_care_logs),
            the_hypothesis_proposer_returns(a_hypothesis_at(an_unconfident_score())),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            _the_hypothesis_names_no_cause()
        )


@pytest.mark.unit
def test_investigate_does_not_ask_the_model_when_no_minute_is_anomalous() -> None:
    # Nothing departs from baseline, so there is no onset to anchor a log
    # window on and nothing to explain. Asking anyway pays a model to invent
    # one.
    dont_care_logs: list[str] = []
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)
    the_hypothesis_proposer_returns = partial(_returning, hypothesis_proposer)
    the_model_was_asked = partial(_the_model_was_asked, hypothesis_proposer)

    Scenario() \
        .given(
            the_metrics_fetcher_returns(a_steady_window()),
            the_log_fetcher_returns(dont_care_logs),
            the_hypothesis_proposer_returns(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            all_of(
                the_model_was_asked(times=0),
                _the_hypothesis_names_no_cause(),
            )
        )


@pytest.mark.unit
def test_investigate_shows_the_model_everything_it_retrieved() -> None:
    window = a_window_that_starts_calm()
    some_log_lines = ["INFO target-service: feature flag 'checkout-v2' toggled on"]
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)
    the_hypothesis_proposer_returns = partial(_returning, hypothesis_proposer)
    the_model_saw = partial(_the_model_saw, hypothesis_proposer)

    Scenario() \
        .given(
            the_metrics_fetcher_returns(window),
            the_log_fetcher_returns(some_log_lines),
            the_hypothesis_proposer_returns(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            the_model_saw(buckets=window, log_lines=some_log_lines)
        )


@pytest.mark.unit
def test_an_undetermined_hypothesis_belongs_to_the_incident_it_was_asked_about() -> None:
    # The one hypothesis `investigate` authors itself, so the one place it has
    # to stamp the incident on. A determined one comes from the model already
    # carrying it.
    dont_care_logs: list[str] = []
    some_incident_id = new_id()
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)

    Scenario() \
        .given(
            the_metrics_fetcher_returns(a_steady_window()),
            the_log_fetcher_returns(dont_care_logs),
        ) \
        .when(
            lambda: investigate(
                an_alert(),
                incident_id=some_incident_id,
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            _the_hypothesis_belongs_to(some_incident_id)
        )


@pytest.mark.unit
def test_an_undetermined_hypothesis_says_which_alert_it_could_not_explain() -> None:
    dont_care_logs: list[str] = []
    service = "buki"
    alert_name = "HighErrorRate"
    metrics_fetcher = a_mock_metrics_fetcher()
    log_fetcher = a_mock_log_fetcher()
    hypothesis_proposer = a_mock_hypothesis_proposer()
    the_metrics_fetcher_returns = partial(_returning, metrics_fetcher)
    the_log_fetcher_returns = partial(_returning, log_fetcher)

    Scenario() \
        .given(
            the_metrics_fetcher_returns(a_steady_window()),
            the_log_fetcher_returns(dont_care_logs),
        ) \
        .when(
            lambda: investigate(
                Alert(service=service, alert_name=alert_name, started_at=AN_ALERT_TIME),
                incident_id=new_id(),
                fetch_metrics=metrics_fetcher,
                fetch_logs=log_fetcher,
                propose_hypothesis=hypothesis_proposer,
            )
        ) \
        .then(
            _the_summary_mentions(alert_name, service)
        )


CALM_MINUTES = 6
CALM_P50_MS = 80
CALM_P95_MS = 200
DONT_CARE_REQUEST_VOLUME = 1000
WINDOW_START = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
AN_ALERT_TIME = datetime(2026, 8, 20, 11, 8, tzinfo=UTC)


def an_alert() -> Alert:
    return Alert(service="kuki", alert_name="HighErrorRate", started_at=AN_ALERT_TIME)


def a_confident_score() -> float:
    return get_settings().mitigate_threshold


def an_unconfident_score() -> float:
    return get_settings().mitigate_threshold / 2


def a_hypothesis_at(confidence: float) -> Hypothesis:
    return Hypothesis(
        incident_id=new_id(),
        summary="a feature flag was toggled on just before the errors began",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=confidence,
        supporting_evidence=[],
    )


def a_mock_metrics_fetcher() -> Any:
    return create_autospec(fetch_metrics)


def a_mock_log_fetcher() -> Any:
    return create_autospec(fetch_logs)


def a_mock_hypothesis_proposer() -> Any:
    return create_autospec(propose_hypothesis)


def a_steady_window() -> list[MetricBucket]:
    return a_window_of([0.01] * (CALM_MINUTES + 2))


def a_window_that_starts_calm() -> list[MetricBucket]:
    return a_window_of([0.01] * CALM_MINUTES + [0.09, 0.18])


def a_window_that_starts_mid_incident() -> list[MetricBucket]:
    return a_window_of([0.30, 0.28, 0.25, 0.21, 0.20, 0.19])


def a_window_of(error_rates: list[float]) -> list[MetricBucket]:
    return [
        MetricBucket(
            bucket_id=to_iso_minute(WINDOW_START + timedelta(minutes=offset)),
            error_rate=error_rate,
            p50_ms=CALM_P50_MS,
            p95_ms=CALM_P95_MS,
            request_volume=DONT_CARE_REQUEST_VOLUME,
        )
        for offset, error_rate in enumerate(error_rates)
    ]


def _returning(double: Any, value: Any) -> Callable[[], None]:
    """A `given` step that fixes what a stand-in answers with.

    A step rather than a bare assignment because `Scenario.given` runs
    callables - and a configured double handed to it directly would be
    *called*, not arranged.
    """

    def step() -> None:
        double.return_value = value

    return step


def _answering_in_turn(double: Any, *values: Any) -> Callable[[], None]:
    """A `given` step for a stand-in that answers differently each time.

    The loop's iterations are otherwise indistinguishable: a model that says
    the same thing every round cannot show which round the loop believed.
    """

    def step() -> None:
        double.side_effect = list(values)

    return step


def _the_hypothesis_is(expected: Hypothesis) -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        assert hypothesis == expected, (
            f"Expected the model's own hypothesis [{expected.summary}], "
            f"got [{hypothesis.summary}]."
        )
        return True

    return assertion


def _the_hypothesis_names_no_cause() -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        assert hypothesis.cause_type is None and hypothesis.confidence is None, (
            f"Expected no cause and no confidence, got "
            f"cause_type=[{hypothesis.cause_type}], confidence=[{hypothesis.confidence}]."
        )
        return True

    return assertion


def _the_hypothesis_belongs_to(incident_id: str) -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        assert hypothesis.incident_id == incident_id, (
            f"Expected the hypothesis to belong to incident [{incident_id}], "
            f"got [{hypothesis.incident_id}]."
        )
        return True

    return assertion


def _the_summary_mentions(*expected_mentions: str) -> Assertion[Hypothesis]:
    def assertion(hypothesis: Hypothesis) -> bool:
        missing = [
            mention for mention in expected_mentions if mention not in hypothesis.summary
        ]
        assert not missing, (
            f"Expected the summary to mention {missing}, got [{hypothesis.summary}]."
        )
        return True

    return assertion


def _the_model_was_asked(proposer: Any, times: int) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        assert proposer.call_count == times, (
            f"Expected the model to be asked {times} time(s), "
            f"it was asked {proposer.call_count}."
        )
        return True

    return assertion


def _the_model_saw(
    proposer: Any, buckets: list[MetricBucket], log_lines: list[str]
) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        evidence = proposer.call_args.args[0]
        assert evidence.metric_buckets == buckets, (
            f"Expected the model to see {len(buckets)} bucket(s), "
            f"it saw {len(evidence.metric_buckets)}."
        )
        assert evidence.log_lines == log_lines, (
            f"Expected the model to see {log_lines}, it saw {evidence.log_lines}."
        )
        return True

    return assertion


def _the_log_window_started_before(log_fetcher: Any, onset: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        requested_start = parse_iso(log_fetcher.call_args.args[0])
        assert requested_start < parse_iso(onset), (
            f"Expected the log window to start before the onset at [{onset}], "
            f"it started at [{log_fetcher.call_args.args[0]}]."
        )
        return True

    return assertion


def _each_log_window_reached_further_back(log_fetcher: Any) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        requested_starts = [parse_iso(call.args[0]) for call in log_fetcher.call_args_list]

        assert len(requested_starts) > 1, (
            f"Expected more than one iteration to compare, got {len(requested_starts)}."
        )
        assert all(
            later < earlier
            for earlier, later in zip(requested_starts, requested_starts[1:], strict=False)
        ), f"Expected each log window to start earlier than the last, got {requested_starts}."
        return True

    return assertion
