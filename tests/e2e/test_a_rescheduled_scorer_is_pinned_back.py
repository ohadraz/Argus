"""A replica rescheduled onto a card that rounds, end to end.

Io scores every purchase for fraud on a GPU, and its three replicas have always
run on V100 nodes. The scheduler moved one: its replacement landed on the
cluster's one A100, which runs the scorer's arithmetic in TF32, and on that
replica about half of all purchases are held for review. Nothing was deployed,
nothing fails and nothing slows. The one series that moves is the share held for
review, and the shop's rule watches it.

Three things this case pins that no other one can.

**A cause no change channel holds.** The categoriser upgrade departs in the same
way - a rule's own series, everything else flat - and is told apart by a
revision at the onset. Here there is none, and what moved is in the placement:
a pod started at the onset on a card none of the pods before it ran on.

**The placement read before anything is done.** The card to pin to comes from
where the pods ran at the onset and from nowhere else, so the placement has to be
on the record before the first action - a read made afterwards would be of a
fleet the walk may already have moved.

**Mitigated by a pin the rule agreed with.** Holding the deployment to the card
the earlier pods ran on puts every replica back where the scorer answers as it
always did, and the share recovers. The scorer still allows TF32 wherever it
runs, which is why a fix is proposed afterwards.

Run under `both` only, like the categoriser upgrade: one recording rather than
three of one assertion that does not vary by which tool found the file.
"""

from __future__ import annotations

import httpx2
import pytest
from argus_core.events import ActionTaken, PlacementRecorded, VerdictReached
from argus_core.models import PIN_TO_ACCELERATOR, FailureMode, IncidentStatus, Verdict
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_ACCELERATOR_HETEROGENEITY,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_proposed_a_fix,
    cause_identified_as,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import a_scenario_was_seeded, the_incidents_events

# What the shop's own monitoring pages on here: its rule on the share of purchases
# held for review, which no other scenario trips.
A_FRAUD_HOLDS_ALERT = "FraudHoldsHigh"


@pytest.mark.e2e
def test_a_replica_rescheduled_onto_a_card_that_rounds_is_pinned_back() -> None:
    some_severity = "warning"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_FRAUD_HOLDS_ALERT,
                                            severity=some_severity)

    # The scenario's id is also the recording's name, so one constant serves both.
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(RECORDED_ACCELERATOR_HETEROGENEITY)),
            calling(the_model_answers_from(RECORDED_ACCELERATOR_HETEROGENEITY))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    cause_identified_as(FailureMode.ACCELERATOR_HETEROGENEITY),
                    _the_placement_was_recorded_before_the_first_action(),
                    _the_last_action_held_the_pods_to_the_card_they_ran_on_before(),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    argus_proposed_a_fix()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_placement_was_recorded_before_the_first_action() -> Assertion[httpx2.Response]:
    """Where the pods ran is on the record before anything moved them.

    Asserted as an order in the incident's own account, because the order is the
    claim: a placement recorded after the first action is a placement of a fleet
    Argus may already have changed.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        published = the_incidents_events(incident_id)
        placed = _the_first_index_of(PlacementRecorded, published)
        acted = _the_first_index_of(ActionTaken, published)

        if placed is None:
            raise AssertionError(
                f"Incident [{incident_id}] recorded no placement at all, so the "
                f"card it pinned to came from somewhere other than the record."
            )

        if acted is not None and acted < placed:
            raise AssertionError(
                f"Incident [{incident_id}] took its first action at event "
                f"[{acted}] and recorded the placement only at event [{placed}]."
            )

        return True

    return assertion


def _the_last_action_held_the_pods_to_the_card_they_ran_on_before(
) -> Assertion[httpx2.Response]:
    """The last action is a pin to the card the pre-onset pods ran on, and the
    rule confirmed it.

    The card is compared with the placement the incident recorded rather than
    with a name written here, so what is asserted is a relation Argus holds: it
    pinned to where its own record says the fleet ran before the incident began.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        published = the_incidents_events(incident_id)
        taken = [event for event in published if isinstance(event, ActionTaken)]

        if not taken:
            raise AssertionError(
                f"Incident [{incident_id}] took no action at all, so nothing "
                f"was ever put to the question."
            )

        last = taken[-1]

        if last.action_type != PIN_TO_ACCELERATOR:
            raise AssertionError(
                f"Expected incident [{incident_id}]'s last action to be "
                f"[{PIN_TO_ACCELERATOR}], and it was [{last.action_type}] on "
                f"[{last.subject}]."
            )

        cards_before = _the_cards_the_pods_ran_on_before_the_onset(
            published[:published.index(last)]
        )

        if cards_before != {last.accelerator}:
            raise AssertionError(
                f"Expected incident [{incident_id}] to pin to the card its pods "
                f"ran on before the onset, {sorted(map(str, cards_before))}, and it pinned "
                f"to [{last.accelerator}]."
            )

        verdicts = [
            event.outcome for event in published[published.index(last):]
            if isinstance(event, VerdictReached)
            and event.hypothesis_id == last.hypothesis_id
        ]

        if verdicts[:1] != [Verdict.CONFIRMED]:
            raise AssertionError(
                f"Expected the pin on incident [{incident_id}] to be "
                f"[{Verdict.CONFIRMED}], and the verdicts after it were {verdicts}."
            )

        return True

    return assertion


def _the_cards_the_pods_ran_on_before_the_onset(published: list[object]) -> set[str | None]:
    """The cards the latest placement recorded before an action says the
    pre-onset pods ran on - empty where none was recorded."""
    placements = [event for event in published if isinstance(event, PlacementRecorded)]

    if not placements:
        return set()

    return {pod.accelerator for pod in placements[-1].placement.started_before_the_onset()}


def _the_first_index_of(kind: type, published: list[object]) -> int | None:
    return next(
        (index for index, event in enumerate(published) if isinstance(event, kind)), None
    )
