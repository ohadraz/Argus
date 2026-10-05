"""The incident Argus knows what to do about and must not do, end to end.

Every other case here ends with Argus acting or with Argus having nothing to
act on. This one ends with it holding an action it worked out, is confident in,
and declines to take - because nothing would say afterwards whether it worked.

The shop's monthly totals have stopped keeping up with the purchases behind
them. Nothing fails, nothing slows, and no series a monitor watches moves at
all, so no rule fires: what pages Argus is the shop's own integrity check,
weekly, long after the writing went wrong. Its alert carries the finding, and
the finding carries the one thing that dates the fault - the oldest purchase
whose total is short.

What is asserted is a diagnosis, a recommendation, and a world Argus left
alone. The cause is named exactly; the change that caused it is still in place,
because the only thing that could confirm undoing it is next week's check; and
the incident ends at `recommended` rather than `escalated`, which is the
difference between "somebody work out what to do" and "somebody go and do this".

Two cases, one per kind of change that writes wrong data. The mode names the
damage rather than its cause, so which change to undo is read off the record: a
flag that moved at the onset is put back, and a revision that went out at the
onset is rolled back. Both end the same way, which is why they are one file.
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx2
import pytest
from argus_core.events import ActionRecommended
from argus_core.models import ROLL_BACK_DEPLOYMENT, FailureMode, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_DEPLOY_CAUSED_CORRUPTION,
    RECORDED_SILENT_DATA_CORRUPTION,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_wrote_a_postmortem,
    cause_identified_as,
    change_channel_returned_a_change,
    incident_id_from,
    the_model_answers_from,
    the_shop_raises_its_own_alert,
)
from tests.e2e.framework.flags import THE_DEMO_FLAG, the_flag_provider_reports
from tests.e2e.framework.world import a_scenario_was_seeded, the_incidents_events


@pytest.mark.e2e
def test_an_incident_nothing_could_confirm_is_recommended_rather_than_acted_on() -> None:
    # Three things together, and no two of them would do. Named, because this
    # is not an incident nobody could explain - Argus reads a flat window, an
    # alert carrying a date a week old, and a flag that moved at that date, and
    # gets the cause exactly right. Not acted on, because the only evidence
    # that a flip worked is a check somebody else runs on a schedule Argus does
    # not control, and an action reported as taken and never judged is worse
    # than one not taken. And recommended rather than escalated, because there
    # *is* a move: what a reader needs is not "nobody knows" but "go and do
    # this".
    #
    # The alert is raised by the shop rather than built here. Every other case
    # in this directory assembles its own payload, because every other alert is
    # a rule firing on a series and carries nothing the test does not already
    # know. This one carries a finding - how many totals disagree, by how much,
    # and when the oldest of them was written - and a payload assembled here
    # would be the test telling Argus what the check found, which is the whole
    # of what is under test.
    Scenario() \
        .given(
            calling(_the_totals_stopped_keeping_up()),
            calling(the_model_answers_from(RECORDED_SILENT_DATA_CORRUPTION))
        ) \
        .when(
            the_shop_raises_its_own_alert()
        ) \
        .then(
            eventually(
                all_of(
                    cause_identified_as(FailureMode.SILENT_DATA_CORRUPTION),
                    argus_ended_with_status(IncidentStatus.RECOMMENDED),
                    argus_wrote_a_postmortem(),
                    # The teeth. Argus proposed putting this flag back, the
                    # gate declined to let it, and the world is as it found it
                    # - which is what "recommended" has to mean or the status
                    # is a label on an action that quietly happened anyway.
                    the_flag_provider_reports(THE_DEMO_FLAG, enabled=True)
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


@pytest.mark.e2e
def test_a_corruption_a_deployment_left_behind_is_recommended_a_rollback() -> None:
    # The same damage by the other kind of change. No flag moved: a revision
    # went out at the instant the oldest short total was written, and the
    # platform's deploy history is the only place that says so. The mode names
    # the damage rather than its cause, so which change to undo is read off the
    # record - and an empty flag history beside a deploy at the onset is a
    # rollback, recommended for the reason the revert above is.
    #
    # The change channel is load-bearing rather than corroborating: a walk that
    # never read the deploy history has nothing to recommend and ends
    # escalated. Asserted from the incident's own events, because a model can
    # name a deploy it only inferred.
    Scenario() \
        .given(
            calling(a_scenario_was_seeded("monthly-totals-falling-behind")),
            calling(the_model_answers_from(RECORDED_DEPLOY_CAUSED_CORRUPTION))
        ) \
        .when(
            the_shop_raises_its_own_alert()
        ) \
        .then(
            eventually(
                all_of(
                    cause_identified_as(FailureMode.SILENT_DATA_CORRUPTION),
                    change_channel_returned_a_change(),
                    argus_ended_with_status(IncidentStatus.RECOMMENDED),
                    _argus_recommended_a_rollback_of(THE_SERVICE_NAME),
                    _the_application_still_syncs_itself(),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _argus_recommended_a_rollback_of(application: str) -> Assertion[httpx2.Response]:
    """What the incident hands on, read from its own account.

    The status alone would pass on a walk that recommended putting back a flag
    that never moved - the same ending, addressed to a change that did not
    happen. What a reader is told to go and do is the whole of this ending, so
    the kind and the subject are what is asserted.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        recommended = [
            event for event in the_incidents_events(incident_id)
            if isinstance(event, ActionRecommended)
        ]

        if not recommended:
            raise AssertionError(
                f"Incident [{incident_id}] recommended nothing, so nobody was "
                f"handed a next step."
            )

        rollbacks = [
            event for event in recommended
            if event.action_type == ROLL_BACK_DEPLOYMENT
            and event.subject == application
        ]

        if not rollbacks:
            raise AssertionError(
                f"Expected a rollback of [{application}] to be recommended, and "
                f"what was recommended was "
                f"{[(event.action_type, event.subject) for event in recommended]}."
            )

        return True

    return assertion


def _the_application_still_syncs_itself() -> Assertion[httpx2.Response]:
    """The teeth of the deploy case: the platform as Argus found it.

    A rollback is refused while the application reconciles itself, so the write
    tier suspends automated sync before it asks for one. An application still
    syncing is therefore one no rollback was begun against - the deploy case's
    counterpart of the flag still being on.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        response = httpx2.get(
            f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}",
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        spec: dict[str, Any] = response.json()["spec"]
        automated = spec["syncPolicy"].get("automated")

        if automated is None:
            raise AssertionError(
                "Expected the application to still sync itself, and its automated "
                "sync has been suspended - the first step of a rollback Argus was "
                "only meant to recommend."
            )

        return True

    return assertion


def _the_totals_stopped_keeping_up() -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx2.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "silent-data-corruption"},
            timeout=10.0
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
