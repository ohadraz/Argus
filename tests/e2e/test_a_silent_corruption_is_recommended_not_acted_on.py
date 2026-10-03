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
alone. The cause is named exactly; the flag that caused it is still on, because
the only thing that could confirm a flip is next week's check; and the incident
ends at `recommended` rather than `escalated`, which is the difference between
"somebody work out what to do" and "somebody go and do this".
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus

import httpx2
import pytest
from argus_core.models import FailureMode, IncidentStatus
from argus_testkit import Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_SILENT_DATA_CORRUPTION,
    TARGET_SERVICE_BASE_URL,
    WALK_TIMEOUT_SECONDS,
    about_the_hypothesis,
    argus_ended_with_status,
    argus_wrote_a_postmortem,
    the_model_answers_from,
    the_shop_raises_its_own_alert,
)
from tests.e2e.framework.flags import THE_DEMO_FLAG, the_flag_provider_reports
from tests.framework.assertions import (
    some_confidence_was_given,
    the_cause_was_identified_as,
)


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
                    about_the_hypothesis(
                        the_cause_was_identified_as(
                            FailureMode.SILENT_DATA_CORRUPTION
                        ),
                        some_confidence_was_given()
                    ),
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


def _the_totals_stopped_keeping_up() -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx2.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "silent-data-corruption"},
            timeout=10.0
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
