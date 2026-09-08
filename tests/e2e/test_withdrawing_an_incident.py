from __future__ import annotations

import time
from collections.abc import Callable
from http import HTTPStatus as HttpStatus

import httpx
import psycopg
import pytest
from agent_mitigation import Undone
from argus_core.models.incident_status import IncidentStatus
from argus_incidents.repository import postmortems, timeline
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    ARGUS_WEB_BASE_URL,
    DATABASE_URL,
    MITIGATION_TIMEOUT_SECONDS,
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

"""Taking an incident back while Argus is in the middle of it.

The one thing a person can do to a running response, and the only case in the
suite where the interesting moment is mid-walk rather than at the end: an
incident is withdrawn *after* Argus has changed the world and *before* it has
finished deciding what that change proved.

What is asserted is the whole of the promise. The incident ends as withdrawn
rather than as anything Argus concluded; the flag goes back to the state Argus
found it in, which is the broken one, because the person who took the incident
back is the one holding it now; and no postmortem is written, because there is
no response to write up.
"""

_A_POLL = 0.5

# How `unwind_incident` prefixes what it writes to the timeline. Spelled out
# here rather than shared with it: the note is prose for a person to read, not
# a protocol, and a test pinning the sentence is the thing that notices when it
# silently stops being written.
_WITHDRAWN_NOTE = "withdrawn: "


@pytest.mark.e2e
def test_an_incident_withdrawn_mid_walk_stops_and_puts_its_flag_back() -> None:
    some_alert_name = "HighErrorRate"
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=some_alert_name,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(_a_feature_flag_was_toggled_on()),
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
            calling(_a_feature_flag_was_toggled_on()),
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
    says happened, which is also the only thing the person reading the timeline
    will have.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)

        with psycopg.connect(DATABASE_URL) as conn:
            events = timeline.get_timeline_events(conn, incident_id)

        unwound = [event.action for event in events
                   if event.action and event.action.startswith(_WITHDRAWN_NOTE)]

        if f"{_WITHDRAWN_NOTE}{Undone.LEFT_AS_FOUND}" not in unwound:
            raise AssertionError(
                f"Incident [{incident_id}] was withdrawn after somebody else "
                f"changed [{THE_DEMO_FLAG}], and its unwind recorded {unwound} "
                f"rather than leaving the flag as found."
            )

        return True

    return assertion


def _a_feature_flag_was_toggled_on() -> Callable[[], bool]:
    """The scenario that breaks the shop, and the change Argus undoes.

    Its own copy, like every other case's: a test reaching into another test
    module's `_name` is the same violation here as anywhere else in the repo.
    """
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "feature-flag-toggle"},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
