"""Where each replica was running when the incident began, as it was recorded.

A contract rather than one module's value: the read tier returns it, the
Investigator records it and shows it to the model, the timeline says it, and the
strategy that pins a deployment to a card decides from it. All four have to agree
on one thing above everything else - which pods started at the onset - because
that is what makes a card a suspect, and four copies of the rule would be four
answers to it.

The rule has a minute's grace. A measured onset is the first whole minute that
departed, and a pod is placed inside a minute: one moved thirty seconds before
the first departed minute is the change that broke it, and reading it as having
been there before the incident would make the card it moved to look good.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from argus_core.models import PodPlacement, RecordedPlacement
from argus_testkit import Assertion, Scenario

THE_ONSET = datetime(2026, 10, 8, 9, 30, tzinfo=UTC)
DONT_CARE_NODE = "gpu-v100-1"
DONT_CARE_ACCELERATOR = "Tesla-V100-SXM2-16GB"


@pytest.mark.unit
def test_a_pod_that_started_hours_before_the_onset_was_there_before_it() -> None:
    Scenario() \
        .given(
            a_placement := _a_placement_of(
                _a_pod("settled", started=THE_ONSET - timedelta(hours=12))
            )
        ) \
        .when(lambda: (
            a_placement.started_before_the_onset(),
            a_placement.started_at_the_onset()
        )) \
        .then(_before_and_at_are(["settled"], []))


@pytest.mark.unit
def test_a_pod_placed_within_the_minute_before_the_onset_started_at_it() -> None:
    # The grace. The reschedule lands mid-minute, and the minute it lands in may
    # not depart on its own - so the first departed minute can be the one after.
    Scenario() \
        .given(
            a_placement := _a_placement_of(
                _a_pod("moved", started=THE_ONSET - timedelta(seconds=30))
            )
        ) \
        .when(lambda: (
            a_placement.started_before_the_onset(),
            a_placement.started_at_the_onset()
        )) \
        .then(_before_and_at_are([], ["moved"]))


@pytest.mark.unit
def test_a_pod_placed_exactly_a_minute_before_the_onset_started_at_it() -> None:
    Scenario() \
        .given(
            a_placement := _a_placement_of(
                _a_pod("moved", started=THE_ONSET - timedelta(minutes=1))
            )
        ) \
        .when(lambda: (
            a_placement.started_before_the_onset(),
            a_placement.started_at_the_onset()
        )) \
        .then(_before_and_at_are([], ["moved"]))


@pytest.mark.unit
def test_a_pod_placed_more_than_a_minute_before_the_onset_was_there_before_it() -> None:
    Scenario() \
        .given(
            a_placement := _a_placement_of(
                _a_pod("settled", started=THE_ONSET - timedelta(seconds=61))
            )
        ) \
        .when(lambda: (
            a_placement.started_before_the_onset(),
            a_placement.started_at_the_onset()
        )) \
        .then(_before_and_at_are(["settled"], []))


@pytest.mark.unit
def test_a_pod_placed_after_the_onset_started_at_it() -> None:
    # Placed later still is no better a witness to the time before: it has only
    # ever run during the incident.
    Scenario() \
        .given(
            a_placement := _a_placement_of(
                _a_pod("later", started=THE_ONSET + timedelta(minutes=4))
            )
        ) \
        .when(lambda: (
            a_placement.started_before_the_onset(),
            a_placement.started_at_the_onset()
        )) \
        .then(_before_and_at_are([], ["later"]))


@pytest.mark.unit
def test_every_pod_is_one_or_the_other_in_the_order_it_was_recorded() -> None:
    Scenario() \
        .given(
            a_placement := _a_placement_of(
                _a_pod("first", started=THE_ONSET - timedelta(hours=12)),
                _a_pod("second", started=THE_ONSET),
                _a_pod("third", started=THE_ONSET - timedelta(hours=3))
            )
        ) \
        .when(lambda: (
            a_placement.started_before_the_onset(),
            a_placement.started_at_the_onset()
        )) \
        .then(_before_and_at_are(["first", "third"], ["second"]))


@pytest.mark.unit
def test_a_recorded_placement_reads_back_as_it_was_written() -> None:
    # It travels in an event and on the walk's state as JSON, so it has to come
    # back the value it went in as - a node with no card included.
    a_placement = _a_placement_of(
        _a_pod("unlabelled", started=THE_ONSET, accelerator=None)
    )

    Scenario() \
        .given(a_placement) \
        .when(lambda: RecordedPlacement.model_validate(
            a_placement.model_dump(mode="json")
        )) \
        .then(_it_is(a_placement))


def _a_pod(name: str,
           started: datetime,
           accelerator: str | None = DONT_CARE_ACCELERATOR) -> PodPlacement:
    return PodPlacement(
        pod=name,
        node=DONT_CARE_NODE,
        accelerator=accelerator,
        started_at=started
    )


def _a_placement_of(*pods: PodPlacement) -> RecordedPlacement:
    return RecordedPlacement(onset=THE_ONSET, pods=pods)


def _before_and_at_are(
    before: list[str], at: list[str]
) -> Assertion[tuple[list[PodPlacement], list[PodPlacement]]]:
    def assertion(sides: tuple[list[PodPlacement], list[PodPlacement]]) -> bool:
        were_before = [pod.pod for pod in sides[0]]
        were_at = [pod.pod for pod in sides[1]]

        if (were_before, were_at) != (before, at):
            raise AssertionError(
                f"Expected {before} to have started before the onset and {at} at "
                f"it, got {were_before} before and {were_at} at."
            )

        return True

    return assertion


def _it_is(expected: RecordedPlacement) -> Assertion[RecordedPlacement]:
    def assertion(read_back: RecordedPlacement) -> bool:
        if read_back != expected:
            raise AssertionError(
                f"Expected the placement to read back as {expected}, got "
                f"{read_back}."
            )

        return True

    return assertion
