"""The incident whose only evidence is the deploy history, end to end.

Io shipped a revision that derives a shopper's lifetime average from their
purchases instead of the total the account already carries, and does it once per
purchase. The figure is the one it always was and takes ten times as long to
produce. The shop runs without a summary cache, so every request computes its own
and every request pays.

What that looks like is the whole case. The median, the 95th and the 99th
percentile all climb by the same multiple, because the revision that is running is
the revision every request runs - there is no cohort to hide in and no tail to
hide behind. Nothing fails, so the error rate never stirs. And no log line mentions
a release: the deploy exists in exactly one place, the Argo CD history the read
tier fetches, which is what makes the change channel load-bearing here rather than
corroborating. That shape is the fixture's to keep, and the demo app's own suite
is where it is asserted.

Two things this case pins that no other one can.

**A cause in the source that is still answered by a rollback.** The repository
holds the slower code and Argus wrote nothing to it. What ended the incident is the
platform returning the deployment to the revision it ran before - a revision that
was reviewed and ran before, which is what admits the action unasked.

**Mitigated, with the fault where it was.** The branch still carries the quadratic
average and automated sync is still suspended, because a run that put the sync
policy back would have handed the incident straight to itself. `mitigated` is the
only honest word for that.

Run the two ways every case here is. Under `nox -s e2e_replay` a green run proves
the path exists - the change channel answering, the strategy reaching for a
rollback, the write tier suspending sync before it asks, the shop coming back.
Under `nox -s e2e` a real model reads a real deploy history and decides for itself
what it is looking at.
"""

from __future__ import annotations

from typing import Any

import httpx2
import pytest
from argus_core.models import FailureMode, IncidentStatus
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_BAD_DEPLOYMENT,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_took_a_rollback_of,
    argus_wrote_a_postmortem,
    cause_identified_as,
    change_channel_returned_a_change,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import a_scenario_was_seeded, the_shops_window

# What the shop's own monitoring pages on here. The same alert the misconfigured
# cache raises, and that is the point: the two are told apart by the evidence and
# never by the page.
A_LATENCY_ALERT = "HighLatency"

THE_SCENARIO = "bad-deployment"

# How close to the window's own quickest minute the last one has to be to count as
# the baseline again. Read off the window rather than copied out of the Target
# Service, because the baseline is its to choose. Loose, because the minute the
# rollback lands in is partly served each way.
THE_QUIET_MINUTES_ARE_WITHIN = 2.0


@pytest.mark.e2e
def test_a_revision_that_slowed_every_page_is_ended_by_rolling_the_deployment_back() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_LATENCY_ALERT,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded(THE_SCENARIO)),
            calling(the_model_answers_from(RECORDED_BAD_DEPLOYMENT))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    cause_identified_as(FailureMode.BAD_DEPLOYMENT),
                    change_channel_returned_a_change(),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    argus_took_a_rollback_of(THE_SERVICE_NAME),
                    _latency_back_to_baseline(),
                    _argo_auto_sync_is_disabled(),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _latency_back_to_baseline() -> Assertion[httpx2.Response]:
    """The incident genuinely ended: the shop's last minute is as quick as its best.

    That the slow minutes are still in the window beside it is the fixture's claim,
    not Argus's, and the demo app's own suite asserts it.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        window = the_shops_window()
        quickest = min(minute["p50_ms"] for minute in window)

        if window[-1]["p50_ms"] > quickest * THE_QUIET_MINUTES_ARE_WITHIN:
            raise AssertionError(
                f"Expected the shop to be quick again once the deployment was put "
                f"back on the earlier revision, and its last minute reports a "
                f"median of [{window[-1]['p50_ms']}]ms against a quickest of "
                f"[{quickest}]ms."
            )

        return True

    return assertion


def _argo_auto_sync_is_disabled() -> Assertion[httpx2.Response]:
    """What makes this mitigated rather than over.

    The rollback moved what is deployed and touched nothing in the repository, so
    the branch still holds the revision that derives the average the expensive way.
    The one thing standing between the shop and the same incident is that the
    application has stopped reconciling itself - and a run that tidily put the sync
    policy back would have handed the incident straight back, while looking in
    every other respect like a success.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        response = httpx2.get(
            f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}",
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        spec: dict[str, Any] = response.json()["spec"]
        automated = spec["syncPolicy"].get("automated")

        if automated is not None:
            raise AssertionError(
                f"Expected automated sync to still be suspended after the "
                f"rollback, and the application reports [{automated}] - so the "
                f"next reconciliation puts the shop back on the slower revision."
            )

        return True

    return assertion
