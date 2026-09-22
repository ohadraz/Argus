"""What the store handed back, and in what order."""

from __future__ import annotations

from argus_testkit import Assertion
from incident_memory.records import RememberedIncident


def these_incidents_come_back(expected: list[str]) -> Assertion[list[RememberedIncident]]:
    """Exactly these incidents, in this order.

    Order is part of the claim rather than incidental: what the store is for is
    putting the likeliest candidate first, so a recall that found the right set
    and ranked it backwards has failed at the only thing it does.
    """
    def assertion(remembered: list[RememberedIncident]) -> bool:
        came_back = [incident.incident_id for incident in remembered]

        if came_back != expected:
            raise AssertionError(f"Expected {expected}, got {came_back}.")

        return True

    return assertion
