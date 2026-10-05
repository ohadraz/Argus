"""The incident answered by adding something, end to end.

Every other mitigation in this suite puts something back: a flag to the state it
was in, a process to a fresh start, a deployment to the revision before it. Io's
shop here is running the code it was reviewed with, reading the configuration it
was deployed with, and serving traffic that has grown past the three replicas
somebody sized it for. Nothing is wrong with it. It is too small, and the only
answer is capacity it never had.

Three things this case pins that no other one can, and one it deliberately does
not.

**A mitigation that restores nothing.** What admits a scale-out unasked is
membership of the declared set (spec §13), and this is the member that makes that
criterion legible: there is no earlier state it returns to, so a gate asking
about reversibility would have had to argue about it. The action recorded here is
read from the incident rather than from the platform, because what is under test
is what Argus decided.

**The half of resource exhaustion a restart gets wrong.** A leak and a saturated
service are the same shape on a latency graph, and the fixture stages this one
with its heap flat and its traffic climbing - so a walk that reached for
`resource-leak` restarts the shop, measures no improvement, and has to carry on.
That is the whole reason the mode exists, and this case is the one that would
fail if the evidence stopped separating them.

**Capacity as the denominator.** `cpu_limit_cores` is the deployment's total
across its replicas, so the scale-out moves the series the incident was visible
in: the gauge pins against its ceiling while the load climbs, and then the
ceiling itself rises. Asserted with the saturated minutes still in the window,
because a fixture that regenerated its history at the new size would erase the
incident at the moment the mitigation wanted judging against it.

**What this case does not assert, and why.** The obvious claim - that a
shortfall of capacity gets no patch proposed for it - is not made here, and what
rules it out is the fixture rather than the design. Code-Fix is aimed by what the
investigation named, and a capacity conclusion names no file, so it reads the
repository at large - which carries a real fault in every scenario, because the
shop's main branch is the bad deployment's commit. Asked to fix a service whose
source is correct, the agent found that fault and proposed a patch for it, which
is a defensible answer to a question nobody should have put to it. So an
assertion here would measure the model's reading of a repository this fixture
deliberately leaves broken, and would fail for a reason that says nothing about
whether Argus patches shortfalls of capacity.

What is about Argus, and is asserted, is the ending: the incident is `mitigated`
and not `resolved`. Git still asks for three replicas, reconciliation is
suspended so that nothing re-applies them, and the traffic that outgrew the
deployment is still arriving.

Run the two ways every case here is. Under `nox -s e2e_replay` a green run proves
the path exists - the detector dating a latency climb it was not shown a heap
for, the strategy reaching for a scale-out, the gate admitting it, the write tier
reading what is running before it doubles it, and the walk carrying on to a
postmortem afterwards. Under `nox -s e2e` a real model reads a real saturation
and decides for itself what it is looking at.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx2
import pytest
from argus_core.events import ActionTaken, VerdictReached
from argus_core.models import SCALE_OUT, FailureMode, IncidentStatus, Verdict
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_CPU_SATURATION,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_wrote_a_postmortem,
    cause_identified_as,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import the_incidents_events, the_shops_window

# What the shop's own monitoring pages on here. Latency is the only judged series
# this incident moves: the error rate stays at its baseline throughout, because
# errors are the leak's late signal and borrowing them would blur the one pair of
# scenarios this case exists to separate.
A_LATENCY_ALERT = "HighLatency"

# The size the shop is declared with, in `deploy/values-production.yaml`. Named
# rather than derived, because what is being asserted is that Argus left the
# deployment larger than anybody asked for - a figure read back from the platform
# would agree with whatever the platform happened to say.
THE_SIZE_THE_SHOP_IS_DECLARED_WITH = 3

# How close to its ceiling the gauge has to get to count as saturated. Not
# equality: usage is clamped at capacity and aggregated as the minute's mean, so
# the minute a surge arrives in is part busy and part not, and a bound demanding
# the whole ceiling would pin this to the shape of the ramp rather than to the
# saturation.
SATURATED_IS_THIS_MUCH_OF_THE_CEILING = 0.9


@pytest.mark.e2e
def test_a_shop_that_outgrew_its_capacity_is_scaled_out_and_left_mitigated() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_LATENCY_ALERT,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(_the_shop_was_left_short_of_capacity()),
            calling(the_model_answers_from(RECORDED_CPU_SATURATION))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    cause_identified_as(FailureMode.DEMAND_SATURATION),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    _the_action_taken_was_a_scale_out_of(THE_SERVICE_NAME),
                    _the_scale_out_was_confirmed(),
                    _the_shop_is_running_more_replicas_than_it_was_declared_with(),
                    _the_window_holds_the_saturation_and_the_capacity_that_ended_it(),
                    _the_application_no_longer_syncs_itself(),
                    argus_wrote_a_postmortem()
                    # No assertion about the code tier, deliberately. A reader
                    # expecting "and no patch was proposed" should see the
                    # docstring above: Code-Fix roams a repository this fixture
                    # keeps deliberately broken, so what such an assertion would
                    # measure is the model's reading of somebody else's staged
                    # fault rather than anything Argus decided here.
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_action_taken_was_a_scale_out_of(application: str) -> Assertion[httpx2.Response]:
    """Read from the incident's own account rather than from the platform.

    What the platform was asked is a fact about the fixture; what Argus decided to
    do is the thing under test. A scale-out carries no direction - there is no
    switch to have been thrown - and no count either: where it went is the write
    tier's to have resolved from what was running, so an event claiming a number
    here would be describing a decision nothing at this layer made.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        taken = [
            event for event in the_incidents_events(incident_id)
            if isinstance(event, ActionTaken)
        ]

        if not taken:
            raise AssertionError(
                f"Incident [{incident_id}] took no action at all, so nothing was "
                f"ever put to the question."
            )

        scale_outs = [
            event for event in taken
            if event.action_type == SCALE_OUT and event.subject == application
        ]

        if not scale_outs:
            raise AssertionError(
                f"Expected a scale-out of [{application}], and what was taken was "
                f"{[(event.action_type, event.subject) for event in taken]} - so "
                f"either the mode reached the wrong strategy, or a restart was "
                f"tried on a shop with nothing to reclaim."
            )

        if scale_outs[-1].enabled is not None:
            raise AssertionError(
                f"Expected a scale-out to carry no direction, and it reported "
                f"[{scale_outs[-1].enabled}] - which tells a later round a switch "
                f"was thrown."
            )

        return True

    return assertion


