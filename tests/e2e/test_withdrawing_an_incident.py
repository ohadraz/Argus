"""Taking an incident back while Argus is in the middle of it.

The one thing a person can do to a running response, and the only case in the
suite where the interesting moment is mid-walk rather than at the end: an
incident is withdrawn *after* Argus has changed the world and *before* it has
finished deciding what that change proved.

What is asserted is the whole of the promise. The incident ends as withdrawn
rather than as anything Argus concluded; what Argus changed goes back to the
state it found, which is the broken one, because the person who took the
incident back is the one holding it now; and no postmortem is written, because
there is no response to write up.

Three kinds of change are here, and they are unalike in the way that matters. A
flag is one value written twice. A rollback is two things - a deployment on an
earlier revision and a platform no longer reconciling it - and a withdrawal that
managed one of them has left the shop somewhere nobody chose. A scale-out is two
things as well, and it is the one whose first half a reader can actually see: a
revision is nowhere in the platform's answers, where a replica count is in the
manifest it holds.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from http import HTTPStatus as HttpStatus

import httpx2
import psycopg
import pytest
from agent_mitigation import Undone
from argus_core.events import ChangeUndone
from argus_core.models import IncidentStatus
from argus_incidents.repository import events, postmortems
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    ARGUS_WEB_BASE_URL,
    DATABASE_URL,
    MITIGATION_TIMEOUT_SECONDS,
    RECORDED_AUTOSCALER_FLAPPING,
    RECORDED_BAD_DEPLOYMENT,
    RECORDED_CPU_SATURATION,
    RECORDED_FLAG_TOGGLE,
    RECORDED_HALF_FINISHED_ROLLOUT,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.flags import THE_DEMO_FLAG, flags_evaluating_true, switch_flag
from tests.e2e.framework.world import (
    THE_QUIET_MINUTES_ARE_WITHIN,
    a_scenario_was_seeded,
    the_shops_window,
)

_A_POLL = 0.5

# The size the shop is declared with, in `deploy/values-production.yaml`. It is
# both what a withdrawal has to put the deployment back to and the count that was
# too few - which is the point of a withdrawal: it restores what Argus changed,
# not what a healthy shop looks like.
THE_SIZE_THE_SHOP_IS_DECLARED_WITH = 3
# The floor its autoscaler is declared with, in the same file. What a withdrawn
# pin has to put back, and the floor the controller thrashes down to - so
# restoring it returns the shop to flapping.
THE_FLOOR_THE_AUTOSCALER_IS_DECLARED_WITH = 3

# How the platform addresses the autoscaler, in Kubernetes' own vocabulary. The
# resource route answers about the Deployment unless it is told which kind, and a
# deployment whose size a controller decides has two resources worth asking about.
AN_AUTOSCALER = {
    "kind": "HorizontalPodAutoscaler",
    "group": "autoscaling",
    "version": "v2",
}


@pytest.mark.e2e
def test_an_incident_withdrawn_mid_walk_stops_and_puts_its_flag_back() -> None:
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("feature-flag-toggle")),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE))
        ) \
        .when(
            _argus_is_withdrawn_once_it_has_acted_on(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.WITHDRAWN),
                    _the_flag_was_put_back_the_way_argus_found_it(),
                    _nothing_was_written_up()
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS
            )
        )


@pytest.mark.e2e
def test_a_flag_changed_from_outside_is_left_alone_when_the_incident_is_withdrawn() -> None:
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("feature-flag-toggle")),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE))
        ) \
        .when(
            _argus_is_withdrawn_after_somebody_else_changed_the_flag(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.WITHDRAWN),
                    _the_incident_left_the_flag_as_found()
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS
            )
        )


@pytest.mark.e2e
def test_a_withdrawn_rollback_puts_the_deployment_back_and_resumes_reconciliation() -> None:
    # The other kind of change an incident can make, and the one with two halves
    # to put back. A flag is a value: Argus writes it and a withdrawal writes it
    # again. A rollback is a revision *and* a suspended reconciliation, and the
    # person taking the incident back gets neither half or both.
    #
    # The shop is left slow, as the flag case leaves the flag broken. An unwind
    # restores what Argus changed, not what a healthy shop looks like, and a
    # deployment quietly left on the earlier revision would be a mitigation
    # nobody chose to keep, held by nobody, under an incident that has ended.
    some_alert_name = "HighLatency"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("bad-deployment")),
            calling(the_model_answers_from(RECORDED_BAD_DEPLOYMENT))
        ) \
        .when(
            _argus_is_withdrawn_once_it_has_stopped_the_shop_reconciling(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.WITHDRAWN),
                    _the_shop_is_slow_again(),
                    _the_shop_reconciles_itself_again(),
                    _nothing_was_written_up()
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS
            )
        )


@pytest.mark.e2e
def test_a_withdrawn_scale_out_puts_the_count_back_and_resumes_reconciliation() -> None:
    # The third kind, and the only one whose change a reader can observe
    # directly: the platform's manifest carries the count in force, where it
    # names no current revision at all. So this case asserts the count itself
    # rather than the incident's account of it - and what it asserts is that the
    # shop is back to the three replicas that were too few, which is the honest
    # end of a withdrawal and not a state anybody would call fixed.
    #
    # Both halves again, and the quiet one is the same quiet one: a deployment at
    # its declared size that the platform is no longer reconciling looks correct
    # from every angle a reader has, and receives nothing anybody ships to it.
    some_alert_name = "HighLatency"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("cpu-saturation")),
            calling(the_model_answers_from(RECORDED_CPU_SATURATION))
        ) \
        .when(
            _argus_is_withdrawn_once_it_has_stopped_the_shop_reconciling(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.WITHDRAWN),
                    _the_shop_is_running_the_size_it_is_declared_with(),
                    _the_shop_reconciles_itself_again(),
                    _nothing_was_written_up()
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS
            )
        )


@pytest.mark.e2e
def test_a_withdrawn_pin_puts_the_floor_back_and_resumes_reconciliation() -> None:
    # The fourth kind, and the pair to the case above rather than a repeat of it.
    # Both act on how many replicas run and they undo different numbers: a
    # scale-out puts back the count the deployment had, a pin puts back the floor
    # the controller was allowed to fall to. A withdrawal that could not tell them
    # apart would restore one of them and report the other.
    #
    # What it restores the shop to is flapping, which is the point. Argus is not
    # putting the world right; it is removing what it did, and the incident goes to
    # whoever took it back.
    some_alert_name = "HighLatency"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("autoscaler-flapping")),
            calling(the_model_answers_from(RECORDED_AUTOSCALER_FLAPPING))
        ) \
        .when(
            _argus_is_withdrawn_once_it_has_stopped_the_shop_reconciling(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.WITHDRAWN),
                    _the_autoscaler_may_fall_as_far_as_it_could_before(),
                    _the_shop_reconciles_itself_again(),
                    _nothing_was_written_up()
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS
            )
        )


@pytest.mark.e2e
def test_a_withdrawn_rollback_splits_the_fleet_again() -> None:
    # The fifth kind, and the rollback whose undo is on the platform itself. A
    # revision is nowhere in the platform's answers, so the bad deployment's
    # withdrawal is read off what the shop's requests cost; how far a rollout got
    # is on the Deployment, so this one asserts that directly.
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(a_scenario_was_seeded("half-finished-rollout")),
            calling(the_model_answers_from(RECORDED_HALF_FINISHED_ROLLOUT))
        ) \
        .when(
            _argus_is_withdrawn_once_it_has_stopped_the_shop_reconciling(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.WITHDRAWN),
                    _the_fleet_is_split_again(),
                    _the_shop_reconciles_itself_again(),
                    _nothing_was_written_up()
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS
            )
        )


def _argus_is_withdrawn_after_somebody_else_changed_the_flag(
    alert: dict[str, object]
) -> Callable[[], httpx2.Response]:
    """The same walk, with a person reaching in between the change and the undo.

    The order is the whole case: Argus turns the flag off, somebody turns it
    back on under it, and only then is the incident taken back. The withdrawal
    follows the outside change immediately, so what the unwind finds is that
    person's doing rather than a refutation the walk had already put back.

    Written under the human's own credential, like everything else in this suite
    that plays a person - a change Argus is recorded as having made is one it
    would rightly read as its own.
    """
    def step() -> httpx2.Response:
        response = argus_is_triggered_with_alert(alert)()
        incident_id = incident_id_from(response)

        _wait_until_argus_turns_the_flag_off()

        if not switch_flag(THE_DEMO_FLAG, enabled=True):
            raise AssertionError(
                f"Could not switch [{THE_DEMO_FLAG}] back on as a person would, "
                f"so nothing below is about a flag changed from outside."
            )

        withdrawn = httpx2.post(
            f"{ARGUS_WEB_BASE_URL}/incidents/{incident_id}/withdraw",
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        if withdrawn.status_code != HttpStatus.OK:
            raise AssertionError(
                f"Withdrawing incident [{incident_id}] answered "
                f"[{withdrawn.status_code}]: {withdrawn.text}."
            )

        return response

    return step


def _argus_is_withdrawn_once_it_has_acted_on(
    alert: dict[str, object]
) -> Callable[[], httpx2.Response]:
    """Fires the alert, waits for Argus to change something, and takes it back.

    The wait is what makes this a withdrawal mid-walk rather than a withdrawal
    of an incident nothing had happened to yet. Argus turning the flag off is
    the first moment there is anything to put back, and until then this case
    would pass against a system that stops cleanly only because it had not
    started.

    Answers with the webhook's response, like every other `when` here, because
    that is the only handle the assertions have on the incident.
    """
    def step() -> httpx2.Response:
        response = argus_is_triggered_with_alert(alert)()
        incident_id = incident_id_from(response)

        _wait_until_argus_turns_the_flag_off()

        withdrawn = httpx2.post(
            f"{ARGUS_WEB_BASE_URL}/incidents/{incident_id}/withdraw",
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        if withdrawn.status_code != HttpStatus.OK:
            raise AssertionError(
                f"Withdrawing incident [{incident_id}] mid-walk answered "
                f"[{withdrawn.status_code}]: {withdrawn.text}. Nothing below is "
                f"about an incident that was never taken back."
            )

        return response

    return step


def _wait_until_argus_turns_the_flag_off() -> None:
    """Blocks until Mitigation has acted, or says that it never did.

    Read over the same evaluation API the shop reads, so this waits on the
    change the service can actually see rather than on a row Argus wrote about
    intending it.
    """
    deadline = time.monotonic() + MITIGATION_TIMEOUT_SECONDS

    while THE_DEMO_FLAG in flags_evaluating_true():
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Argus never turned [{THE_DEMO_FLAG}] off within "
                f"[{MITIGATION_TIMEOUT_SECONDS}s], so there was never a change "
                f"for a withdrawal to put back."
            )

        time.sleep(_A_POLL)


def _the_flag_was_put_back_the_way_argus_found_it() -> Assertion[httpx2.Response]:
    """On, which is the state that broke the shop - and the point.

    An unwind restores what Argus changed, not what a healthy shop looks like.
    The person who withdrew the incident has it in hand, and handing them a
    service Argus had quietly half-fixed would be handing them a system in a
    state nobody chose.
    """
    def assertion(_response: httpx2.Response) -> bool:
        evaluating = flags_evaluating_true()

        if THE_DEMO_FLAG not in evaluating:
            raise AssertionError(
                f"Expected [{THE_DEMO_FLAG}] to be back on, the way Argus found "
                f"it, but the provider evaluates {sorted(evaluating)}."
            )

        return True

    return assertion


def _nothing_was_written_up() -> Assertion[httpx2.Response]:
    """No postmortem, because there was no response to write one about.

    The observable form of "the walk stopped": a graph that carried on past a
    withdrawal would reach the Postmortem node like any other run, and would do
    it quietly.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            postmortem = postmortems.get_by_incident(conn, incident_id)

        if postmortem is not None:
            raise AssertionError(
                f"Incident [{incident_id}] was withdrawn and was written up all "
                f"the same: {postmortem.executive_summary!r}."
            )

        return True

    return assertion


def _the_incident_left_the_flag_as_found() -> Assertion[httpx2.Response]:
    """The unwind recorded a decision, not a restore.

    Asserted on the record rather than on the flag, and it has to be: the flag
    ends on either way, so the provider cannot tell a change Argus deliberately
    left alone from one it put back. What separates them is what the incident
    says happened, which is also the only thing the person reading it will have.

    The outcome as the value rather than a sentence it was spelled into: three
    answers, and "left as found" is the one that means somebody else owns the
    flag now.
    """
    def assertion(response: httpx2.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            recorded = events.get_by_incident(conn, incident_id)

        unwound = [event.outcome for event in recorded
                   if isinstance(event, ChangeUndone)]

        if Undone.LEFT_AS_FOUND not in unwound:
            raise AssertionError(
                f"Incident [{incident_id}] was withdrawn after somebody else "
                f"changed [{THE_DEMO_FLAG}], and its unwind recorded {unwound} "
                f"rather than leaving the flag as found."
            )

        return True

    return assertion


def _argus_is_withdrawn_once_it_has_stopped_the_shop_reconciling(
    alert: dict[str, object]
) -> Callable[[], httpx2.Response]:
    """Fires the alert, waits for Argus to suspend the sync, and takes the
    incident back.

    Named for what it waits on rather than for either action, because it serves
    both: suspending the platform's own reconciliation is the first half of a
    rollback *and* of a scale-out, and for one reason in both cases - Argo CD
    would otherwise re-apply what the repository holds at its next pass, which is
    the revision being rolled away from or the count that was too few.

    That makes it the first moment there is anything for a withdrawal to put
    back, which is what keeps this a withdrawal mid-walk rather than a withdrawal
    of an incident nothing had happened to yet. It is also the half that would be
    invisible if it went wrong: a deployment correct in every other respect and
    still not reconciling looks right from every angle a reader has, while
    receiving nothing anybody ships to it.
    """
    def step() -> httpx2.Response:
        response = argus_is_triggered_with_alert(alert)()
        incident_id = incident_id_from(response)

        _wait_until_the_shop_stops_reconciling_itself()

        withdrawn = httpx2.post(
            f"{ARGUS_WEB_BASE_URL}/incidents/{incident_id}/withdraw",
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        if withdrawn.status_code != HttpStatus.OK:
            raise AssertionError(
                f"Withdrawing incident [{incident_id}] mid-walk answered "
                f"[{withdrawn.status_code}]: {withdrawn.text}. Nothing below is "
                f"about an incident that was never taken back."
            )

        return response

    return step


def _wait_until_the_shop_stops_reconciling_itself() -> None:
    """Blocks until Argus has suspended the sync, or says that it never did.

    Read from the platform the way the flag wait is read from the provider: what
    is waited on is the change the world can actually see, and not a row Argus
    wrote about intending it.
    """
    deadline = time.monotonic() + MITIGATION_TIMEOUT_SECONDS

    while _the_shop_reconciles_itself():
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Argus never suspended the shop's automated sync within "
                f"[{MITIGATION_TIMEOUT_SECONDS}s], so it never changed the "
                f"deployment at all and there was no change for a withdrawal to "
                f"put back."
            )

        time.sleep(_A_POLL)


def _the_shop_reconciles_itself() -> bool:
    """Whether the platform is syncing the application on its own.

    Spelled as the presence of `automated` rather than as a boolean, because
    that is how Argo CD spells it - an `automated` of `{}` means automated, and
    reading it as false here would have this wait return the moment the stack
    came up.
    """
    response = httpx2.get(
        f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()

    return response.json()["spec"]["syncPolicy"].get("automated") is not None


def _the_shop_is_slow_again() -> Assertion[httpx2.Response]:
    """The slower revision is the one running again, read from the shop.

    A revision is nowhere in the platform's answers, so the deployment being put
    back is read where it shows: in what every request costs. Slow again is the
    honest end of a withdrawal - Argus took its mitigation back, and the incident
    is with whoever took it.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        window = the_shops_window()
        quickest = min(minute["p50_ms"] for minute in window)

        if window[-1]["p50_ms"] <= quickest * THE_QUIET_MINUTES_ARE_WITHIN:
            raise AssertionError(
                f"Expected the shop to be slow again once the incident was "
                f"withdrawn, and its last minute reports a median of "
                f"[{window[-1]['p50_ms']}]ms against a quickest of [{quickest}]ms "
                f"- so a rollback Argus took under an incident that has ended is "
                f"still in force, and nobody is watching it."
            )

        return True

    return assertion


def _the_shop_is_running_the_size_it_is_declared_with() -> Assertion[httpx2.Response]:
    """The count in force, read from the platform rather than from the record.

    The one restore in this file that can be checked against the world instead of
    against Argus's account of it: a replica count is in the manifest the
    platform holds, where a revision is nowhere in its answers. So this asserts
    the thing itself - and asserts that it is back to the size that was too few,
    because a withdrawal restores what Argus changed and hands the incident to
    the person who took it.

    The manifest arrives as text, which is Argo CD's own shape for it, so this
    parses it the way the write tier has to.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        response = httpx2.get(
            f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}/resource",
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        running: int = json.loads(response.json()["manifest"])["spec"]["replicas"]

        if running != THE_SIZE_THE_SHOP_IS_DECLARED_WITH:
            raise AssertionError(
                f"Expected the shop to be back at the "
                f"[{THE_SIZE_THE_SHOP_IS_DECLARED_WITH}] replicas it is declared "
                f"with once the incident was withdrawn, and the platform reports "
                f"[{running}] - so capacity Argus added under an incident that has "
                f"ended is being paid for by nobody who chose it."
            )

        return True

    return assertion


def _the_shop_reconciles_itself_again() -> Assertion[httpx2.Response]:
    """The other half of the restore, read from the platform.

    Both halves or it is not undone, and this is the one the record alone cannot
    be trusted for: it is the half that leaves a deployment looking correct and
    receiving nothing. A withdrawal that put the revision or the count back and
    left the sync suspended would hand somebody an application quietly out of the
    delivery path, which is worse than the state Argus found.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        if not _the_shop_reconciles_itself():
            raise AssertionError(
                f"Expected [{THE_SERVICE_NAME}] to be reconciling itself again "
                f"once the incident was withdrawn, and its sync policy is still "
                f"the suspended one Argus left to change the deployment."
            )

        return True

    return assertion


def _the_autoscaler_may_fall_as_far_as_it_could_before(
) -> Assertion[httpx2.Response]:
    """The floor in force, read from the platform rather than from the record.

    The second restore in this file that can be checked against the world, and it
    asserts the shop is back to *flapping* - which is the honest end of a
    withdrawal and not a state anybody would call fixed. A withdrawal restores what
    Argus changed and hands the incident to whoever took it back; a run that left
    the count held still would be keeping a mitigation alive under an incident that
    has ended, and nobody would be watching it.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        response = httpx2.get(
            f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}/resource",
            params=AN_AUTOSCALER,
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        floor: int = json.loads(response.json()["manifest"])["spec"]["minReplicas"]

        if floor != THE_FLOOR_THE_AUTOSCALER_IS_DECLARED_WITH:
            raise AssertionError(
                f"Expected the autoscaler to be back at the floor of "
                f"[{THE_FLOOR_THE_AUTOSCALER_IS_DECLARED_WITH}] it is declared "
                f"with once the incident was withdrawn, and the platform reports "
                f"[{floor}] - so a controller Argus held still under an incident "
                f"that has ended is still being held, by nobody who chose it."
            )

        return True

    return assertion


def _the_fleet_is_split_again() -> Assertion[httpx2.Response]:
    """The rollout is back where the incident found it, read from the platform.

    Checked against the world rather than the record: how far a rollout got is on
    the Deployment, so this one asserts the thing itself.

    And what it asserts is that the shop is **broken again**: two versions serving,
    the update paused where somebody left it. That is the honest end of a
    withdrawal rather than a state anybody would call fixed - a run that left the
    fleet converged would be keeping a mitigation alive under an incident that has
    ended, held by nobody who chose it.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        response = httpx2.get(
            f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}/resource",
            timeout=REQUEST_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        manifest = json.loads(response.json()["manifest"])
        status = manifest.get("status", {})
        serving = status.get("replicas")
        updated = status.get("updatedReplicas")

        if serving == updated:
            raise AssertionError(
                f"Expected the fleet to be split again once the incident was "
                f"withdrawn, and the platform reports all {serving} replicas on "
                f"one revision - so a rollback Argus took under an incident that "
                f"has ended is still in force, and nobody is watching it."
            )

        if not manifest.get("spec", {}).get("paused"):
            raise AssertionError(
                "The fleet is split again but the rolling update is no longer "
                "paused, so the platform is converging it on its own - which is "
                "not the world the incident was found in."
            )

        return True

    return assertion
