"""The incident answered by stopping something, end to end.

The scenario next door is a shop that outgrew its capacity, and the answer there
is capacity. This one is the same traffic and the same shortfall at the bottom of
every cycle, and capacity is the *wrong* answer to it: a controller owns the
replica count, so a count Argus sets is re-derived away within a minute. What is
wrong here is not the size but that the size will not settle.

Four things this case pins that no other one can.

**A mitigation that stops rather than adds or restores.** The three before the
scale-out put something back and the scale-out added something; this takes away a
controller's room to shrink, by raising the floor it may fall to until it meets
the ceiling a human declared. What admits it unasked is membership of the declared
set (spec §13) and nothing about the kind of change it makes, which is the second
time that criterion has had to hold against a new shape of action and the reason
it is asserted rather than assumed.

**The near-miss is the mode next door's answer, and it is refuted by the estate.**
A reader who sees pinned utilisation and stops looking names demand saturation and
scales out, which works for about a minute. Nothing in Argus refutes it: the
controller puts the count back, the service is still unwell at the next
measurement, and the walk carries on. That is why this case does not assert a
single attempt - a recorded walk that reached for capacity first and pinned
second is the *expected* shape, and the assertion is on where it ended.

**The action is read from the incident, never from the platform.** What the
platform was asked is a fact about the fixture; what Argus decided is the thing
under test. A pin carries no direction and no count - how high the floor goes is
the write tier's to resolve from the live resource, bounded by Argus's own cap.

**Mitigated and never resolved.** The values file still declares the
stabilisation window that flaps, reconciliation is suspended so nothing
re-applies the floor, and putting the floor back returns the shop to flapping. No
patch is asserted either way, for the reason the scale-out's case gives at
length: Code-Fix roams a repository this fixture keeps deliberately broken, so an
assertion there would measure the model's reading of somebody else's staged fault.

Collected under `both` alone, and the dearest walk in the suite: the near-miss is
a whole mitigation attempt, so a capture bills for two.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx2
import pytest
from argus_core.events import ActionTaken, VerdictReached
from argus_core.models import (
    PIN_AUTOSCALER,
    SCALE_OUT,
    ActionType,
    FailureMode,
    IncidentStatus,
    Verdict,
)
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_AUTOSCALER_FLAPPING,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    about_the_hypothesis,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_wrote_a_postmortem,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.world import the_incidents_events, the_shops_window
from tests.framework.assertions import (
    some_confidence_was_given,
    the_cause_was_identified_as,
)

# What the shop's own monitoring pages on here, as the surge next door does.
# Latency is the only judged series this incident moves.
A_LATENCY_ALERT = "HighLatency"

# The bounds the autoscaler is declared with in `deploy/values-production.yaml`.
# Named as well as read back, and the two readings answer different questions: the
# platform says where the floor and the ceiling sit *now*, which is what "they meet"
# is asserted against, while these say where they sat before the pin - so a floor
# that merely equals the one it was declared with is a pin that never arrived.
THE_FLOOR_THE_CONTROLLER_FELL_TO = 3
THE_CEILING_THE_CONTROLLER_REACHED = 6

# How the platform addresses the autoscaler, in Kubernetes' own vocabulary.
AN_AUTOSCALER = {
    "kind": "HorizontalPodAutoscaler",
    "group": "autoscaling",
    "version": "v2",
}


@pytest.mark.e2e
def test_a_flapping_autoscaler_is_pinned_and_left_mitigated() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_LATENCY_ALERT,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(_the_shops_autoscaler_was_left_flapping()),
            calling(the_model_answers_from(RECORDED_AUTOSCALER_FLAPPING))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    _optionally(
                        when=_the_walk_tried_capacity,
                        then=_that_attempt_was_not_confirmed()
                    ),
                    about_the_hypothesis(
                        the_cause_was_identified_as(
                            FailureMode.AUTOSCALING_PATHOLOGY
                        ),
                        some_confidence_was_given()
                    ),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    _the_action_that_ended_it_was_a_pin_of(THE_SERVICE_NAME),
                    _the_pin_was_confirmed(),
                    _the_autoscalers_floor_now_meets_its_ceiling(),
                    _the_window_holds_the_flapping_and_the_count_that_stopped(),
                    _the_application_no_longer_syncs_itself(),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_action_that_ended_it_was_a_pin_of(application: str) -> Assertion[httpx2.Response]:
    """The *last* action, not the only one.

    A walk that tried capacity first and was refuted by the controller is the
    shape this scenario is built to produce, so an assertion demanding a single
    action would fail on the very behaviour the fixture exists to demonstrate.
    What matters is that the thing Argus finished on is the one that holds.
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

        if taken[-1].action_type != PIN_AUTOSCALER or taken[-1].subject != application:
            raise AssertionError(
                f"Expected the last action to be a pin of [{application}], and "
                f"what was taken was "
                f"{[(event.action_type, event.subject) for event in taken]} - so "
                f"either the mode reached the wrong strategy, or Argus finished on "
                f"a count the controller re-derives within a minute."
            )

        if taken[-1].enabled is not None:
            raise AssertionError(
                f"Expected a pin to carry no direction, and it reported "
                f"[{taken[-1].enabled}] - which tells a later round a switch was "
                f"thrown."
            )

        return True

    return assertion


