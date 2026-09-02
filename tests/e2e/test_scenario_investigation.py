from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus

import httpx
import pytest
from argus_core.models.cause import CauseType
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Scenario, all_of, eventually

from tests.e2e.framework.argus import (
    INVESTIGATION_TIMEOUT_SECONDS,
    MITIGATION_TIMEOUT_SECONDS,
    RECORDED_BAD_DEPLOYMENT,
    RECORDED_FLAG_TOGGLE,
    RECORDED_FLAG_TOGGLE_UNCORROBORATED,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    about_the_hypothesis,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.flags import (
    THE_DEMO_FLAG,
    another_flag_was_toggled_on,
    the_flag_provider_forgot_every_change,
    the_flag_provider_reports,
    the_service_returned_to_baseline,
)
from tests.framework.assertions import (
    some_confidence_was_given,
    the_cause_was_identified_as,
)

"""What Argus concludes about a seeded scenario, and what it then does, end to
end.

Both stand-ins are arranged per case: the Target Service is seeded with a
scenario, and the Anthropic double is seeded with the recorded answer for it.
Neither is put back here - `conftest.py` restores the whole environment after
every case, including the provider's record of what changed, so no case
inherits another's world.

Run two ways, and they prove different things:

- `nox -s e2e_replay` - what CI runs on every push. Every model answer comes
  from a recording committed to this repo, so a green run proves the pipeline
  works: webhook, graph, all three retrieval channels over MCP, the Argo CD
  adapter, the real Anthropic adapter parsing a real Anthropic body, the write
  tier changing a real flag, persistence, terminal status. It proves nothing
  about whether the model was right - that answer was decided when the
  recording was made. Judgement is measured by `nox -s eval`, over fifty
  samples a case.

- `nox -s e2e` - the paid, manual, pre-merge run. A real model reads the real
  retrieved evidence. The seeding step above is inert there, because nothing
  points the web app at the double.

Which is why nothing below asserts on wording. `cause_type` is a closed enum,
the final status is what Argus did, and the flag provider's state is what the
world looks like afterwards; all three hold whichever way this runs, where the
prose never would.

It is also why no case here turns on the model *failing* to identify
something. An outcome that needs the model to be uncertain can only be staged
by a recording, so it would pass replayed and fail live - a test that reports
which harness ran it rather than what Argus does.
"""

SOME_UNRELATED_FLAG = "an-unrelated-feature"


@pytest.mark.e2e
def test_a_diagnosed_flag_toggle_is_mitigated_and_the_world_changed() -> None:
    # The assertions that matter are the last two. An incident reaching
    # `resolved` proves the graph ran; it does not prove Argus did anything.
    # The flag provider reporting the flag off, and the service's own metrics
    # back at baseline, are the difference between a mitigation and a report of
    # one - and they are read from the provider and the service directly,
    # never from what Argus wrote about itself.
    service = "io-shop"  
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=service,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            _a_feature_flag_was_toggled_on(),
            the_model_answers_from(RECORDED_FLAG_TOGGLE),
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    about_the_hypothesis(
                        the_cause_was_identified_as(CauseType.FEATURE_FLAG_TOGGLE),
                        some_confidence_was_given(),
                    ),
                    argus_ended_with_status(IncidentStatus.RESOLVED),
                    the_flag_provider_reports(THE_DEMO_FLAG, enabled=False),
                    the_service_returned_to_baseline(),
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS,
            )
        )


