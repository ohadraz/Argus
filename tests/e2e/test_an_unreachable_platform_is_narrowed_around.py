"""The incident Argus narrows itself to fit, end to end.

Every other case in this suite runs against an estate that answers. This one
runs against one that will not act: the deployment platform's API server is
refusing, while it goes on saying what it has deployed. Four of Argus's five
generic mitigations reach the estate through that platform - the rollback, the
restart, the scale-out and the autoscaler pin - so a single platform failure
takes four actions away at once, and takes them away for a reason that has
nothing to do with the incident.

The world is staged so that the one thing Argus cannot do is the first thing it
should want to do. A revision went out and a flag was switched on in the same
window, and the revision is what ranks first: its diff moves the boundary
deciding which purchases fall in this month, which is the divisor the failing
page divides by. So the deploy owns the call path that is throwing, and the flag
merely exposed it.

That is the whole of why the rollback ranks above the revert, and it is worth
stating because the obvious version does not work. Staged against a revision
that changed some *other* function, a real model ranked the flag first and was
right to: a deploy whose diff cannot reach the failing path is not a better
explanation for being nearer in time. The ranking has to be earned by the diff.

What is left when the rollback fails is the flag revert, which lives with a
different provider, is still answering, and does end the incident.

Three things this case pins that no other one can.

**A failed action that is not a refuted candidate.** Everywhere else, an action
that does not end the incident is evidence against the explanation it was taken
for. Here it is evidence about the platform and none at all about the cause -
and an agent that read it the usual way would strike a candidate off its list
for a reason that was never about that candidate.

**Narrowing rather than escalating.** The rollback failing is the first thing
that happens, and it would be the last if Argus escalated on it. What the walk
has to do instead is work out which of its remaining candidates are reachable,
pass over the three that are not, and go on - so the assertion is not merely
that the incident was mitigated but that exactly one action was ever attempted
through the platform that went away.

**The record says which four went with it.** An incident that ended on the one
action Argus had left reads, with nothing else in the timeline, as though Argus
had simply preferred that action. `PlatformUnavailable` is what stops it being
read that way, and it is asserted here as one event naming four kinds, not as
one event per candidate skipped.

What is deliberately not asserted is which failure mode the model named. Two
changes moved in the window on purpose, so the first candidate is supposed to
be the deployment and the second the flag; which words it reaches for about
either is measured by `nox -s eval`, and a case pinning them here would fail
whenever a re-recording changed the model's mind about a label this case does
not rest on.

Recorded under `both` alone. Nothing in "a platform that will not act" varies by
which tool the model found a file with.
"""

from __future__ import annotations

import httpx2
import pytest
from argus_core.events import ActionTaken, PlatformUnavailable, VerdictReached
from argus_core.models import (
    DEPLOYMENT_PLATFORM,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    IncidentStatus,
    Verdict,
    the_actions_through,
    the_platform_of,
)
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    RECORDED_CONTROL_PLANE_UNREACHABLE,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    about_the_hypothesis,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    argus_read_a_change_event,
    argus_wrote_a_postmortem,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.flags import (
    THE_DEMO_FLAG,
    the_flag_provider_reports,
    the_service_returned_to_baseline,
)
from tests.e2e.framework.world import a_scenario_was_seeded, the_incidents_events
from tests.framework.assertions import some_confidence_was_given

# What the shop's own monitoring pages on here. The flag is what is breaking the
# account page, so this is an error-rate incident and not a latency one - and the
# deployment in the window is a real candidate rather than a decoy: its diff owns
# the divisor the failing page divides by.
AN_ERROR_RATE_ALERT = "HighErrorRate"

THE_SCENARIO = "control-plane-unreachable"


