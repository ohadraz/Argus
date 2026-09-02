from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.events import (
    AlertAcknowledged,
    ChangesRetrieved,
    FlagChangesRetrieved,
    HypothesisFormed,
    IncidentEvent,
    LogsRetrieved,
    MetricsRetrieved,
    OnsetDetected,
    RetrievalChannel,
    RetrievalRequested,
    StatusChanged,
)
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.cause import CauseType
from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.models.flag_change import FlagChange
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.metrics import MetricBucket
from argus_web.views import NarrationLine, build_live_incident, build_narration
from orchestrator.repository.incidents import Incident

"""Turning the recorded account into the lines a reader sees.

No database and no clock of its own. Every question here is about the shaping -
what a line says, what evidence travels with it, and where the elapsed time
stops - because the retrieval is the repository's problem and the judgement of
what happened was made before any of this ran.
"""

_OPENED_AT = datetime(2026, 8, 30, 10, 15, tzinfo=UTC)


@pytest.mark.unit
def test_the_narration_keeps_the_order_the_events_were_published_in() -> None:
    # The account is a sequence, and its order is the order things happened in.
    # A view that re-sorted it would be telling a different story from the one
    # that was recorded.
    dont_care_incident = new_id()

    narration = build_narration([
        AlertAcknowledged(incident_id=dont_care_incident, alert=_an_alert()),
        OnsetDetected(incident_id=dont_care_incident, onset="2026-08-30T10:14Z"),
        StatusChanged(incident_id=dont_care_incident, to_status=IncidentStatus.MITIGATING),
    ])

    assert [line.kind for line in narration] == [
        "alert-acknowledged",
        "onset-detected",
        "status-changed",
    ]


@pytest.mark.unit
def test_every_line_is_timed_by_the_moment_its_event_happened() -> None:
    # Not by when the page was rendered, and not by when the row was written:
    # the moment belongs to the thing that happened.
    an_event = OnsetDetected(incident_id=new_id(), onset="2026-08-30T10:14Z")

    assert build_narration([an_event])[0].at == an_event.at


@pytest.mark.unit
def test_a_retrieval_line_names_the_channel_and_the_window_it_asked_about() -> None:
    # A retrieval whose window is not shown cannot be checked against what came
    # back, which is the one thing a reader wants from it - and a wire-format
    # minute is not a time anybody reads off a page.
    line = _one_line_for(
        RetrievalRequested(
            incident_id=new_id(),
            channel=RetrievalChannel.LOGS,
            window_start="2026-08-30T10:10Z",
            window_end="2026-08-30T10:20Z",
        )
    )

    assert "log" in line.text
    assert "10 minutes" in line.text
    assert "10:20" in line.text


@pytest.mark.unit
def test_a_metrics_retrieval_carries_its_buckets_with_the_elevated_ones_marked() -> None:
    # The shop's console reddens a minute over the same threshold. Two screens
    # in a demo that redden different minutes make a reader translate between
    # them.
    a_quiet_minute = _a_bucket("2026-08-30T10:12Z", error_rate=0.01)
    a_bad_minute = _a_bucket("2026-08-30T10:14Z", error_rate=0.31)

    line = _one_line_for(
        MetricsRetrieved(
            incident_id=new_id(),
            window_start="2026-08-30T10:12Z",
            window_end="2026-08-30T10:14Z",
            buckets=[a_quiet_minute, a_bad_minute],
        )
    )

    assert [(bucket.bucket_id, bucket.elevated) for bucket in line.buckets] == [
        ("2026-08-30T10:12Z", False),
        ("2026-08-30T10:14Z", True),
    ]


@pytest.mark.unit
def test_a_log_retrieval_distinguishes_warnings_and_errors_from_the_rest() -> None:
    # At a glance, in a page a reader is scanning while an incident runs. A wall
    # of undifferentiated lines is a wall.
    line = _one_line_for(
        LogsRetrieved(
            incident_id=new_id(),
            window_start="2026-08-30T10:12Z",
            window_end="2026-08-30T10:14Z",
            lines=[
                "2026-08-30T10:12Z INFO io-shop: account page rendered",
                "2026-08-30T10:13Z WARN io-shop: account page error rate at 6%",
                "2026-08-30T10:14Z ERROR io-shop: account page request failed - timeout",
            ],
        )
    )

    assert [shown.level for shown in line.log_lines] == ["info", "warn", "error"]


