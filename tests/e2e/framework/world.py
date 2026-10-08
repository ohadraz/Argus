"""What the Target Service was told to do, and what it reports having done.

The stack's own side of an e2e case. Every test here begins by putting the shop
into a known state and ends by asking the shop - not Argus - what happened, and
both halves belong together because both are about the world rather than about
the agent walking it.

Read straight from the service on purpose. A reading taken through Argus's read
tier would agree with the code under test about anything that code got wrong,
which is the one thing an end-to-end test exists to catch.

`a_scenario_was_seeded` is one function rather than one per scenario. Six files
had grown their own copy of the flag-toggle seeder, each explaining in its
docstring that it could not use a neighbour's because reaching into another test
module's `_name` is a violation - which was true, and had a third answer neither
copy took: a public name here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from http import HTTPStatus as HttpStatus
from typing import Any

import httpx2
import psycopg
from argus_incidents.repository import events
from argus_testkit import Assertion
from deployment_platform.argocd import AUTOMATED, ENABLED, SPEC, SYNC_POLICY

from tests.e2e.framework.argus import (
    DATABASE_URL,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
)

# How close to the window's own quickest minute the last one has to be to count as
# the baseline again. Read off the window rather than copied out of the Target
# Service, because the baseline is its to choose. Loose, because the minute the
# mitigation lands in is partly served each way.
THE_QUIET_MINUTES_ARE_WITHIN = 2.0


def a_scenario_was_seeded(scenario_id: str) -> Callable[[], bool]:
    """Puts the shop into the state a scenario describes, or fails the case.

    Returned as a step rather than performed here, so a `Scenario`'s `given`
    reads as the arrangement it is and the seeding happens when the case runs
    rather than when it is assembled.

    Raises rather than answering `False`, because `calling` discards what a step
    returns: a seed the shop refused went unnoticed, and the case went on to
    investigate a shop with nothing staged in it.
    """
    def seed_scenario() -> bool:
        response = httpx2.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": scenario_id},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        if response.status_code != HttpStatus.OK:
            raise AssertionError(
                f"Expected the Target Service to stage scenario [{scenario_id}], "
                f"got [{response.status_code}]: {response.text}."
            )

        return True

    return seed_scenario


def the_shops_window() -> list[dict[str, Any]]:
    """The Target Service's own metrics, read straight from it.

    Not through Argus's read tier: what this checks is what the world did, and a
    reading taken through the code under test would agree with that code about
    anything it got wrong.
    """
    response = httpx2.get(
        f"{TARGET_SERVICE_BASE_URL}/scenario/metrics", timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    window: list[dict[str, Any]] = response.json()

    if not window:
        raise AssertionError("The Target Service reported no metrics at all.")

    return window


def the_incidents_events(incident_id: str) -> list[Any]:
    """Everything the walk published for one incident, in the order it happened."""
    with psycopg.connect(DATABASE_URL) as conn:
        return events.get_by_incident(conn, incident_id)


def the_middle_of(figures: Iterable[float]) -> float:
    """The median of a minute's worth of readings, without the import.

    A plain sort rather than `statistics.median`, because the window is small
    and what an assertion needs from the middle of it is the reading itself
    rather than an average of two - a figure the shop actually reported is a
    figure a failure message can be checked against.
    """
    ordered = sorted(figures)

    if not ordered:
        raise AssertionError("Asked for the middle of no readings at all.")

    return float(ordered[len(ordered) // 2])


def argo_auto_sync_is_disabled() -> Assertion[httpx2.Response]:
    """The platform has stopped reconciling the application, as Argus left it.

    What makes a mitigation at the deployment mitigated rather than over. The
    action changed what is running and nothing in the repository, so the next
    reconciliation puts back whatever the repository declares - the fault with
    it. A run that tidily restored the sync policy would hand the incident
    straight back while looking in every other respect like a success.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        automated = _argos_automated_sync()

        if automated is not None:
            raise AssertionError(
                f"Expected automated sync to still be suspended, and the "
                f"application reports [{automated}] - so the next reconciliation "
                f"puts back what the repository declares, fault and all."
            )

        return True

    return assertion


def argo_auto_sync_is_enabled() -> Assertion[httpx2.Response]:
    """The platform still reconciles the application, as Argus found it.

    Suspending automated sync is the first write a rollback makes, so a policy
    still in force says no rollback got as far as changing the estate - the
    deployment's counterpart of a flag still where it was.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        if _argos_automated_sync() is None:
            raise AssertionError(
                "Expected automated sync to be untouched, and the application "
                "reports it suspended - the first step of a rollback this "
                "incident was not meant to have taken."
            )

        return True

    return assertion


def latency_back_to_baseline() -> Assertion[httpx2.Response]:
    """The incident genuinely ended: the shop's last minute is as quick as its best.

    That the slow minutes are still in the window beside it is the fixture's claim,
    not Argus's, and the demo app's own suite asserts it.
    """
    def assertion(dont_care_response: httpx2.Response) -> bool:
        window = the_shops_window()
        quickest = min(minute["p50_ms"] for minute in window)

        if window[-1]["p50_ms"] > quickest * THE_QUIET_MINUTES_ARE_WITHIN:
            raise AssertionError(
                f"Expected the shop to be quick again once Argus acted, and its "
                f"last minute reports a median of [{window[-1]['p50_ms']}]ms "
                f"against a quickest of [{quickest}]ms."
            )

        return True

    return assertion


def _argos_automated_sync() -> Any:
    """The application's automated sync policy, or `None` where it is suspended.

    Read as Argo CD reads it: an `automated` object whose `enabled` is absent or
    true. Suspending is `enabled: false`, which keeps the object and the
    operator's settings in it, so a present `automated` is not on its own an
    application syncing itself.
    """
    response = httpx2.get(
        f"{TARGET_SERVICE_BASE_URL}/argocd/{THE_SERVICE_NAME}",
        timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    spec: dict[str, Any] = response.json()[SPEC]
    automated = spec[SYNC_POLICY].get(AUTOMATED)

    if automated is None or automated.get(ENABLED) is False:
        return None

    return automated