@pytest.mark.e2e
def test_a_platform_that_will_not_act_leaves_argus_the_one_action_it_still_has() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=AN_ERROR_RATE_ALERT,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded(THE_SCENARIO)),
            calling(the_model_answers_from(RECORDED_CONTROL_PLANE_UNREACHABLE))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    about_the_hypothesis(some_confidence_was_given()),
                    argus_read_a_change_event(),
                    _the_platform_went_on_saying_what_it_had_deployed(),
                    _the_rollback_was_reached_for_and_nothing_answered(),
                    _the_application_still_syncs_itself(),
                    _what_the_platform_took_with_it_was_recorded_once(),
                    _only_the_one_action_was_ever_attempted_through_it(),
                    _the_action_that_ended_it_was_a_revert_of(THE_DEMO_FLAG),
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    the_flag_provider_reports(THE_DEMO_FLAG, enabled=False),
                    the_service_returned_to_baseline(),
                    argus_wrote_a_postmortem()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_platform_went_on_saying_what_it_had_deployed() -> Assertion[httpx2.Response]:
    """The half of the staging that makes this narrowing rather than blindness.

    A platform refusing its reads as well would hide the deployment, and the
    deployment is this incident's first candidate - so the walk would never
    reach for the rollback, never learn the platform is unavailable, and this
    case would pass against a shop staging a different mode entirely.

    Read from the platform directly rather than from what Argus fetched, which
    `argus_read_a_change_event` already asserts from the other side. The two
    together are the claim: the reporting routes answered, and Argus's change
    channel got something back from them.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        response = httpx2.get(
            f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}",
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        if not response.is_success:
            raise AssertionError(
                f"Expected the deployment platform to go on reporting while it "
                f"refused to act, and it answered [{response.status_code}] for "
                f"[{THE_SERVICE_NAME}] - so this run staged a platform that "
                f"cannot be seen rather than one that cannot be used."
            )

        history = response.json().get("status", {}).get("history", [])

        if not history:
            raise AssertionError(
                "The deployment platform answered with no history at all, so "
                "there was no deployment in the window for the walk to reach "
                "for and nothing for its rollback to fail on."
            )

        return True

    return assertion


def _the_application_still_syncs_itself() -> Assertion[httpx2.Response]:
    """Nothing the rollback started got as far as changing the estate.

    Suspending reconciliation is the first write a rollback makes, and it goes
    through the same acting routes the rest of it does - so a platform refusing
    to act refuses that too, and the rollback fails having touched nothing.
    Which is what makes passing over the three remaining candidates honest: the
    walk is narrowing away from actions it cannot take, rather than stepping
    around a half-finished one it can no longer see the end of.

    Order-independent because `/scenario/reset` puts automated sync back and
    this suite's teardown calls it after every case - so an earlier rollback or
    pin cannot leave a suspension here for this case to read as its own.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        response = httpx2.get(
            f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}",
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        automated = response.json()["spec"]["syncPolicy"].get("automated")

        if automated is None:
            raise AssertionError(
                "Expected automated sync to be untouched, and the application "
                "reports it suspended - so the rollback reached the platform "
                "far enough to change it, and there is something left behind "
                "that no verdict in this incident accounts for."
            )

        return True

    return assertion


def _the_rollback_was_reached_for_and_nothing_answered() -> Assertion[httpx2.Response]:
    """Argus wanted the rollback, asked for it, and was told the platform is gone.

    The whole premise, and the one assertion here that fails if the model ranks
    the flag first. That is deliberate: a walk that reached the flag revert
    without ever touching the platform would end mitigated, leave the flag off
    and the shop well, and satisfy every other assertion in this case while
    demonstrating nothing it exists for.

    Read as the verdict that came back from *that* action rather than as a
    verdict the incident reached at some point. A later action failing the same
    way would be a second fact, and a case matching on the set would accept it
    as this one.
    """
    def assertion(response: httpx2.Response) -> bool:
        recorded = the_incidents_events(incident_id_from(response))
        reached_for = [
            position for position, event in enumerate(recorded)
            if isinstance(event, ActionTaken)
            and event.action_type == ROLL_BACK_DEPLOYMENT
        ]

        if not reached_for:
            raise AssertionError(
                f"Expected the walk to reach for a rollback of the deployment "
                f"that moved in the window, and the actions it took were "
                f"{_what_was_taken(recorded)} - so the platform was never asked "
                f"to do the one thing it cannot do."
            )

        answered = [
            event for event in recorded[reached_for[0] + 1:]
            if isinstance(event, VerdictReached)
        ]

        if not answered:
            raise AssertionError(
                "The rollback was taken and no verdict was ever reached about "
                "it, so nothing in the record says what the platform answered."
            )

        if answered[0].outcome is not Verdict.PLATFORM_UNREACHABLE:
            raise AssertionError(
                f"Expected the rollback to come back as an unreachable platform, "
                f"and it came back [{answered[0].outcome}] - which is a verdict "
                f"about the explanation it was taken for rather than about the "
                f"platform it was taken through."
            )

        return True

    return assertion