@pytest.mark.unit
def test_a_log_line_that_announces_no_level_is_still_shown() -> None:
    # The log store is the service's, not Argus's, and a line it never labelled
    # is still a line Argus read.
    a_line_with_no_level = "2026-08-30T10:12Z io-shop: something happened"

    line = _one_line_for(
        LogsRetrieved(
            incident_id=new_id(),
            window_start="2026-08-30T10:12Z",
            window_end="2026-08-30T10:14Z",
            lines=[a_line_with_no_level],
        )
    )

    assert [shown.text for shown in line.log_lines] == [a_line_with_no_level]


@pytest.mark.unit
def test_a_changes_retrieval_carries_what_changed_on_the_service() -> None:
    # What changed is what a cause actually is, so it travels on the line that
    # read it rather than being summarised away.
    a_deploy = ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at="2026-08-30T10:13Z",
        reference="abc1234",
        summary="checkout: swap the account page renderer",
    )

    line = _one_line_for(
        ChangesRetrieved(
            incident_id=new_id(),
            window_start="2026-08-30T09:15Z",
            window_end="2026-08-30T10:15Z",
            changes=[a_deploy],
        )
    )

    assert line.changes == [a_deploy]


@pytest.mark.unit
def test_a_candidate_is_the_hypothesis_that_was_recorded() -> None:
    # Not restated and not re-derived: the narration and the walk have to be the
    # same hypothesis seen twice, rather than two accounts to reconcile.
    line = _one_line_for(
        _a_hypothesis(summary="legacy-checkout-fallback was enabled", rank=1)
    )

    assert [shown.summary for shown in line.candidates] == [
        "legacy-checkout-fallback was enabled"
    ]


@pytest.mark.unit
def test_the_candidates_formed_together_are_one_line() -> None:
    # An investigation forms its explanations in one breath, and a story that
    # spent a line on each would bury what it did next under a list. They are
    # one finding with a ranking inside it.
    dont_care_incident = new_id()

    narration = build_narration([
        _a_hypothesis(summary="the flag", rank=1, incident_id=dont_care_incident),
        _a_hypothesis(summary="the deploy", rank=2, incident_id=dont_care_incident),
        OnsetDetected(incident_id=dont_care_incident, onset="2026-08-30T10:14Z"),
    ])

    assert [line.kind for line in narration] == ["hypothesis-formed", "onset-detected"]
    assert [shown.rank for shown in narration[0].candidates] == [1, 2]


@pytest.mark.unit
def test_a_candidate_shows_what_it_was_formed_from() -> None:
    # The findings are what make a claim checkable. Without them the page asks
    # an audience to take Argus's word for the whole investigation.
    what_it_rests_on = ["monthly-spend-feature began evaluating ON at 10:05"]

    line = _one_line_for(
        _a_hypothesis(summary="dont care", rank=1, evidence=what_it_rests_on)
    )

    assert [[cited.text for cited in shown.evidence] for shown in line.candidates] == [
        what_it_rests_on
    ]



@pytest.mark.unit
def test_a_flag_history_is_carried_as_the_changes_it_reported() -> None:
    # Which flag moved, which way and when: the three facts the action was
    # chosen from, and the ones an audience checks it against.
    a_toggle = FlagChange(
        flag="monthly-spend-feature",
        enabled=True,
        occurred_at="2026-08-30T10:05:00Z",
        actor="a-human",
    )

    line = _one_line_for(
        FlagChangesRetrieved(incident_id=new_id(), changes=[a_toggle])
    )

    assert line.flag_changes == [a_toggle]


@pytest.mark.unit
def test_a_running_incident_counts_the_time_since_it_opened() -> None:
    # The header's whole job while an incident runs: how long has this been
    # going on.
    a_minute_later = _OPENED_AT + timedelta(minutes=1)

    live = build_live_incident(
        _an_incident(IncidentStatus.INVESTIGATING), [], now=lambda: a_minute_later
    )

    assert live.elapsed_seconds == 60


@pytest.mark.unit
def test_a_finished_incident_stops_counting_at_the_moment_it_finished() -> None:
    # An elapsed time that kept climbing after the incident ended would report
    # the age of the record rather than the length of the incident.
    an_incident = _an_incident(IncidentStatus.RESOLVED)
    resolved_at = _OPENED_AT + timedelta(minutes=2)
    much_later = _OPENED_AT + timedelta(hours=3)

    live = build_live_incident(
        an_incident,
        [
            StatusChanged(
                incident_id=an_incident.id, at=resolved_at, to_status=IncidentStatus.RESOLVED
            )
        ],
        now=lambda: much_later,
    )

    assert live.elapsed_seconds == 120


