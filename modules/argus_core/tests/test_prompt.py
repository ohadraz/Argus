from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.anthropic_llm import build_prompt
from argus_core.config import get_settings
from argus_core.ids import new_id
from argus_core.models.alert import Alert
from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.models.evidence import Evidence
from argus_core.models.metrics import MetricBucket
from argus_core.timestamps import parse_iso, to_iso_minute

# The heading the change channel's section is written under. A literal here
# because it *is* the thing under test: the prompt has to name the channel it
# is reporting on, and a test that derived the heading from the code could not
# notice it disappearing.
CHANGES_HEADING = "## Changes to this service"


@pytest.mark.unit
def test_the_prompt_carries_every_change_that_was_retrieved() -> None:
    # The third channel is only a channel if what it retrieved reaches the
    # model. A change the prompt drops is a cause Argus paid to fetch and
    # then hid.
    some_deploy = a_deploy_of("9f4c1e7b2a")
    another_deploy = a_deploy_of("3c8e5d1f0b")

    prompt = build_prompt(an_incident_where(some_deploy, another_deploy))

    for change in (some_deploy, another_deploy):
        assert change.reference in prompt
        assert change.summary in prompt


@pytest.mark.unit
def test_the_prompt_says_nothing_changed_rather_than_staying_silent() -> None:
    # "Nothing changed in this window" and "nobody looked" call for different
    # conclusions, and an omitted section reads as the second. The model is
    # told to answer undetermined when the evidence is thin, so it has to be
    # able to tell a checked-and-empty channel from an absent one.
    prompt = build_prompt(an_incident_where())

    assert CHANGES_HEADING in prompt
    assert "no changes" in prompt.lower()


@pytest.mark.unit
def test_the_prompt_tells_the_model_to_judge_a_change_against_the_symptoms() -> None:
    # The failure this framing exists to prevent: a change is the only thing
    # in the evidence shaped like an actor, so a model handed one with no
    # judgement rule will reach for it.
    #
    # The rule is stated as a test to apply - does this account for the
    # symptoms? - and deliberately *not* as a prior about deploys in general.
    # It once read "most changes break nothing", and the model duly discounted
    # the whole channel: the same deploy scored 0.65 under that wording and
    # 0.72 without it, while this guard was unaffected either way.
    dont_care_deploy = a_deploy_of("9f4c1e7b2a")

    prompt = build_prompt(an_incident_where(dont_care_deploy))

    assert "judge" in prompt.lower()
    assert "complete list" in prompt.lower()


@pytest.mark.unit
def test_the_prompt_states_the_window_the_changes_were_retrieved_over() -> None:
    # The completeness claim is worthless without it. "This is every change"
    # over an unnamed interval gives the model nothing to reason with, and
    # leaves it holding back confidence for a change it cannot rule out.
    dont_care_deploy = a_deploy_of("9f4c1e7b2a")
    evidence = an_incident_where(dont_care_deploy)

    prompt = build_prompt(evidence)

    assert evidence.change_window_start is not None
    assert evidence.change_window_end is not None
    assert evidence.change_window_start in prompt
    assert evidence.change_window_end in prompt


@pytest.mark.unit
def test_the_prompt_does_not_invent_a_change_window_it_was_not_given() -> None:
    # Evidence gathered before the change channel had a window - a recording,
    # an eval fixture - still has to render. A guessed bound would be worse
    # than none: the model would reason about an interval nothing was
    # actually retrieved over.
    dont_care_deploy = a_deploy_of("9f4c1e7b2a")
    evidence = an_incident_where(dont_care_deploy).model_copy(
        update={"change_window_start": None, "change_window_end": None}
    )

    prompt = build_prompt(evidence)

    assert "window not recorded" in prompt.lower()


@pytest.mark.unit
def test_the_prompt_states_the_window_the_log_lines_came_from() -> None:
    # A model told where the logs end can say *the cause is outside this
    # window*; one handed bare lines can only guess whether silence means
    # nothing happened or nothing was fetched.
    evidence = an_incident_where()

    prompt = build_prompt(evidence)

    assert evidence.log_window_start is not None
    assert evidence.log_window_end is not None
    assert evidence.log_window_start in prompt
    assert evidence.log_window_end in prompt


@pytest.mark.unit
def test_the_prompt_carries_the_metrics_and_the_logs_it_was_given() -> None:
    # The two older channels, guarded here because the change section is
    # appended after them - a section that swallowed its predecessors would
    # otherwise show up only as a quiet drop in eval scores.
    evidence = an_incident_where()

    prompt = build_prompt(evidence)

    assert evidence.metric_buckets[0].bucket_id in prompt
    assert str(evidence.metric_buckets[0].error_rate) in prompt
    for line in evidence.log_lines:
        assert line in prompt


WINDOW_START = datetime(2026, 8, 20, 11, 0, tzinfo=UTC)
SOME_ERROR_RATE = 0.18
DONT_CARE_P50_MS = 45
DONT_CARE_P95_MS = 220
DONT_CARE_REQUEST_VOLUME = 1200


def an_incident_where(*changes: ChangeEvent) -> Evidence:
    buckets = a_window_of_buckets()
    onset = parse_iso(buckets[0].bucket_id)
    lookback = timedelta(minutes=get_settings().change_lookback_minutes)

    return Evidence(
        incident_id=new_id(),
        alert=Alert(service="kuki", alert_name="HighErrorRate"),
        metric_buckets=buckets,
        log_lines=["INFO kuki: request succeeded", "ERROR kuki: request failed"],
        change_events=list(changes),
        log_window_start=buckets[0].bucket_id,
        log_window_end=buckets[-1].bucket_id,
        change_window_start=to_iso_minute(onset - lookback),
        change_window_end=buckets[0].bucket_id,
    )


def a_window_of_buckets() -> list[MetricBucket]:
    return [
        MetricBucket(
            bucket_id=to_iso_minute(WINDOW_START + timedelta(minutes=offset)),
            error_rate=SOME_ERROR_RATE,
            p50_ms=DONT_CARE_P50_MS,
            p95_ms=DONT_CARE_P95_MS,
            request_volume=DONT_CARE_REQUEST_VOLUME,
        )
        for offset in range(3)
    ]


def a_deploy_of(reference: str) -> ChangeEvent:
    some_actor = "kuki"
    some_source = "https://github.com/kuki/k8s-configs"

    return ChangeEvent(
        kind=ChangeKind.DEPLOY,
        occurred_at=to_iso_minute(WINDOW_START),
        reference=reference,
        summary=f"deployed {reference}",
        actor=some_actor,
        source=some_source,
    )