def _what_the_platform_took_with_it_was_recorded_once() -> Assertion[httpx2.Response]:
    """One event, naming the platform and every kind of action that went with it.

    Once rather than once per candidate passed over: the fact is about the
    platform, and repeated against each candidate it teaches a reader to skim
    exactly the sentence that explains the outcome.

    The four kinds are compared against the mapping rather than written out
    here, so a sixth mitigation placed on the deployment platform is carried
    into this assertion by the same type check that carries it everywhere else -
    and one placed on the flag provider does not silently widen what this
    accepts.
    """
    def assertion(response: httpx2.Response) -> bool:
        recorded = the_incidents_events(incident_id_from(response))
        unavailable = [
            event for event in recorded if isinstance(event, PlatformUnavailable)
        ]

        if len(unavailable) != 1:
            raise AssertionError(
                f"Expected the incident to record the platform going away "
                f"exactly once, and it recorded it [{len(unavailable)}] time(s) - "
                f"so the record either does not explain why three candidates "
                f"went untried, or repeats the explanation against each of them."
            )

        if unavailable[0].platform != DEPLOYMENT_PLATFORM:
            raise AssertionError(
                f"Expected the deployment platform to be the one that did not "
                f"answer, and the incident recorded "
                f"[{unavailable[0].platform}] - so the walk narrowed itself "
                f"away from the actions that were still available to it."
            )

        expected = the_actions_through(DEPLOYMENT_PLATFORM)

        if unavailable[0].actions_unavailable != expected:
            raise AssertionError(
                f"Expected the event to carry every kind of action that reaches "
                f"the estate through the deployment platform, which is "
                f"{expected}, and it carries "
                f"{unavailable[0].actions_unavailable} - so a reader is told a "
                f"platform's name and left to look up what went with it."
            )

        return True

    return assertion


def _only_the_one_action_was_ever_attempted_through_it() -> Assertion[httpx2.Response]:
    """The three remaining platform candidates were passed over, not tried.

    Stated as a count of attempts because that is where passing over is
    visible: a candidate the walk declines to act on proposes no action and
    records no attempt, so what a later reader sees is an absence. An agent
    that narrowed itself correctly attempts exactly one thing through a dead
    platform - the one that told it the platform was dead.

    The kinds are compared through `the_platform_of` rather than listed, for the
    reason the event's contents are: a sixth mitigation on this platform has to
    be covered by this assertion without anybody remembering to add it.
    """
    def assertion(response: httpx2.Response) -> bool:
        recorded = the_incidents_events(incident_id_from(response))
        through_it = [
            event for event in recorded
            if isinstance(event, ActionTaken)
            and the_platform_of(event.action_type) == DEPLOYMENT_PLATFORM
        ]

        if len(through_it) != 1:
            raise AssertionError(
                f"Expected exactly one action to be attempted through the "
                f"platform that would not answer - the one that found out - and "
                f"[{len(through_it)}] were: "
                f"{[(event.action_type, event.subject) for event in through_it]}. "
                f"So the walk went on reaching for actions it had already been "
                f"told were unavailable."
            )

        return True

    return assertion


def _the_action_that_ended_it_was_a_revert_of(flag: str) -> Assertion[httpx2.Response]:
    """The last action, on the one platform that was still answering.

    The last rather than the only one: the rollback came first by design, and a
    case demanding a single action would fail on the very behaviour the scenario
    exists to produce.

    The direction is asserted alongside the flag, because "a flag was changed"
    is the half of the sentence nobody can act on - and a revert that switched
    this flag on would be a mitigation that staged the incident again.
    """
    def assertion(response: httpx2.Response) -> bool:
        recorded = the_incidents_events(incident_id_from(response))
        taken = [event for event in recorded if isinstance(event, ActionTaken)]

        if not taken:
            raise AssertionError(
                "The incident took no action at all, so nothing was ever put to "
                "the question."
            )

        if taken[-1].action_type != REVERT_FEATURE_FLAG or taken[-1].subject != flag:
            raise AssertionError(
                f"Expected the walk to finish on a revert of [{flag}], which is "
                f"the one action left to it, and what it took was "
                f"{_what_was_taken(recorded)}."
            )

        if taken[-1].enabled is not False:
            raise AssertionError(
                f"Expected the flag to have been switched off, and the action "
                f"reports [{taken[-1].enabled}] - so either the direction is "
                f"missing from the record or Argus staged this incident a "
                f"second time."
            )

        return True

    return assertion


def _what_was_taken(recorded: list[object]) -> list[tuple[str, str | None]]:
    """Every action an incident took, as a failure message can print it."""
    return [
        (event.action_type, event.subject)
        for event in recorded if isinstance(event, ActionTaken)
    ]