@pytest.mark.unit
def test_a_live_incident_is_shown_with_the_alert_it_opened_on() -> None:
    # The header names what fired and where. The row stores the alert as the
    # JSON it was normalized into; a reader gets the alert back.
    some_alert = Alert(service="io-shop", alert_name="HighErrorRate", severity="critical")

    live = build_live_incident(
        _an_incident(IncidentStatus.INVESTIGATING, alert=some_alert),
        [],
        now=lambda: _OPENED_AT,
    )

    assert live.alert == some_alert


@pytest.mark.unit
def test_a_flag_state_in_a_claim_is_said_the_way_the_rest_of_the_page_says_it() -> None:
    # The model writes a flag's position as ordinary lower-case words; every
    # other place it appears - the flag table, the action line - says ON and
    # OFF. Three spellings of one fact on one screen is a reader wondering
    # whether they are three facts.
    line = _one_line_for(_a_hypothesis(
        summary=(
            "The ramp turned legacy-checkout-fallback off at 22:34, "
            "and monthly-spend-feature flipped from off to on."
        ),
        rank=1,
    ))

    assert line.candidates[0].summary == (
        "The ramp turned legacy-checkout-fallback OFF at 22:34, "
        "and monthly-spend-feature flipped from OFF to ON."
    )


@pytest.mark.unit
def test_a_word_that_is_merely_the_word_off_is_left_alone() -> None:
    # The other direction, and the more embarrassing mistake: a page that
    # uppercased every "off" in a sentence would be shouting at English.
    line = _one_line_for(_a_hypothesis(
        summary="The account page went off the rails when the ramp completed.",
        rank=1,
    ))

    assert line.candidates[0].summary == (
        "The account page went off the rails when the ramp completed."
    )


@pytest.mark.unit
def test_a_transition_broken_across_lines_is_still_the_transition_it_was() -> None:
    # What the model sometimes actually sends: the arrow between two states
    # arrives as a line break, a fragment of nothing, and another line break.
    # Shown as it stands, a reader gets a claim about a flag that turns into
    # gibberish exactly where it says which way the flag moved.
    line = _one_line_for(_a_hypothesis(
        summary="Two flags flipped (legacy-checkout-fallback on\ninosn\n\noff).", rank=1
    ))

    assert line.candidates[0].summary == (
        "Two flags flipped (legacy-checkout-fallback ON \u2192 OFF)."
    )


@pytest.mark.unit
def test_a_claim_broken_across_lines_is_read_as_the_sentence_it_is() -> None:
    # The page lays out its own text. A line break arriving inside a claim is
    # typesetting the model did not mean and this page did not ask for.
    line = _one_line_for(
        _a_hypothesis(summary="The error rate rose\n   to 33% within a minute.", rank=1)
    )

    assert line.candidates[0].summary == "The error rate rose to 33% within a minute."


def _one_line_for(event: IncidentEvent) -> NarrationLine:
    """The single narration line one event becomes.

    Every event shapes into exactly one line, and a test that indexed `[0]`
    inline would be quietly asserting that too, in the one place a reader is
    not looking.
    """
    narration = build_narration([event])

    assert len(narration) == 1, f"Expected one line, got {len(narration)}."

    return narration[0]


def _a_hypothesis(summary: str,
                  rank: int,
                  evidence: list[str] | None = None,
                  incident_id: str | None = None) -> HypothesisFormed:
    return HypothesisFormed(
        incident_id=incident_id or new_id(),
        hypothesis_id=new_id(),
        summary=summary,
        cause_type=CauseType.FEATURE_FLAG_TOGGLE,
        confidence=0.9,
        subject="dont-care-flag",
        rank=rank,
        evidence=evidence or [],
    )


def _an_alert() -> Alert:
    return Alert(service="io-shop", alert_name="HighErrorRate")


def _a_bucket(bucket_id: str, error_rate: float) -> MetricBucket:
    return MetricBucket(
        bucket_id=bucket_id,
        error_rate=error_rate,
        p50_ms=120,
        p95_ms=240,
        request_volume=200,
    )


def _an_incident(status: IncidentStatus, alert: Alert | None = None) -> Incident:
    return Incident(
        id=new_id(),
        alert_payload=(alert or _an_alert()).model_dump(mode="json"),
        status=status,
        slack_channel_id=None,
        pr_url=None,
        created_at=_OPENED_AT,
    )
