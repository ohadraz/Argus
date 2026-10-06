"""A revert that seems to work, judged by the rule that paged.

The flag scenario with something left behind. Reverting the flag clears the shop
for a minute, and then it fails a single minute at a time, at gaps that never
settle into a rhythm - often enough that the rule which paged, an error rate
averaged over ten minutes, never stops firing.

**That the revert is refuted.** Read off the metrics alone, the clean minute
after the revert looks like the recovery it is supposed to be, and every
failing minute after it is a single minute that could as well be chance. The
alert is what defines acceptable here: it fired on a condition, and the revert
fixed the incident only if that condition stopped holding. It never does.

**That the incident does not end mitigated.** What the walk does after the
refutation is the model's to choose and not asserted here. What is asserted is
that it did not end on the revert having held.
"""

from __future__ import annotations

import httpx2
import psycopg
import pytest
from argus_core.events import ActionTaken, VerdictReached
from argus_core.models import REVERT_FEATURE_FLAG, ActionType, IncidentStatus, Verdict
from argus_incidents.repository import incidents
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_FLAG_REVERT_LEAVES_A_FLAP,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_is_triggered_with_alert,
    argus_wrote_a_postmortem,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import a_scenario_was_seeded, the_incidents_events

# What the shop's own monitoring pages on here: the burn-rate rule, which stays
# firing while any minute in ten fails.
AN_ERROR_RATE_ALERT = "ErrorRateSustained"


@pytest.mark.e2e
def test_a_revert_the_shop_goes_on_flapping_after_is_refuted() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=AN_ERROR_RATE_ALERT,
                                            severity=some_severity)

    # The scenario's id is also the recording's name, so one constant serves both.
    Scenario() \
        .given(
            calling(a_scenario_was_seeded(RECORDED_FLAG_REVERT_LEAVES_A_FLAP)),
            calling(the_model_answers_from(RECORDED_FLAG_REVERT_LEAVES_A_FLAP))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_wrote_a_postmortem(),
                    _a_flag_revert_was_taken_and_refuted(),
                    _the_incident_did_not_end_mitigated()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _a_flag_revert_was_taken_and_refuted() -> Assertion[httpx2.Response]:
    """Every flag revert the walk took came back refuted, and there was one.

    Every one rather than the first, because a walk may revert the flag again in
    a later round, and any of them confirmed is the incident closing on a fix
    the rule never agreed with.
    """
    def assertion(response: httpx2.Response) -> bool:
        story = _the_actions_and_their_outcomes(response)
        reverts = [outcome for action, outcome in story if action == REVERT_FEATURE_FLAG]

        if not reverts:
            raise AssertionError(
                f"Incident [{incident_id_from(response)}] took no flag revert, so "
                f"the one action this case is about was never put to the rule. "
                f"The actions and their outcomes were {story}."
            )

        if any(outcome != Verdict.REFUTED for outcome in reverts):
            raise AssertionError(
                f"Expected every flag revert taken for incident "
                f"[{incident_id_from(response)}] to be refuted, since the rule "
                f"that paged never stopped firing. The actions and their outcomes "
                f"were {story}."
            )

        return True

    return assertion


def _the_incident_did_not_end_mitigated() -> Assertion[httpx2.Response]:
    """Wherever the walk ended, it was not on a fix that held.

    Not a particular ending: what the walk does once the revert is refuted is the
    model's choice. Asserted once the postmortem is written, which is when the
    walk has ended at all.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            incident = incidents.get(conn, incident_id)

        if incident is None:
            raise AssertionError(f"No incident found with id [{incident_id}].")

        if incident.status == IncidentStatus.MITIGATED:
            raise AssertionError(
                f"Incident [{incident_id}] ended [{incident.status}], on a shop "
                f"whose rule never stopped firing - so a fix was reported as "
                f"holding that the alert never agreed with. The actions and "
                f"their outcomes were {_the_actions_and_their_outcomes(response)}."
            )

        return True

    return assertion


def _the_actions_and_their_outcomes(
    response: httpx2.Response
) -> list[tuple[ActionType, Verdict | None]]:
    """Each action the walk took, in order, beside the verdict it reached.

    Paired by position in the stream, as the flapping autoscaler's case pairs
    them. `None` is an action still being measured, or abandoned before it was.
    """
    story: list[tuple[ActionType, Verdict | None]] = []

    for event in the_incidents_events(incident_id_from(response)):
        if isinstance(event, ActionTaken):
            story.append((event.action_type, None))
        elif isinstance(event, VerdictReached) and story:
            story[-1] = (story[-1][0], event.outcome)

    return story