def _the_scale_out_was_confirmed() -> Assertion[httpx2.Response]:
    """The service answered for the action, and answered well.

    Stated beside the status rather than left to it, because the two say
    different things: `mitigated` is where the incident ended, and a confirmed
    verdict is the claim that the minutes after the scale-out were measured and
    found healthy. A walk that reached `mitigated` off a refutation and a second
    attempt would satisfy one and not the other.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)
        verdicts = [
            event.outcome for event in the_incidents_events(incident_id)
            if isinstance(event, VerdictReached)
        ]

        if Verdict.CONFIRMED not in verdicts:
            raise AssertionError(
                f"Incident [{incident_id}] reached the verdicts "
                f"{[str(verdict) for verdict in verdicts]}, so nothing here was "
                f"confirmed by the shop returning to its baseline."
            )

        return True

    return assertion


def _the_shop_is_running_more_replicas_than_it_was_declared_with(
) -> Assertion[httpx2.Response]:
    """The count in force, read where the only honest answer to that lives.

    From the platform's live resource and not from the repository: the values
    file says what the deployment is asked to converge on, and after one
    scale-out those are different numbers. That difference is the whole of why
    this is `mitigated` - git still asks for the size that was too small.

    The manifest arrives as text, which is Argo CD's own shape for it, so this
    parses it the way the write tier has to.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        running = _the_replicas_the_platform_reports()

        if running <= THE_SIZE_THE_SHOP_IS_DECLARED_WITH:
            raise AssertionError(
                f"Expected the shop to be running more than the "
                f"[{THE_SIZE_THE_SHOP_IS_DECLARED_WITH}] replicas it is declared "
                f"with, and the platform reports [{running}] - so whatever the "
                f"incident recorded, no capacity ever reached the deployment."
            )

        return True

    return assertion