@pytest.mark.e2e
def test_a_diagnosed_bad_deployment_escalates_because_nothing_can_be_reverted() -> None:
    # The change channel, end to end and load-bearing. This scenario's log
    # lines report symptoms only - climbing latency, then timeouts - and never
    # mention a deploy. The deploy exists in exactly one place: the Argo CD
    # revision history the read MCP server fetches. So a diagnosis of
    # BAD_DEPLOYMENT cannot have come from anywhere else, and the whole path
    # is under test - the adapter, the onset-anchored change window, the
    # events reaching the prompt, and the model judging them.
    #
    # The other half of the point is the metrics shape: p95 departs while the
    # error rate stays mild, so a diagnosis that reached for the flag-toggle
    # story would be reading the alert rather than the evidence.
    #
    # It ends `escalated`, not `resolved`: no reversible action answers a bad
    # deployment until the git write path exists, and an incident marked
    # resolved with the bad version still serving is a lie a human would act
    # on. Diagnosable and unmitigable is the honest state.
    some_alert_name = "HighLatency"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            _a_bad_version_was_deployed(),
            the_model_answers_from(RECORDED_BAD_DEPLOYMENT),
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    about_the_hypothesis(
                        the_cause_was_identified_as(CauseType.BAD_DEPLOYMENT),
                        some_confidence_was_given(),
                    ),
                    argus_ended_with_status(IncidentStatus.ESCALATED),
                ),
                timeout=INVESTIGATION_TIMEOUT_SECONDS,
            )
        )


@pytest.mark.e2e
def test_a_flag_the_provider_did_not_record_changing_is_not_reverted() -> None:
    # Escalation on the flag path, as it actually arises now that the
    # Investigator names the flag it blames. The name alone is not
    # authorization: the provider's own record of what changed is, and here it
    # holds nothing about that flag.
    #
    # Staged by erasing the provider's change log after the scenario is seeded,
    # which is what two ordinary situations look like from Argus's side - a
    # flag changed longer ago than the lookback window reaches, and a model
    # naming a flag it inferred from prose rather than saw in a change. Both
    # end the same way, and must: a write to a flag nothing corroborates is a
    # production change made on one source's say-so.
    #
    # The Target Service's own logs still show its evaluations changing, so the
    # investigation is unaffected and the model still names the flag. Only the
    # corroboration is missing - which is precisely the state under test.
    service = "io-shop"
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=service,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            _a_feature_flag_was_toggled_on(),
            the_flag_provider_forgot_every_change,
            the_model_answers_from(RECORDED_FLAG_TOGGLE_UNCORROBORATED),
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.ESCALATED),
                    # Left exactly as it was found. An uncorroborated name is a
                    # reason to stop, not a reason to try it and see.
                    the_flag_provider_reports(THE_DEMO_FLAG, enabled=True),
                ),
                timeout=INVESTIGATION_TIMEOUT_SECONDS,
            )
        )


@pytest.mark.e2e
def test_the_flag_the_investigator_named_is_the_one_reverted() -> None:
    # Two flags changed inside the window, and the Investigator says which one
    # it blames - so there is nothing left to guess at. Argus reverts that flag
    # and leaves the other alone.
    #
    # This is what makes the finding worth typing. Before it, Mitigation
    # re-derived the culprit from the change history alone, found two
    # candidates, and escalated an incident the Investigator had already
    # solved.
    service = "io-shop"
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=service,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            _a_feature_flag_was_toggled_on(),
            another_flag_was_toggled_on(SOME_UNRELATED_FLAG),
            the_model_answers_from(RECORDED_FLAG_TOGGLE),
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.RESOLVED),
                    the_flag_provider_reports(THE_DEMO_FLAG, enabled=False),
                    # Untouched. Naming one flag is not licence to tidy the
                    # other, and a second revert would be a production change
                    # nothing diagnosed.
                    the_flag_provider_reports(SOME_UNRELATED_FLAG, enabled=True),
                    the_service_returned_to_baseline(),
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS,
            )
        )


def _a_feature_flag_was_toggled_on() -> Callable[[], bool]:
    return _a_scenario_was_seeded("feature-flag-toggle")


def _a_bad_version_was_deployed() -> Callable[[], bool]:
    return _a_scenario_was_seeded("bad-deployment")


def _a_scenario_was_seeded(scenario_id: str) -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": scenario_id},
            timeout=10.0,
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
