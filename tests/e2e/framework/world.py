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

import httpx
import psycopg
from argus_incidents.repository import events

from tests.e2e.framework.argus import (
    DATABASE_URL,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
)


def a_scenario_was_seeded(scenario_id: str) -> Callable[[], bool]:
    """Puts the shop into the state a scenario describes, and says whether it took.

    Returned as a step rather than performed here, so a `Scenario`'s `given`
    reads as the arrangement it is and the seeding happens when the case runs
    rather than when it is assembled.
    """
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": scenario_id},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        return response.status_code == HttpStatus.OK

    return seed_scenario


def the_shops_window() -> list[dict[str, Any]]:
    """The Target Service's own metrics, read straight from it.

    Not through Argus's read tier: what this checks is what the world did, and a
    reading taken through the code under test would agree with that code about
    anything it got wrong.
    """
    response = httpx.get(
        f"{TARGET_SERVICE_BASE_URL}/metrics", timeout=REQUEST_TIMEOUT_SECONDS
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
