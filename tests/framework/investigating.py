"""What a cross-module suite hands `investigate()` when the evidence is not
the subject.

Three suites drive a real investigation to watch something *around* it - what it
recorded, what it was charged, how the model behaved - and each needs evidence
good enough that the walk does not stop before it starts. An incident with no
departure escalates at retrieval, before a model is ever called, and a test
watching the replay log would then pass on an empty log for the wrong reason.

So these are deliberately dull: one clear onset, one log line, no changes. What
they are *not* is a fixture for tests about retrieval itself, which state their
own evidence and mean something by it.

`the_configured_thresholds` is here rather than stated as numbers because every
one of these suites asks about the same deployment the worker walks. A suite
that named its own thresholds would be testing an algorithm nobody runs.
"""

from __future__ import annotations

from argus_core import get_settings
from argus_core.anomaly import AnomalyThresholds
from argus_core.models import ChangeEvent, MetricBucket

# The minute the departure lands in, and so the onset every one of these suites
# measures from. Named because two of them assert against it.
SOME_ONSET = "2026-08-29T22:15:00Z"

A_CALM_MINUTE = "2026-08-29T22:10:00Z"
A_STEADY_HEAP_BYTES = 440 * 1024**2
A_STEADY_START_TIME = 1_756_000_000.0
A_MINUTES_SAMPLE = 200


def metrics_that_show_an_onset(dont_care_window_start: str | None) -> list[MetricBucket]:
    """Enough of a departure that the investigation does not stop at retrieval.

    An incident with no metrics escalates before a model is ever called, which
    would make a test about what the walk recorded pass on an empty log.
    """
    return [
        MetricBucket(
            bucket_id=A_CALM_MINUTE,
            error_rate=0.01,
            p50_ms=40,
            p95_ms=120,
            p99_ms=200,
            request_volume=A_MINUTES_SAMPLE,
            memory_used_bytes=A_STEADY_HEAP_BYTES,
            process_start_time_seconds=A_STEADY_START_TIME
        ),
        MetricBucket(
            bucket_id=SOME_ONSET,
            error_rate=0.31,
            p50_ms=60,
            p95_ms=900,
            p99_ms=1600,
            request_volume=A_MINUTES_SAMPLE,
            memory_used_bytes=A_STEADY_HEAP_BYTES,
            process_start_time_seconds=A_STEADY_START_TIME
        )
    ]


def logs_that_say_little(dont_care_start: str, dont_care_end: str) -> list[str]:
    """One failure and no explanation - enough to read, not enough to conclude
    from, which is what keeps these suites off the model's judgement."""
    return ["2026-08-29T22:15:00Z ERROR io-shop: request failed"]


def no_changes(dont_care_service: str,
               dont_care_start: str,
               dont_care_end: str) -> list[ChangeEvent]:
    """Nothing deployed and nothing toggled, so the third channel adds no
    evidence and cannot be what a walk concluded from."""
    return []


def the_configured_thresholds() -> AnomalyThresholds:
    """Where the algorithm draws its lines, read from this deployment.

    Narrowed from the same configuration the worker would, rather than stated:
    what is under test here is the run, not the arithmetic.
    """
    settings = get_settings()

    return AnomalyThresholds(
        deviations_from_baseline=settings.anomaly_deviations_from_baseline,
        persistence_minutes=settings.anomaly_persistence_minutes,
        recovery_fraction_of_the_rise=settings.recovery_fraction_of_the_rise
    )
