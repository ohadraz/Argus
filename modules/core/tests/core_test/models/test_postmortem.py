"""What a stored postmortem says of its own impact: whether the metrics stopped,
and whether anything ended it - the two facts every page that shows a floor or
a gap reads, so each is read one way.

Each case is one document and the answer.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_testkit import Scenario, the_answer_was
from core.models import (
    Impact,
    ImpactExtent,
    PostmortemDocument,
    TimelineEntry,
    TimelineMarker,
)

DONT_CARE_MOMENT = datetime(2026, 10, 11, 14, 3, tzinfo=UTC)
DONT_CARE_DURATION = timedelta(minutes=6)


@pytest.mark.unit
@pytest.mark.parametrize(("extent", "marked", "expected"), [
    pytest.param(ImpactExtent.MEASURED, False, True, id="back-to-normal"),
    pytest.param(ImpactExtent.REPORTED, False, True, id="reported"),
    pytest.param(ImpactExtent.AT_LEAST, True, False, id="never-seen-back"),
    pytest.param(ImpactExtent.DISPROVEN, True, False, id="disproven"),
    pytest.param(ImpactExtent.METRICS_MISSING, True, True, id="missing-reported-over"),
    pytest.param(ImpactExtent.METRICS_MISSING, False, False, id="missing-to-the-close"),
    pytest.param(ImpactExtent.METRICS_RESUMED, True, True, id="resumed-showing-it-back"),
    pytest.param(ImpactExtent.METRICS_RESUMED, False, False, id="resumed-not-showing-it-back")
])
def test_the_impact_ended_where_the_extent_says_so_and_the_marker_only_where_it_cannot(
        extent: ImpactExtent, marked: bool, expected: bool) -> None:
    # The extent knows wherever the metrics held; where they stopped, only the
    # timeline's end marker says whether a person's report or the rows they
    # came back with ended it - so a marker beside any other extent changes
    # nothing.
    Scenario() \
        .given(
            a_document := _a_document(impact=_an_impact(extent), marked=marked)
        ) \
        .when(
            lambda: a_document.the_impact_ended()
        ) \
        .then(
            the_answer_was(expected)
        )


@pytest.mark.unit
@pytest.mark.parametrize("marked", [True, False], ids=["marked", "unmarked"])
def test_a_document_that_measured_no_impact_ended_where_its_timeline_marks_an_end(
        marked: bool) -> None:
    Scenario() \
        .given(
            a_document := _a_document(impact=None, marked=marked)
        ) \
        .when(
            lambda: a_document.the_impact_ended()
        ) \
        .then(
            the_answer_was(marked)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("extent", "expected"), [
    pytest.param(ImpactExtent.METRICS_MISSING, True, id="missing"),
    pytest.param(ImpactExtent.METRICS_RESUMED, True, id="resumed"),
    pytest.param(ImpactExtent.MEASURED, False, id="back-to-normal"),
    pytest.param(ImpactExtent.REPORTED, False, id="reported"),
    pytest.param(ImpactExtent.AT_LEAST, False, id="never-seen-back"),
    pytest.param(ImpactExtent.DISPROVEN, False, id="disproven")
])
def test_the_metrics_stopped_wherever_the_stretch_was_one_they_did_not_cover(
        extent: ImpactExtent, expected: bool) -> None:
    # Read off the extent rather than a marker: with no onset measured there is
    # no marker to place where they stopped, and the gap is still there.
    Scenario() \
        .given(
            a_document := _a_document(impact=_an_impact(extent), marked=False)
        ) \
        .when(
            lambda: a_document.the_metrics_stopped()
        ) \
        .then(
            the_answer_was(expected)
        )


@pytest.mark.unit
def test_a_document_that_measured_no_impact_saw_no_metrics_stop() -> None:
    Scenario() \
        .given(
            a_document := _a_document(impact=None, marked=False)
        ) \
        .when(
            lambda: a_document.the_metrics_stopped()
        ) \
        .then(
            the_answer_was(False)
        )


def _an_impact(extent: ImpactExtent) -> Impact:
    return Impact(duration=DONT_CARE_DURATION, extent=extent, peak_error_rate=None)


def _a_document(impact: Impact | None, marked: bool) -> PostmortemDocument:
    """A document with nothing in it but `impact`, and an end marker on its
    timeline where `marked`."""
    return PostmortemDocument(
        root_cause=None,
        executive_summary=None,
        customer_loss_estimate=None,
        estimate_currency=None,
        engineer_minutes=None,
        responders=None,
        tokens_spent=None,
        assumptions=[],
        impact=impact,
        timeline=([TimelineEntry(at=DONT_CARE_MOMENT, who=None, text="dont care",
                                 marker=TimelineMarker.IMPACT_ENDS)] if marked else [])
    )
