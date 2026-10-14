"""The postmortem's sections, written by a whole walk rather than handed in.

Every section has a unit suite that builds its input by hand. What none of them
can show is that the record a real walk leaves behind - the narration, the
candidates, the actions, the model's answer to a real prompt - is enough to
fill them: an action the walk recorded under a verdict nobody reads as
confirmed would leave the timeline unmitigated and the action items without
their first entry, and every unit suite would stay green.

Relations only, never the walk's own figures. How many steps the chain has,
how many items the model proposed and how long anything took are the model's
and the clock's; what is asserted is how the parts of one document agree.
"""

from __future__ import annotations

import httpx2
import psycopg
import pytest
from agent_postmortem import ITEMS_OWNED_AND_DATED, REVIEWED_AND_SHARED
from argus_core.models import ActionItemStatus, Postmortem, TimelineMarker
from argus_incidents.repository import postmortems
from argus_testkit import Assertion, Scenario, all_of, calling
from argus_testkit.assertions import eventually

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_FLAG_TOGGLE,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_is_triggered_with_alert,
    argus_wrote_a_postmortem,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import a_scenario_was_seeded

LEFT_FOR_PEOPLE = {ITEMS_OWNED_AND_DATED, REVIEWED_AND_SHARED}


@pytest.mark.e2e
def test_a_walk_argus_mitigated_writes_every_section_of_the_template() -> None:
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name="HighErrorRate",
                                            severity="critical")

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("feature-flag-toggle",
                                          as_recorded_in=RECORDED_FLAG_TOGGLE)),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            # `eventually` on the row alone: it is written once and never
            # updated, so what it says is asserted once it exists.
            all_of(
                eventually(argus_wrote_a_postmortem(),
                           timeout=WALK_TIMEOUT_SECONDS),
                _the_timeline_was_detected_before_it_was_mitigated(),
                _the_first_action_item_is_the_mitigation_argus_completed(),
                _the_action_items_are_numbered_without_a_gap(),
                _every_step_of_the_cause_carries_what_it_read(),
                _the_review_leaves_to_people_what_only_people_can_do()
            )
        )


def _the_timeline_was_detected_before_it_was_mitigated() -> Assertion[httpx2.Response]:
    """Both markers present, in that order: Argus confirmed a recovery, so the
    action that brought it is in the timeline, and after the alert."""
    def assertion(response: httpx2.Response) -> bool:
        postmortem = _the_postmortem_for(response)
        markers = [entry.marker for entry in postmortem.timeline if entry.marker is not None]
        wanted = [TimelineMarker.DETECTED, TimelineMarker.MITIGATED]

        if [marker for marker in markers if marker in wanted] != wanted:
            raise AssertionError(
                f"Postmortem for [{postmortem.incident_id}] marks its timeline "
                f"{markers}, not detected and then mitigated.")

        return True

    return assertion


def _the_first_action_item_is_the_mitigation_argus_completed() -> Assertion[httpx2.Response]:
    """The record's own items come before the model's, and what brought
    recovery comes first among them - done, and somebody's."""
    def assertion(response: httpx2.Response) -> bool:
        postmortem = _the_postmortem_for(response)
        items = postmortem.action_items

        if not items or items[0].status is not ActionItemStatus.DONE or items[0].owner is None:
            raise AssertionError(
                f"Postmortem for [{postmortem.incident_id}] opens its action items "
                f"with {items[:1]}, not the mitigation Argus completed.")

        return True

    return assertion


def _the_action_items_are_numbered_without_a_gap() -> Assertion[httpx2.Response]:
    """The record's numbering and the model's proposals meet with nothing lost
    or repeated between them."""
    def assertion(response: httpx2.Response) -> bool:
        postmortem = _the_postmortem_for(response)
        numbers = [item.number for item in postmortem.action_items]
        expected = [f"AI-{position}" for position in range(1, len(numbers) + 1)]

        if numbers != expected:
            raise AssertionError(
                f"Postmortem for [{postmortem.incident_id}] numbers its action "
                f"items {numbers}, expected {expected}.")

        return True

    return assertion


def _every_step_of_the_cause_carries_what_it_read() -> Assertion[httpx2.Response]:
    """At least one step, each citing evidence the model was shown - stored
    with the text its label named, so the row reads without the prompt."""
    def assertion(response: httpx2.Response) -> bool:
        postmortem = _the_postmortem_for(response)
        uncited = [step.text for step in postmortem.causal_chain
                   if not step.cites or not all(cited.text for cited in step.cites)]

        if not postmortem.causal_chain or uncited:
            raise AssertionError(
                f"Postmortem for [{postmortem.incident_id}] has a causal chain of "
                f"{len(postmortem.causal_chain)} step(s), these citing nothing "
                f"readable: {uncited}.")

        return True

    return assertion


def _the_review_leaves_to_people_what_only_people_can_do() -> Assertion[httpx2.Response]:
    """Neither met nor failed: a box Argus can never tick is left for a person."""
    def assertion(response: httpx2.Response) -> bool:
        postmortem = _the_postmortem_for(response)
        left = {entry.criterion for entry in postmortem.review if entry.met is None}

        if left != LEFT_FOR_PEOPLE:
            raise AssertionError(
                f"Postmortem for [{postmortem.incident_id}] leaves {sorted(left)} "
                f"for a person, expected {sorted(LEFT_FOR_PEOPLE)}.")

        return True

    return assertion


def _the_postmortem_for(response: httpx2.Response) -> Postmortem:
    incident_id = incident_id_from(response)

    with psycopg.connect(DATABASE_URL) as conn:
        postmortem = postmortems.get_by_incident(conn, incident_id)

    if postmortem is None:
        raise AssertionError(f"No postmortem exists for incident [{incident_id}].")

    return postmortem
