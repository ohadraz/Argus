"""The incident Argus can relieve and cannot resolve.

Every other scenario here ends with the cause undone: a flag goes back where it
was and the shop is well again. A leak has no such ending. The fault is in the
deployed source, restarting the service reclaims what it accumulated and nothing
else does, and the climb begins again the moment the new process starts serving
- so the right answer is a restart *and* a proposed fix, and calling it resolved
would file a postmortem about an incident that is still on its way back.

Three things this case pins that no other one can.

**An onset in a trend.** A flag fault steps: one minute is calm and the next is
not, and the departure is the break between them. A leak ramps, so its earliest
minutes are its lowest and a baseline taken from the window's quietest half is
taken from the climb itself. What locates it is the window's *opening* read as a
second baseline, and what is asserted below is that the onset lands inside the
climb rather than at the window's edge - a few minutes late, because the heap has
to rise clear of the opening's own spread before it counts, and late is the
honest answer where the alternative is confident and wrong.

**A mitigation that puts nothing back.** The restart carries no undo descriptor
and has no field for one, so what admits it is membership of the declared set
(§13) and nothing about its reversibility. The gate is the only thing between it
and production, which is why the action recorded here is worth reading from the
incident rather than from the agent.

**A verdict that needed two questions.** Memory falling says a heap got smaller;
the process start time moving says a new process is serving. Only the two
together separate "the restart landed and helped" from "the traffic dropped" and
from "nothing happened at all" - so the window is asserted to hold both the climb
and the drop, and the process that served its first minute is asserted not to be
the one serving its last.

Run the two ways every case here is. Under `nox -s e2e_replay` a green run proves
the path exists - the detector dating a ramp, the strategy reaching for a
restart, the gate admitting it, the write tier asking the platform and waiting
for the process to change, and the walk carrying on to Code-Fix afterwards.
Under `nox -s e2e` a real model reads a real leak and decides for itself what it
is looking at.
"""

from __future__ import annotations

from collections.abc import Callable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx
import psycopg
import pytest
from argus_core.events import ActionTaken, FixAttempted, OnsetDetected
from argus_core.models import RESTART_SERVICE, IncidentStatus
from argus_incidents.repository import events
from argus_testkit import Assertion, Scenario, all_of, calling, eventually

from tests.e2e.framework.argus import (
    DATABASE_URL,
    RECORDED_RESOURCE_LEAK,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with

# What the shop's own monitoring pages on for a leak, and not what it pages on
# for anything else. Memory is the signal that moves first: by the time a
# climbing heap has moved the error rate the shop has been failing for a while,
# and the alert would be late as well as vague.
A_MEMORY_ALERT = "HighMemoryUsage"

# How much of the climb the onset may miss and still be the climb. The heap has
# to rise clear of the opening stretch's own spread before it counts as
# departed, which on this scenario's slope is about six minutes - so a window
# that is sixty calm minutes and then thirty of climbing should be dated in the
# first third of the climb, and anything earlier than the climb is the detector
# finding a departure in flat telemetry.
THE_CLIMB_IS_MINUTES_LONG = 30
THE_ONSET_MAY_BE_MINUTES_LATE = 10


@pytest.mark.e2e
def test_a_leaking_service_is_restarted_and_still_gets_a_fix_proposed() -> None:
    some_severity = "critical"
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name=A_MEMORY_ALERT,
                                            severity=some_severity)

    Scenario() \
        .given(
            calling(_the_shop_was_left_leaking()),
            calling(the_model_answers_from(RECORDED_RESOURCE_LEAK))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    _the_onset_was_dated_inside_the_climb(),
                    _the_action_taken_was_a_restart_of(THE_SERVICE_NAME),
                    _a_new_process_is_serving_the_shop(),
                    _the_heap_climbed_and_then_came_back_down(),
                    _a_fix_was_proposed()
                ),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _the_onset_was_dated_inside_the_climb() -> Assertion[httpx.Response]:
    """The incident is dated in the ramp, not at the edge of the window.

    The failure this guards is specific and quiet: a detector that cannot see a
    trend reports the first minute it was given, because on a ramp the earliest
    minutes really are the lowest. That answer is indistinguishable from a
    correct one until somebody checks how far back the window happened to
    reach - so what is asserted is that the onset sits inside the climb, which
    a window-edge answer cannot satisfy however wide the window is.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)
        window = _the_shops_window()
        onsets = [
            event for event in _the_incidents_events(incident_id)
            if isinstance(event, OnsetDetected)
        ]

        if not onsets:
            raise AssertionError(
                f"Incident [{incident_id}] never dated an onset, so the "
                f"investigation had nothing to anchor its retrieval on."
            )

        onset = onsets[-1].onset
        climb_began_at = window[-THE_CLIMB_IS_MINUTES_LONG]["bucket_id"]
        latest_it_may_be = window[
            -THE_CLIMB_IS_MINUTES_LONG + THE_ONSET_MAY_BE_MINUTES_LATE
        ]["bucket_id"]

        if not climb_began_at <= onset <= latest_it_may_be:
            raise AssertionError(
                f"Expected the onset to land in the first minutes of the climb, "
                f"between [{climb_began_at}] and [{latest_it_may_be}], and it "
                f"was dated [{onset}] in a window opening at "
                f"[{window[0]['bucket_id']}]."
            )

        return True

    return assertion


def _the_action_taken_was_a_restart_of(service: str) -> Assertion[httpx.Response]:
    """Read from the incident's own account rather than from the platform.

    What the platform was asked is a fact about the fixture; what Argus decided
    to do is the thing under test, and the two are worth keeping apart. A
    restart carries no direction - there is no switch to have been thrown - so
    the event says so by leaving it absent, and an event claiming one would
    describe a different action from the one that was taken.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)
        taken = [
            event for event in _the_incidents_events(incident_id)
            if isinstance(event, ActionTaken)
        ]

        if not taken:
            raise AssertionError(
                f"Incident [{incident_id}] took no action at all, so nothing "
                f"was ever put to the question."
            )

        restarts = [
            event for event in taken
            if event.action_type == RESTART_SERVICE and event.subject == service
        ]

        if not restarts:
            raise AssertionError(
                f"Expected a restart of [{service}], and what was taken was "
                f"{[(event.action_type, event.subject) for event in taken]}."
            )

        if restarts[-1].enabled is not None:
            raise AssertionError(
                f"Expected a restart to carry no direction, and it reported "
                f"[{restarts[-1].enabled}] - which tells a later round a switch "
                f"was thrown."
            )

        return True

    return assertion


