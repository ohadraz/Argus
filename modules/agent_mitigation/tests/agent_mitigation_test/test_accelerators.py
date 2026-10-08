"""Which card a deployment is held to, decided from where its pods were placed.

A replica the platform moved onto another card, with nothing deployed, answers
differently from the rest - and the answer that undoes it is to hold the
deployment to the card the fleet ran on before the incident. Which card that is
comes from the placement the Investigator recorded against the onset, and from
nothing else: never from a read made when acting, which would be made after the
pods had been moved by whatever the walk did first.

The decision pins only where the evidence names one card unambiguously. Every
other shape - a pod on no card the platform reports, two cards serving before
the onset, a pod at the onset on the fleet's own card, nothing placed at the
onset at all - is one where a pin would be a guess, and the answer there is no
pin: the walk moves on to its next candidate, and in the end to a person.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from agent_mitigation.accelerators import the_accelerator_to_pin_to
from argus_core.models import PodPlacement, RecordedPlacement
from argus_testkit import Assertion, Scenario

THE_ONSET = datetime(2026, 10, 7, 21, 41, tzinfo=UTC)

THE_FLEETS_CARD = "Tesla-V100-SXM2-16GB"
ANOTHER_CARD = "NVIDIA-A100-SXM4-40GB"
A_THIRD_CARD = "Tesla-T4"

LONG_BEFORE_THE_ONSET = THE_ONSET - timedelta(hours=2)
# Thirty seconds before the first minute that departed. A measured onset is the
# first whole minute that departed, and a pod is placed inside a minute - so a
# replica moved half a minute earlier is the cause, not a bystander.
JUST_BEFORE_THE_ONSET = THE_ONSET - timedelta(seconds=30)


@pytest.mark.unit
def test_a_replica_moved_onto_another_card_has_the_fleet_held_to_its_own() -> None:
    Scenario() \
        .given(
            a_placement := _placed(
                _a_pod_on(THE_FLEETS_CARD, LONG_BEFORE_THE_ONSET),
                _a_pod_on(THE_FLEETS_CARD, LONG_BEFORE_THE_ONSET),
                _a_pod_on(ANOTHER_CARD, JUST_BEFORE_THE_ONSET)
            )
        ) \
        .when(lambda: the_accelerator_to_pin_to(a_placement)) \
        .then(_the_card_to_pin_to_is(THE_FLEETS_CARD))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("started", "expected"),
    [
        (THE_ONSET - timedelta(seconds=59), THE_FLEETS_CARD),
        (THE_ONSET - timedelta(seconds=61), None),
        (THE_ONSET + timedelta(minutes=2), THE_FLEETS_CARD)
    ],
    ids=["inside-the-minutes-grace", "outside-it", "after-the-onset"]
)
def test_a_pod_placed_within_a_minute_of_the_onset_counts_as_placed_at_it(
    started: datetime, expected: str | None
) -> None:
    # A minute and no more. Outside it, the pod on the other card was serving
    # before the incident began, so the fleet ran on two cards before anything
    # departed - and which of the two to hold it to is not something the
    # placement says.
    Scenario() \
        .given(
            a_placement := _placed(
                _a_pod_on(THE_FLEETS_CARD, LONG_BEFORE_THE_ONSET),
                _a_pod_on(ANOTHER_CARD, started)
            )
        ) \
        .when(lambda: the_accelerator_to_pin_to(a_placement)) \
        .then(_the_card_to_pin_to_is(expected))


@pytest.mark.unit
def test_a_pod_placed_at_the_onset_on_the_fleets_own_card_pins_nothing() -> None:
    # Two pods moved at the onset, one onto the other card and one onto the
    # fleet's. The second is evidence that a reschedule onto the fleet's card is
    # an ordinary event here, which is evidence against the card being what
    # changed the answers - so this is a person's question, not a pin.
    Scenario() \
        .given(
            a_placement := _placed(
                _a_pod_on(THE_FLEETS_CARD, LONG_BEFORE_THE_ONSET),
                _a_pod_on(THE_FLEETS_CARD, JUST_BEFORE_THE_ONSET),
                _a_pod_on(ANOTHER_CARD, JUST_BEFORE_THE_ONSET)
            )
        ) \
        .when(lambda: the_accelerator_to_pin_to(a_placement)) \
        .then(_the_card_to_pin_to_is(None))


@pytest.mark.unit
def test_a_fleet_nothing_was_placed_into_at_the_onset_pins_nothing() -> None:
    # No replica moved, so a pin would be an answer to a cause the placement
    # does not show - and holding a fleet to the card it already runs on changes
    # nothing a verification could see.
    Scenario() \
        .given(
            a_placement := _placed(
                _a_pod_on(THE_FLEETS_CARD, LONG_BEFORE_THE_ONSET),
                _a_pod_on(THE_FLEETS_CARD, LONG_BEFORE_THE_ONSET)
            )
        ) \
        .when(lambda: the_accelerator_to_pin_to(a_placement)) \
        .then(_the_card_to_pin_to_is(None))


@pytest.mark.unit
def test_a_fleet_that_ran_on_two_cards_before_the_onset_pins_nothing() -> None:
    # Holding it to either would move pods that were serving well, onto a card
    # the placement gives no reason to prefer.
    Scenario() \
        .given(
            a_placement := _placed(
                _a_pod_on(THE_FLEETS_CARD, LONG_BEFORE_THE_ONSET),
                _a_pod_on(A_THIRD_CARD, LONG_BEFORE_THE_ONSET),
                _a_pod_on(ANOTHER_CARD, JUST_BEFORE_THE_ONSET)
            )
        ) \
        .when(lambda: the_accelerator_to_pin_to(a_placement)) \
        .then(_the_card_to_pin_to_is(None))


@pytest.mark.unit
@pytest.mark.parametrize(
    "the_pod_on_no_card_started",
    [LONG_BEFORE_THE_ONSET, JUST_BEFORE_THE_ONSET],
    ids=["one-serving-before", "the-one-placed-at-the-onset"]
)
def test_a_pod_whose_card_the_platform_did_not_report_pins_nothing(
    the_pod_on_no_card_started: datetime
) -> None:
    # A card nobody reported is not a card nobody has. Before the onset it may be
    # a second card the fleet ran on; at the onset it may be the fleet's own. A
    # pin decided past either is decided past the one fact it rests on.
    Scenario() \
        .given(
            a_placement := _placed(
                _a_pod_on(THE_FLEETS_CARD, LONG_BEFORE_THE_ONSET),
                _a_pod_on(ANOTHER_CARD, JUST_BEFORE_THE_ONSET),
                _a_pod_on(None, the_pod_on_no_card_started)
            )
        ) \
        .when(lambda: the_accelerator_to_pin_to(a_placement)) \
        .then(_the_card_to_pin_to_is(None))


@pytest.mark.unit
def test_a_placement_nobody_could_read_pins_nothing() -> None:
    Scenario() \
        .when(lambda: the_accelerator_to_pin_to(None)) \
        .then(_the_card_to_pin_to_is(None))


def _placed(*pods: PodPlacement) -> RecordedPlacement:
    return RecordedPlacement(onset=THE_ONSET, pods=pods)


def _a_pod_on(card: str | None, started: datetime) -> PodPlacement:
    """One pod, named and housed arbitrarily: what is read is its card and when
    it started."""
    return PodPlacement(
        pod=f"io-shop-{card}-{started.isoformat()}",
        node=f"dont-care-node-{card}",
        accelerator=card,
        started_at=started
    )


def _the_card_to_pin_to_is(expected: str | None) -> Assertion[str | None]:
    def assertion(card: str | None) -> bool:
        if card != expected:
            raise AssertionError(
                f"Expected the deployment to be held to [{expected}], and the "
                f"decision was [{card}]."
            )

        return True

    return assertion