def _the_walk_tried_capacity(response: httpx2.Response) -> bool:
    """Whether the near-miss was made at all, which is the model's choice.

    The recording takes this path, so a replayed walk reaches for capacity before
    pinning; a walk that reasons its way straight to the pin has done nothing
    wrong. So this is a premise and not an assertion: it says whether there is an
    attempt here to judge, and never that there should have been one.
    """
    return any(
        action == SCALE_OUT
        for action, _ in _the_actions_and_their_outcomes(response)
    )


def _that_attempt_was_not_confirmed() -> Assertion[httpx2.Response]:
    """What must hold wherever capacity was tried.

    The obvious answer here is wrong and nothing in Argus says so: a reader who
    sees pinned utilisation scales out, the controller re-derives the count within
    a minute, and the service is still unwell when the attempt is measured. Were
    such an attempt ever confirmed, the incident would close on a count that does
    not hold.

    Every attempt rather than the first, because a walk refuted once may reach for
    capacity again. And `CONFIRMED` alone is the failure: `REFUTED` is the measured
    refusal the recording holds, while a shop already serving at its ceiling
    refuses the write and answers `NOT_ATTEMPTED` - a different mechanism arriving
    at the same place.
    """
    def assertion(response: httpx2.Response) -> bool:
        story = _the_actions_and_their_outcomes(response)

        if any(
            action == SCALE_OUT and outcome == Verdict.CONFIRMED
            for action, outcome in story
        ):
            raise AssertionError(
                f"A scale-out taken for incident [{incident_id_from(response)}] "
                f"was confirmed, so a count the controller re-derives within a "
                f"minute read as a recovery and this incident could have closed "
                f"on it. The actions and their outcomes were {story}."
            )

        return True

    return assertion


def _the_actions_and_their_outcomes(
    response: httpx2.Response
) -> list[tuple[ActionType, Verdict | None]]:
    """Each action the walk took, in order, beside what the shop said about it.

    Paired by position in the stream rather than by the hypothesis both events
    carry: a walk may reach for the same explanation twice, so the id says which
    candidate an attempt belongs to and not which attempt. `None` is an action
    still being measured, or one abandoned before it ever was.
    """
    story: list[tuple[ActionType, Verdict | None]] = []

    for event in the_incidents_events(incident_id_from(response)):
        if isinstance(event, ActionTaken):
            story.append((event.action_type, None))
        elif isinstance(event, VerdictReached) and story:
            story[-1] = (story[-1][0], event.outcome)

    return story