def _a_new_process_is_serving_the_shop() -> Assertion[httpx.Response]:
    """The one reading that separates a restart from a coincidence.

    Memory falling is ambiguous on its own - the process was replaced, or the
    traffic dropped - and a fixture whose heap fell without its process
    changing would let a restart that never happened pass as one that did.
    Asserted across the window rather than against a reading taken beforehand,
    because the window keeps both: the minutes before the restart still report
    the process that served them.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        window = _the_shops_window()
        was_serving = window[0]["process_start_time_seconds"]
        serving_now = window[-1]["process_start_time_seconds"]

        if serving_now == was_serving:
            raise AssertionError(
                f"Expected the shop to be serving a new process, and the whole "
                f"window still reports the one that started at [{was_serving}]."
            )

        return True

    return assertion


def _the_heap_climbed_and_then_came_back_down() -> Assertion[httpx.Response]:
    """Both halves, in one window.

    The climb has to still be there afterwards. A fixture that reset its whole
    history on restart would erase the incident at the moment it was mitigated,
    and this case would pass against a service that had never leaked at all.

    Stated as a proportion rather than against the shop's baseline in bytes,
    because what is being asserted is the shape - a heap that got much smaller
    than it had been - and the baseline is the Target Service's to choose.
    """
    def assertion(dont_care_response: httpx.Response) -> bool:
        window = _the_shops_window()
        highest = max(minute["memory_used_bytes"] for minute in window)
        now = window[-1]["memory_used_bytes"]

        if now * 2 > highest:
            raise AssertionError(
                f"Expected the heap to have been reclaimed, and the window's "
                f"highest minute was [{highest}] bytes against [{now}] now."
            )

        return True

    return assertion


def _a_fix_was_proposed() -> Assertion[httpx.Response]:
    """A mitigated leak is not a finished incident.

    The restart bought minutes, and the fault that filled the heap is still in
    the source - so the walk has to carry on to Code-Fix rather than stop at a
    verdict it could have called a success. This is the assertion that would
    fail if a confirmed mitigation were ever routed to `resolved` again.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)
        attempts = [
            event for event in _the_incidents_events(incident_id)
            if isinstance(event, FixAttempted)
        ]

        if not attempts:
            raise AssertionError(
                f"Incident [{incident_id}] was mitigated and then stopped: "
                f"there is no account of Code-Fix having been asked at all, so "
                f"the leak is still in the code with nobody told."
            )

        return True

    return assertion


def _the_incidents_events(incident_id: str) -> list[Any]:
    with psycopg.connect(DATABASE_URL) as conn:
        return events.get_by_incident(conn, incident_id)


def _the_shops_window() -> list[dict[str, Any]]:
    """The Target Service's own metrics, read straight from it.

    Not through Argus's read tier: what this checks is what the world did, and
    a reading taken through the code under test would agree with that code
    about anything it got wrong.
    """
    response = httpx.get(
        f"{TARGET_SERVICE_BASE_URL}/metrics", timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    window: list[dict[str, Any]] = response.json()

    if len(window) < THE_CLIMB_IS_MINUTES_LONG:
        raise AssertionError(
            f"The shop is reporting {len(window)} minutes, which is too few to "
            f"say anything about a climb {THE_CLIMB_IS_MINUTES_LONG} minutes long."
        )

    return window


def _the_shop_was_left_leaking() -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": "resource-leak"},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario
