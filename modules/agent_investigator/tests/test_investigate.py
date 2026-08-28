from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any, NamedTuple
from unittest.mock import create_autospec

import pytest
from agent_investigator import investigate
from agent_investigator.reasoning import propose_hypothesis
from agent_investigator.retrieval import fetch_change_events, fetch_logs, fetch_metrics
from argus_core.config import get_settings
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso, to_iso, to_iso_minute
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting


@pytest.mark.unit
def test_investigate_returns_a_hypothesis_the_model_is_confident_enough_about() -> None:
    some_confident_hypothesis = a_hypothesis_at(a_confident_score())
    investigation = an_investigation()

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(some_confident_hypothesis),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
        ) \
        .then(
            _the_hypothesis_is(some_confident_hypothesis)
        )


@pytest.mark.unit
def test_investigate_stops_asking_once_a_hypothesis_is_confident_enough() -> None:
    # The first iteration answered, so the rest of the budget is not spent -
    # every further iteration would be another model call paid for nothing.
    investigation = an_investigation()
    the_model_was_asked = partial(_the_model_was_asked, investigation.hypothesis_proposer)

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
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
    the_first_answer_plus_one_widening = 2
    investigation = an_investigation()
    the_model_was_asked = partial(_the_model_was_asked, investigation.hypothesis_proposer)

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_mid_incident()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
        ) \
        .then(
            the_model_was_asked(times=the_first_answer_plus_one_widening)
        )


@pytest.mark.unit
def test_investigate_returns_the_confident_answer_from_the_wider_window() -> None:
    # Having widened, the loop believes the better-informed answer - not the
    # first one, which is the one it distrusted enough to widen for.
    the_answer_from_the_narrow_window = a_hypothesis_at(a_confident_score())
    the_answer_from_the_wider_window = a_hypothesis_at(a_confident_score())
    investigation = an_investigation()

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_mid_incident()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered_in_turn(
                the_answer_from_the_narrow_window,
                the_answer_from_the_wider_window,
            ),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
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
    iteration_budget = get_settings().investigation_max_iterations
    the_only_confident_answer = a_hypothesis_at(a_confident_score())
    every_later_answer = [
        a_hypothesis_at(an_unconfident_score()) for _ in range(iteration_budget - 1)
    ]
    investigation = an_investigation()

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_mid_incident()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered_in_turn(
                the_only_confident_answer, *every_later_answer
            ),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
        ) \
        .then(
            _the_hypothesis_is(the_only_confident_answer)
        )


@pytest.mark.unit
def test_investigate_never_asks_more_times_than_the_iteration_budget() -> None:
    iteration_budget = get_settings().investigation_max_iterations
    investigation = an_investigation()
    the_model_was_asked = partial(_the_model_was_asked, investigation.hypothesis_proposer)

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_mid_incident()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(a_hypothesis_at(an_unconfident_score())),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
        ) \
        .then(
            the_model_was_asked(times=iteration_budget)
        )


@pytest.mark.unit
def test_investigate_reaches_further_back_when_the_window_opens_mid_incident() -> None:
    # No calm stretch is visible, so the onset predates everything retrieved
    # and the next iteration has to widen. Structural: it does not depend on
    # how confident the model happened to sound.
    investigation = an_investigation()
    each_log_window_reached_further_back = partial(
        _each_log_window_reached_further_back, investigation.log_fetcher
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_mid_incident()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(a_hypothesis_at(an_unconfident_score())),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
        ) \
        .then(
            each_log_window_reached_further_back()
        )


@pytest.mark.unit
def test_investigate_anchors_the_log_window_before_the_onset() -> None:
    # A flag toggle lands in a minute that still looks healthy - the error rate
    # reacts only afterwards - so a window starting *at* the onset would
    # structurally exclude the cause.
    window = a_window_that_starts_calm()
    onset = window[CALM_MINUTES].bucket_id
    investigation = an_investigation()
    the_log_window_started_before = partial(
        _the_log_window_started_before, investigation.log_fetcher
    )

    Scenario() \
        .given(
            investigation.metrics_showed(window),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
        ) \
        .then(
            the_log_window_started_before(onset)
        )


@pytest.mark.unit
def test_investigate_reads_logs_up_to_the_alert() -> None:
    # The onset is inferred and can be wrong; the alert is the one moment the
    # service is known to have been unhealthy. A window closing a fixed few
    # minutes past a mislocated onset never reaches the minutes somebody
    # complained about, and every widening reaches further the other way.
    #
    # The alert is deliberately later than that fixed lookahead would have
    # reached: a threshold trips when a symptom crosses it, which can be long
    # after the incident began, and an alert firing promptly would leave the
    # old behaviour and the new one indistinguishable.
    an_alert_time_well_after_the_onset = WINDOW_START + timedelta(minutes=30)
    investigation = an_investigation()
    the_log_window_ended_at = partial(
        _the_log_window_ended_at, investigation.log_fetcher
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigation.investigate(
                an_alert_at(an_alert_time_well_after_the_onset), incident_id=new_id()
            )
        ) \
        .then(
            the_log_window_ended_at(to_iso(an_alert_time_well_after_the_onset))
        )


@pytest.mark.unit
def test_investigate_asks_for_changes_over_the_configured_lookback_before_the_onset() -> None:
    # The change window is the caller's judgement about how far a cause may
    # precede its symptoms, and it ends at the onset: a change after the
    # incident began did not begin it.
    window = a_window_that_starts_calm()
    onset = window[CALM_MINUTES].bucket_id
    investigation = an_investigation()
    the_changes_asked_for_spanned = partial(
        _the_changes_asked_for_spanned, investigation.change_fetcher
    )

    Scenario() \
        .given(
            investigation.metrics_showed(window),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
        ) \
        .then(
            the_changes_asked_for_spanned(
                the_configured_change_lookback_before(onset), until=onset
            )
        )


@pytest.mark.unit
def test_investigate_shows_the_model_what_changed() -> None:
    # The point of the third channel: a deploy that no log window would have
    # reached still arrives as evidence.
    some_deploy = a_deploy_of("9f4c1e7b2a3d5c8e")
    investigation = an_investigation()
    the_model_saw_changes = partial(_the_model_saw_changes, investigation.hypothesis_proposer)

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.changes_were([some_deploy]),
            investigation.the_model_answered(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
        ) \
        .then(
            the_model_saw_changes([some_deploy])
        )


@pytest.mark.unit
def test_investigate_reads_the_changes_once_across_a_widening_investigation() -> None:
    # Changes are already retrieved over a window wider than any the log
    # schedule reaches, so re-reading them per iteration would return the same
    # handful of rows at the same cost as the first time.
    iteration_budget = get_settings().investigation_max_iterations
    investigation = an_investigation()
    the_changes_were_read = partial(_the_changes_were_read, investigation.change_fetcher)
    the_logs_were_read = partial(_the_logs_were_read, investigation.log_fetcher)

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_mid_incident()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(a_hypothesis_at(an_unconfident_score())),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
        ) \
        .then(all_of(
            the_changes_were_read(times=1),
            the_logs_were_read(times=iteration_budget),
        ))


@pytest.mark.unit
def test_investigate_does_not_continue_when_the_change_source_cannot_be_reached() -> None:
    # "Could not ask what changed" must not become "nothing changed". Carrying
    # on with logs alone would produce a hypothesis that reads as though the
    # change evidence had been seen and found empty.
    investigation = an_investigation()

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.the_change_source_failed(
                RuntimeError("MCP tool call [get_change_events] failed")
            ),
            investigation.the_model_answered(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            attempting(
                lambda: investigation.investigate(an_alert(), incident_id=new_id())
            )
        ) \
        .then(
            an_error_was_raised(RuntimeError)
        )


@pytest.mark.unit
def test_investigate_reports_no_cause_when_the_iteration_budget_is_spent() -> None:
    # The honest outcome: the incident began before anything Argus can read.
    # A hypothesis manufactured to fill the field would be indistinguishable
    # from a real diagnosis to whoever picks the incident up.
    investigation = an_investigation()

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_mid_incident()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(a_hypothesis_at(an_unconfident_score())),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
        ) \
        .then(
            _the_hypothesis_names_no_cause()
        )


@pytest.mark.unit
def test_investigate_does_not_ask_the_model_when_no_minute_is_anomalous() -> None:
    # Nothing departs from baseline, so there is no onset to anchor a log
    # window on and nothing to explain. Asking anyway pays a model to invent
    # one.
    investigation = an_investigation()
    the_model_was_asked = partial(_the_model_was_asked, investigation.hypothesis_proposer)

    Scenario() \
        .given(
            investigation.metrics_showed(a_steady_window()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
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
    investigation = an_investigation()
    the_model_saw = partial(_the_model_saw, investigation.hypothesis_proposer)

    Scenario() \
        .given(
            investigation.metrics_showed(window),
            investigation.logs_showed(some_log_lines),
            investigation.no_changes_were_recorded(),
            investigation.the_model_answered(a_hypothesis_at(a_confident_score())),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=new_id())
        ) \
        .then(
            the_model_saw(buckets=window, log_lines=some_log_lines)
        )


@pytest.mark.unit
def test_an_undetermined_hypothesis_belongs_to_the_incident_it_was_asked_about() -> None:
    # The one hypothesis `investigate` authors itself, so the one place it has
    # to stamp the incident on. A determined one comes from the model already
    # carrying it.
    some_incident_id = new_id()
    investigation = an_investigation()

    Scenario() \
        .given(
            investigation.metrics_showed(a_steady_window()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
        ) \
        .when(
            lambda: investigation.investigate(an_alert(), incident_id=some_incident_id)
        ) \
        .then(
            _the_hypothesis_belongs_to(some_incident_id)
        )


@pytest.mark.unit
def test_an_undetermined_hypothesis_says_which_alert_it_could_not_explain() -> None:
    service = "buki"
    alert_name = "HighErrorRate"
    investigation = an_investigation()

    Scenario() \
        .given(
            investigation.metrics_showed(a_steady_window()),
            investigation.logs_showed(DONT_CARE_LOGS),
            investigation.no_changes_were_recorded(),
        ) \
        .when(
            lambda: investigation.investigate(
                Alert(service=service, alert_name=alert_name, started_at=AN_ALERT_TIME),
                incident_id=new_id(),
            )
        ) \
        .then(
            _the_summary_mentions(alert_name, service)
        )


CALM_MINUTES = 6
CALM_P50_MS = 80
CALM_P95_MS = 200
DONT_CARE_REQUEST_VOLUME = 1000
DONT_CARE_LOGS: list[str] = []
WINDOW_START = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
AN_ALERT_TIME = datetime(2026, 8, 20, 11, 8, tzinfo=UTC)


class Investigation(NamedTuple):
    """The four collaborators `investigate` takes, and the call that uses them.

    A builder rather than four locals per test: the loop has four seams now,
    and repeating their construction sixteen times buried the one or two lines
    each test actually cares about. The `given` steps below name what each
    stand-in *reported*, so the arrangement still reads in the test rather than
    hiding in a fixture.
    """

    metrics_fetcher: Any
    log_fetcher: Any
    change_fetcher: Any
    hypothesis_proposer: Any

    def investigate(self, alert: Alert, incident_id: str) -> Hypothesis:
        return investigate(
            alert,
            incident_id=incident_id,
            fetch_metrics=self.metrics_fetcher,
            fetch_logs=self.log_fetcher,
            fetch_change_events=self.change_fetcher,
            propose_hypothesis=self.hypothesis_proposer,
        )

    def metrics_showed(self, buckets: list[MetricBucket]) -> Callable[[], None]:
        return _returning(self.metrics_fetcher, buckets)

    def logs_showed(self, lines: list[str]) -> Callable[[], None]:
        return _returning(self.log_fetcher, lines)

    def changes_were(self, changes: list[ChangeEvent]) -> Callable[[], None]:
        return _returning(self.change_fetcher, changes)

    def no_changes_were_recorded(self) -> Callable[[], None]:
        return _returning(self.change_fetcher, [])

    def the_change_source_failed(self, error: Exception) -> Callable[[], None]:
        return _raising(self.change_fetcher, error)

    def the_model_answered(self, hypothesis: Hypothesis) -> Callable[[], None]:
        return _returning(self.hypothesis_proposer, hypothesis)

    def the_model_answered_in_turn(self, *hypotheses: Hypothesis) -> Callable[[], None]:
        return _answering_in_turn(self.hypothesis_proposer, *hypotheses)


def an_investigation() -> Investigation:
    return Investigation(
        metrics_fetcher=create_autospec(fetch_metrics),
        log_fetcher=create_autospec(fetch_logs),
        change_fetcher=create_autospec(fetch_change_events),
        hypothesis_proposer=create_autospec(propose_hypothesis),
    )


def an_alert() -> Alert:
    return Alert(service="kuki", alert_name="HighErrorRate", started_at=AN_ALERT_TIME)


def an_alert_at(moment: datetime) -> Alert:
    return Alert(service="kuki", alert_name="HighErrorRate", started_at=moment)


def a_confident_score() -> float:
    return get_settings().mitigate_threshold


def an_unconfident_score() -> float:
    return get_settings().mitigate_threshold / 2


def the_configured_change_lookback_before(moment: str) -> str:
    lookback = timedelta(minutes=get_settings().change_lookback_minutes)

    return to_iso_minute(parse_iso(moment) - lookback)


def a_hypothesis_at(confidence: float) -> Hypothesis:
    return Hypothesis(
        incident_id=new_id(),
        summary="a feature flag was toggled on just before the errors began",
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=confidence,
        supporting_evidence=[],
    )


def a_deploy_of(revision: str) -> ChangeEvent:
    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=to_iso_minute(WINDOW_START),
        reference=revision,
        summary=f"deployed revision {revision}",
        actor="kuki",
        source="https://github.com/kuki/k8s-configs/apps/target-service/production",
    )


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


def _raising(double: Any, error: Exception) -> Callable[[], None]:
    def step() -> None:
        double.side_effect = error

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


def _the_changes_were_read(change_fetcher: Any, times: int) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        assert change_fetcher.call_count == times, (
            f"Expected changes to be read {times} time(s), "
            f"they were read {change_fetcher.call_count}."
        )
        return True

    return assertion


def _the_logs_were_read(log_fetcher: Any, times: int) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        assert log_fetcher.call_count == times, (
            f"Expected logs to be read {times} time(s), "
            f"they were read {log_fetcher.call_count}."
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


def _the_model_saw_changes(proposer: Any, changes: list[ChangeEvent]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        evidence = proposer.call_args.args[0]
        assert evidence.change_events == changes, (
            f"Expected the model to see {[change.reference for change in changes]}, "
            f"it saw {[change.reference for change in evidence.change_events]}."
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


def _the_log_window_ended_at(log_fetcher: Any, expected_end: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        requested_end = log_fetcher.call_args.args[1]

        assert parse_iso(requested_end) == parse_iso(expected_end), (
            f"Expected the log window to end at the alert [{expected_end}], "
            f"it ended at [{requested_end}]."
        )
        return True

    return assertion


def _the_changes_asked_for_spanned(
    change_fetcher: Any, expected_start: str, until: str
) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        _service, window_start, window_end = change_fetcher.call_args.args

        assert parse_iso(window_start) == parse_iso(expected_start), (
            f"Expected the change window to start at [{expected_start}], "
            f"it started at [{window_start}]."
        )
        assert parse_iso(window_end) == parse_iso(until), (
            f"Expected the change window to end at the onset [{until}], "
            f"it ended at [{window_end}]."
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