def _the_window_holds_the_saturation_and_the_capacity_that_ended_it(
) -> Assertion[httpx2.Response]:
    """Both halves, in one window, in one pair of series.

    The saturated minutes have to still be there afterwards. Capacity is a
    history of resizes rather than a number the fixture holds, precisely so that
    a scale-out does not regenerate the minutes already served at the new size -
    and a fixture that did would erase the incident at the moment the mitigation
    wanted judging against it, leaving this case passing against a shop that was
    never short of anything.

    The recovery is visible in the same series as the incident because capacity
    is the deployment's total across its replicas. That is what makes a second
    field reporting a replica count unnecessary, and it is worth pinning here: a
    later change that made the limit one replica's would leave the gauge pinned
    for ever and no reader able to see the mitigation at all.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        window = the_shops_window()
        ceilings = [
            minute["cpu_limit_cores"] for minute in window
            if minute["cpu_limit_cores"] is not None
        ]

        if not ceilings:
            raise AssertionError(
                "The shop reported no CPU capacity on any minute, so there is no "
                "telling what it had to spend or whether that ever changed."
            )

        saturated = [
            minute for minute in window
            if minute["cpu_limit_cores"]
            and minute["cpu_used_cores"]
            >= minute["cpu_limit_cores"] * SATURATED_IS_THIS_MUCH_OF_THE_CEILING
        ]

        if not saturated:
            highest = max(
                minute["cpu_used_cores"] / (minute["cpu_limit_cores"] or 1)
                for minute in window
            )

            raise AssertionError(
                f"Expected the window to still hold the minutes the shop had "
                f"nothing left to spend, and its busiest minute used "
                f"[{highest:.2f}] of the ceiling - so the saturation has been "
                f"erased from the record a mitigation is judged against."
            )

        if ceilings[-1] <= ceilings[0]:
            raise AssertionError(
                f"Expected the shop's capacity to have grown with the scale-out, "
                f"and the window opens on [{ceilings[0]}] cores and ends on "
                f"[{ceilings[-1]}] - so the one series a reader would see the "
                f"mitigation in never moved."
            )

        return True

    return assertion


def _the_application_no_longer_syncs_itself() -> Assertion[httpx2.Response]:
    """What makes this mitigated rather than over, and what a timer would undo.

    Argo CD puts a live replica count back to what the repository holds at its
    next sync, so a scale-out taken under automated sync is a mitigation with a
    timer on it: the shop would return to saturation at a moment nothing in the
    record explains. Suspending reconciliation is therefore part of performing
    the scale, and a run that tidily put the policy back would have handed the
    incident straight back to itself while looking in every other respect like a
    success.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        response = httpx2.get(
            f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}",
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        automated = response.json()["spec"]["syncPolicy"].get("automated")

        if automated is not None:
            raise AssertionError(
                f"Expected automated sync to still be suspended after the "
                f"scale-out, and the application reports [{automated}] - so the "
                f"next reconciliation takes the shop back to the "
                f"[{THE_SIZE_THE_SHOP_IS_DECLARED_WITH}] replicas that were too "
                f"few."
            )

        return True

    return assertion


def _the_replicas_the_platform_reports() -> int:
    """How many replicas are serving, as the platform holds the manifest."""
    response = httpx2.get(
        f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}/resource",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    manifest: dict[str, Any] = json.loads(response.json()["manifest"])
    replicas: int = manifest["spec"]["replicas"]

    return replicas


def _the_shop_was_left_short_of_capacity() -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx2.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "cpu-saturation"},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
