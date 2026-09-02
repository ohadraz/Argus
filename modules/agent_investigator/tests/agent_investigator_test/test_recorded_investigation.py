from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from agent_investigator import investigate
from agent_investigator.retrieval import fetch_change_events, fetch_logs, fetch_metrics
from argus_core.models.metrics import MetricBucket
from argus_core.replay import CallType, ReplayEntry
from argus_testkit import Assertion, Kept, Scenario, all_of

from .framework.builders.budget import a_budget
from .framework.builders.incident import (
    a_steady_window,
    a_window_that_starts_calm,
    an_alert,
)
from .framework.builders.model import a_model_that_says, a_turn_answering, an_explanation

"""The one retrieval the loop makes for itself, and its receipt.

Every other read is the model's: it asks, the dispatcher serves, and the
dispatcher writes it down. The metrics are different - the loop reads them
before the model has any say, because the onset every window is anchored on has
to be measured rather than sampled - and that read goes nowhere near the
dispatcher.

So it needs its own receipt, or a replay can reconstruct every turn of the
conversation and not the evidence the first one was written from. The buckets
are in the opening message; without this entry, nothing in the log says what
they were.

Written down when it happens rather than when the investigation ends, which is
what the second test is about: an incident whose metrics show nothing never
reaches a model at all, and that is exactly the run someone later asks "what
did it actually see" about.
"""

SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"

# The channel this read belongs to, named as the model's own metrics calls are
# named, because it is the same channel read by a different caller. Restated
# here rather than imported: it is vocabulary the log's readers depend on, and
# a test that imports the code's spelling agrees with it even when it changes.
METRICS_TOOL = "get_metrics"


@pytest.mark.unit
def test_the_metrics_the_loop_reads_for_itself_are_written_down() -> None:
    # The buckets, not merely the fact of a read: they are what the onset was
    # measured from and what the opening message carried, so an entry without
    # them stands in for nothing.
    some_buckets = a_window_that_starts_calm()

    Scenario() \
        .given(
            recorded := _a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _an_investigation_recording_to(recorded, saw=some_buckets)
        ) \
        .then(
            all_of(
                _a_metrics_read_was_recorded_for(recorded, SOME_INCIDENT_ID),
                _the_recorded_read_carries(recorded, some_buckets)
            )
        )


@pytest.mark.unit
def test_an_investigation_that_stops_at_the_metrics_still_writes_the_read_down() -> None:
    # No minute departs, so the loop returns before a model is ever asked
    # anything. The read still happened and was still paid for, and this is the
    # run most likely to be re-examined - "it said it found nothing; what did it
    # have in front of it".
    a_window_with_no_incident_in_it = a_steady_window()

    Scenario() \
        .given(
            recorded := _a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _an_investigation_recording_to(
                recorded, saw=a_window_with_no_incident_in_it
            )
        ) \
        .then(
            _a_metrics_read_was_recorded_for(recorded, SOME_INCIDENT_ID)
        )


def _a_recorder_that_keeps_what_it_is_given() -> Kept[ReplayEntry]:
    """A recorder that collects entries instead of storing them.

    Handed over as `recorded.take`: a `Scenario` calls anything callable it is
    given, and a recorder that ran while the test was being arranged would
    record nothing and report it faithfully.
    """
    return Kept()


def _an_investigation_recording_to(recorded: Kept[ReplayEntry],
                                   saw: list[MetricBucket]) -> Any:
    """One whole investigation, whose model answers on its first turn.

    The model is scripted to answer immediately because what these tests are
    about happens before it speaks - a longer conversation would add entries
    the dispatcher wrote, which have their own tests.
    """
    return investigate(
        an_alert(),
        incident_id=SOME_INCIDENT_ID,
        fetch_metrics=create_autospec(fetch_metrics, return_value=saw),
        fetch_logs=create_autospec(fetch_logs, return_value=[]),
        fetch_change_events=create_autospec(fetch_change_events, return_value=[]),
        converse=a_model_that_says(a_turn_answering(an_explanation())),
        budget=a_budget(),
        recorder=recorded.take
    )


def _the_metrics_reads_in(recorded: Kept[ReplayEntry]) -> list[ReplayEntry]:
    return [entry for entry in recorded.taken if entry.target == METRICS_TOOL]


def _a_metrics_read_was_recorded_for(recorded: Kept[ReplayEntry],
                                     incident_id: str) -> Assertion[Any]:
    """Exactly one, filed as a tool call, against this incident.

    One rather than at least one: the loop reads the metrics once, and a second
    entry would mean the same read was written down twice - which is what an
    eval counting retrievals would report as an investigation that read more
    than it did.
    """
    def assertion(_result: Any) -> bool:
        reads = _the_metrics_reads_in(recorded)

        if len(reads) != 1:
            raise AssertionError(
                f"Expected exactly one metrics read recorded, got {len(reads)} "
                f"among {[entry.target for entry in recorded.taken]}."
            )

        read = reads[0]

        if read.call_type is not CallType.MCP:
            raise AssertionError(f"Expected a [{CallType.MCP}] entry, got [{read.call_type}].")

        if read.incident_id != incident_id:
            raise AssertionError(
                f"Expected it recorded for [{incident_id}], got [{read.incident_id}]."
            )

        return True

    return assertion


def _the_recorded_read_carries(recorded: Kept[ReplayEntry],
                               buckets: list[MetricBucket]) -> Assertion[Any]:
    """Every minute that came back, by the one thing that identifies a minute.

    The bucket ids rather than the whole payload: what matters is that the
    window was recorded whole, and comparing rendered numbers would make this
    test fail the day a bucket grows a field.
    """
    def assertion(_result: Any) -> bool:
        answered = str(_the_metrics_reads_in(recorded)[0].response)
        missing = [bucket.bucket_id for bucket in buckets if bucket.bucket_id not in answered]

        if missing:
            raise AssertionError(f"Expected the entry to carry {missing}, got {answered}.")

        return True

    return assertion