def _the_pin_was_confirmed() -> Assertion[httpx2.Response]:
    """The service answered for the action, and answered well.

    Stated beside the status because the two claim different things, and here the
    difference is sharper than anywhere else in this suite: `mitigated` says where
    the incident ended, and a confirmed verdict says the minutes after the pin were
    measured against the detector and found clear. The running cycle supplies no
    such minutes, which is what the refuted attempt above is the evidence of.
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
                f"confirmed by the shop settling."
            )

        return True

    return assertion


def _the_autoscalers_floor_now_meets_its_ceiling() -> Assertion[httpx2.Response]:
    """Read from the live resource, which is the only place the floor in force is.

    The values file still asks for the floor that flapped - that is what makes this
    mitigated rather than over - so the repository is the wrong place to ask. The
    manifest arrives as text, which is Argo CD's own shape for it.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        floor, ceiling = _the_bounds_the_platform_reports()

        if floor != ceiling:
            raise AssertionError(
                f"Expected the autoscaler's floor to have been raised to meet its "
                f"ceiling, and the platform reports a floor of [{floor}] against a "
                f"ceiling of [{ceiling}] - so the controller still has room to "
                f"scale down and the shop is still flapping."
            )

        if floor <= THE_FLOOR_THE_CONTROLLER_FELL_TO:
            raise AssertionError(
                f"Expected the floor to have risen above the "
                f"[{THE_FLOOR_THE_CONTROLLER_FELL_TO}] it was declared with, and "
                f"the platform reports [{floor}] - so whatever the incident "
                f"recorded, no pin ever reached the controller."
            )

        return True

    return assertion


def _the_window_holds_the_flapping_and_the_count_that_stopped(
) -> Assertion[httpx2.Response]:
    """Both halves, in the one series that separates this mode from the surge.

    The oscillating minutes have to still be there afterwards: capacity is derived
    from the cycle's position, so a fixture that regenerated its history at the
    pinned size would erase the incident at the moment the mitigation wanted
    judging against it - and this case would pass against a shop that never
    flapped.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        capacities = [
            minute["cpu_limit_cores"] for minute in the_shops_window()
            if minute["cpu_limit_cores"] is not None
        ]

        if not capacities:
            raise AssertionError(
                "The shop reported no CPU capacity on any minute, so there is no "
                "telling what it had to spend or whether that ever moved."
            )

        settled = capacities[-1]
        moved = {capacity for capacity in capacities if capacity != settled}

        if not moved:
            raise AssertionError(
                f"Every minute in the window reports [{settled}] cores, so the "
                f"capacity never moved - which is demand saturation's window and "
                f"not this mode's. The flapping has been erased from the record a "
                f"mitigation is judged against."
            )

        if settled != float(THE_CEILING_THE_CONTROLLER_REACHED):
            raise AssertionError(
                f"The window ends on [{settled}] cores where a pinned controller "
                f"serves every minute at "
                f"[{THE_CEILING_THE_CONTROLLER_REACHED}] - so the count is still "
                f"moving, and the capacities seen were "
                f"{sorted({*moved, settled})}."
            )

        return True

    return assertion


def _the_application_no_longer_syncs_itself() -> Assertion[httpx2.Response]:
    """What makes this mitigated rather than over, and what a timer would undo.

    Argo CD re-applies an autoscaler's whole manifest at its next sync, floor
    included, so a pin taken under automated sync is a mitigation with a timer on
    it: the shop returns to flapping at a moment nothing in the record explains.
    Suspending reconciliation is part of performing the pin, and a run that tidily
    put the policy back would have handed the incident to itself while looking in
    every other respect like a success.
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
                f"Expected automated sync to still be suspended after the pin, and "
                f"the application reports [{automated}] - so the next "
                f"reconciliation puts the flapping floor back."
            )

        return True

    return assertion


def _the_bounds_the_platform_reports() -> tuple[int, int]:
    """The floor and ceiling in force, as the platform holds the manifest."""
    response = httpx2.get(
        f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}/resource",
        params=AN_AUTOSCALER,
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    manifest: dict[str, Any] = json.loads(response.json()["manifest"])
    floor: int = manifest["spec"]["minReplicas"]
    ceiling: int = manifest["spec"]["maxReplicas"]

    return floor, ceiling


def _the_shops_autoscaler_was_left_flapping() -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx2.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "autoscaler-flapping"},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario


def _optionally[T](when: Callable[[T], bool],
                  then: Assertion[T]) -> Assertion[T]:
    """Asserts something where its premise holds, and passes where it does not.

    For a claim about a step the system was free not to take - an attempt a model
    may or may not make, a branch a policy may or may not reach. "Whatever it
    tried, that was not confirmed" is a real claim, and both other spellings lose
    it: demanding the attempt fails against the better answer, and dropping the
    assertion stops judging the attempt at all.

    The premise is a predicate rather than an assertion, because it is not
    something that can fail. It reads off the same result and answers only
    whether there is anything here to judge.
    """

    def conditional_assertion(result: T) -> bool:
        if not when(result):
            return True

        return then(result)

    return conditional_assertion
