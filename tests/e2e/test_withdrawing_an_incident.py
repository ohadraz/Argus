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

Both kinds of change are here, and they are unalike in the way that matters. A
flag is one value written twice. A rollback is two things - a deployment on an
earlier revision and a platform no longer reconciling it - and a withdrawal that
managed one of them has left the shop somewhere nobody chose.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from http import HTTPStatus as HttpStatus

import httpx
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
    RECORDED_BAD_DEPLOYMENT,
    RECORDED_FLAG_TOGGLE,
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
from tests.e2e.framework.world import a_scenario_was_seeded

_A_POLL = 0.5


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
                    _nothing_was_written_up(),
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
                    _the_incident_left_the_flag_as_found(),
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
            _argus_is_withdrawn_once_it_has_rolled_the_deployment_back(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.WITHDRAWN),
                    _the_deployment_was_put_back(),
                    _the_shop_reconciles_itself_again(),
                    _nothing_was_written_up()
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS
            )
        )


def _argus_is_withdrawn_after_somebody_else_changed_the_flag(
    alert: dict[str, object]
) -> Callable[[], httpx.Response]:
    """The same walk, with a person reaching in between the change and the undo.

    The order is the whole case: Argus turns the flag off, somebody turns it
    back on under it, and only then is the incident taken back. The withdrawal
    follows the outside change immediately, so what the unwind finds is that
    person's doing rather than a refutation the walk had already put back.

    Written under the human's own credential, like everything else in this suite
    that plays a person - a change Argus is recorded as having made is one it
    would rightly read as its own.
    """
    def step() -> httpx.Response:
        response = argus_is_triggered_with_alert(alert)()
        incident_id = incident_id_from(response)

        _wait_until_argus_turns_the_flag_off()

        if not switch_flag(THE_DEMO_FLAG, enabled=True):
            raise AssertionError(
                f"Could not switch [{THE_DEMO_FLAG}] back on as a person would, "
                f"so nothing below is about a flag changed from outside."
            )

        withdrawn = httpx.post(
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
) -> Callable[[], httpx.Response]:
    """Fires the alert, waits for Argus to change something, and takes it back.

    The wait is what makes this a withdrawal mid-walk rather than a withdrawal
    of an incident nothing had happened to yet. Argus turning the flag off is
    the first moment there is anything to put back, and until then this case
    would pass against a system that stops cleanly only because it had not
    started.

    Answers with the webhook's response, like every other `when` here, because
    that is the only handle the assertions have on the incident.
    """
    def step() -> httpx.Response:
        response = argus_is_triggered_with_alert(alert)()
        incident_id = incident_id_from(response)

        _wait_until_argus_turns_the_flag_off()

        withdrawn = httpx.post(
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


def _the_flag_was_put_back_the_way_argus_found_it() -> Assertion[httpx.Response]:
    """On, which is the state that broke the shop - and the point.

    An unwind restores what Argus changed, not what a healthy shop looks like.
    The person who withdrew the incident has it in hand, and handing them a
    service Argus had quietly half-fixed would be handing them a system in a
    state nobody chose.
    """
    def assertion(_response: httpx.Response) -> bool:
        evaluating = flags_evaluating_true()

        if THE_DEMO_FLAG not in evaluating:
            raise AssertionError(
                f"Expected [{THE_DEMO_FLAG}] to be back on, the way Argus found "
                f"it, but the provider evaluates {sorted(evaluating)}."
            )

        return True

    return assertion


def _nothing_was_written_up() -> Assertion[httpx.Response]:
    """No postmortem, because there was no response to write one about.

    The observable form of "the walk stopped": a graph that carried on past a
    withdrawal would reach the Postmortem node like any other run, and would do
    it quietly.
    """
    def assertion(response: httpx.Response) -> bool:
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


def _the_incident_left_the_flag_as_found() -> Assertion[httpx.Response]:
    """The unwind recorded a decision, not a restore.

    Asserted on the record rather than on the flag, and it has to be: the flag
    ends on either way, so the provider cannot tell a change Argus deliberately
    left alone from one it put back. What separates them is what the incident
    says happened, which is also the only thing the person reading it will have.

    The outcome as the value rather than a sentence it was spelled into: three
    answers, and "left as found" is the one that means somebody else owns the
    flag now.
    """
    def assertion(response: httpx.Response) -> bool:
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


def _argus_is_withdrawn_once_it_has_rolled_the_deployment_back(
    alert: dict[str, object]
) -> Callable[[], httpx.Response]:
    """Fires the alert, waits for the rollback, and takes the incident back.

    The wait is read as the sync policy rather than as the revision, because the
    revision is not a thing the platform lets anybody observe directly - what a
    rollback leaves behind is an application that has stopped reconciling itself,
    and it is the half a withdrawal has to put back. It is also the half that
    would be invisible if it went wrong: a deployment back on the newer revision
    and still not reconciling looks right from every angle a reader has, while
    receiving nothing anybody ships to it.
    """
    def step() -> httpx.Response:
        response = argus_is_triggered_with_alert(alert)()
        incident_id = incident_id_from(response)

        _wait_until_the_shop_stops_reconciling_itself()

        withdrawn = httpx.post(
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
    """Blocks until Argus has rolled back, or says that it never did.

    Read from the platform the way the flag wait is read from the provider: what
    is waited on is the change the world can actually see, and not a row Argus
    wrote about intending it. Suspending the sync is the first half of a
    rollback and therefore the first moment there is anything to put back.
    """
    deadline = time.monotonic() + MITIGATION_TIMEOUT_SECONDS

    while _the_shop_reconciles_itself():
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"Argus never suspended the shop's automated sync within "
                f"[{MITIGATION_TIMEOUT_SECONDS}s], so it never rolled anything "
                f"back and there was no change for a withdrawal to put back."
            )

        time.sleep(_A_POLL)


def _the_shop_reconciles_itself() -> bool:
    """Whether the platform is syncing the application on its own.

    Spelled as the presence of `automated` rather than as a boolean, because
    that is how Argo CD spells it - an `automated` of `{}` means automated, and
    reading it as false here would have this wait return the moment the stack
    came up.
    """
    response = httpx.get(
        f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()

    return response.json()["spec"]["syncPolicy"].get("automated") is not None


def _the_deployment_was_put_back() -> Assertion[httpx.Response]:
    """The unwind returned the application to the revision Argus found it on.

    Asserted on the record rather than on the platform, and it has to be: the
    stand-in's history is append-only and names no current entry, so there is
    nothing to read back that would distinguish a deployment put back from one
    left where the rollback left it. What the person who withdrew the incident
    will have is the incident's own account, which is the thing under test here
    anyway - a restore Argus did not manage is one it has to say it did not
    manage.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            recorded = events.get_by_incident(conn, incident_id)

        unwound = [event for event in recorded if isinstance(event, ChangeUndone)]
        restored = [
            event for event in unwound
            if event.subject == THE_SERVICE_NAME
            and event.outcome is Undone.RESTORED
        ]

        if not restored:
            raise AssertionError(
                f"Incident [{incident_id}] was withdrawn after rolling "
                f"[{THE_SERVICE_NAME}] back, and its unwind recorded "
                f"{[(event.subject, event.outcome) for event in unwound]} rather "
                f"than putting the deployment back."
            )

        return True

    return assertion


def _the_shop_reconciles_itself_again() -> Assertion[httpx.Response]:
    """The other half of the restore, read from the platform.

    Both halves or it is not undone, and this is the one the record alone cannot
    be trusted for: it is the half that leaves a deployment looking correct and
    receiving nothing. A withdrawal that put the revision back and left the sync
    suspended would hand somebody an application quietly out of the delivery
    path, which is worse than the state Argus found.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        if not _the_shop_reconciles_itself():
            raise AssertionError(
                f"Expected [{THE_SERVICE_NAME}] to be reconciling itself again "
                f"once the incident was withdrawn, and its sync policy is still "
                f"the suspended one Argus left to take the rollback."
            )

        return True

    return assertion
