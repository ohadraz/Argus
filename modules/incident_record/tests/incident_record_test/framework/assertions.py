"""Assertions more than one of this package's suites makes."""

from __future__ import annotations

from argus_testkit import Assertion
from core.models import IncidentStatus

from incident_record_test.framework.transactions import Seen


def the_account_was_written_inside_the_change(seen: list[Seen],
                                              status: IncidentStatus) -> Assertion[object]:
    """That the account of a change to `status` was written once, inside the
    change's own transaction: seen there as `status`, and from anywhere else as
    still acknowledged."""
    def assertion(_ended: object) -> bool:
        expected = [Seen(inside=status, outside=IncidentStatus.ACKNOWLEDGED)]

        if seen != expected:
            raise AssertionError(
                f"Expected the account to be written once, inside the change - seen "
                f"as [{status}] where it was written and still as "
                f"[{IncidentStatus.ACKNOWLEDGED}] anywhere else; it was written "
                f"{seen}."
            )

        return True

    return assertion
