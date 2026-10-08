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

import pytest
from argus_core.models import FailureMode, IncidentStatus
from argus_testkit import Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_BAD_DEPLOYMENT,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_took_a_rollback_of,
    argus_wrote_a_postmortem,
    cause_identified_as,
    investigation_finds_a_deployment_change,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.deployments import THE_AVERAGE_SLOWED, the_deployment_was_staged
from tests.e2e.framework.world import (
    a_scenario_was_seeded,
    argo_auto_sync_is_disabled,
    latency_back_to_baseline,
)

# What the shop's own monitoring pages on here. The same alert the misconfigured
# cache raises, and that is the point: the two are told apart by the evidence and
# never by the page.
A_LATENCY_ALERT = "HighLatency"

THE_SCENARIO = "bad-deployment"


@pytest.mark.e2e
def test_a_revision_that_slowed_every_page_is_ended_by_rolling_the_deployment_back() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_LATENCY_ALERT,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded(THE_SCENARIO)),
            calling(the_model_answers_from(RECORDED_BAD_DEPLOYMENT)),
            calling(the_deployment_was_staged(THE_AVERAGE_SLOWED))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    cause_identified_as(FailureMode.BAD_DEPLOYMENT),
                    investigation_finds_a_deployment_change(),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    argus_took_a_rollback_of(THE_SERVICE_NAME),
                    latency_back_to_baseline(),
                    argo_auto_sync_is_disabled(),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )
