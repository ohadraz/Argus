from __future__ import annotations

from typing import Any

from argus_core.replay import ReplayEntry
from argus_testkit import Assertion, Kept

"""Reading back what a recorder was handed.

Shared by the two suites that need it for different questions:
`test_replay.py` holds the seam - that an entry is built and reaches a recorder
at all - and `llm/test_recorded_client.py` holds what the wrapped client puts
in one.

Split from `argus_testkit` along the line of what knows about Argus. Collecting
whatever a one-argument collaborator was handed is generic and lives there as
`Kept`; these assertions know what a `ReplayEntry` is, and testkit must not.
Not taste: `argus_testkit` is a dev dependency *of* `argus_core`, so depending
back on it would close a cycle that a fresh `uv sync --all-packages` is
entitled to refuse.
"""

KeptEntries = Kept[ReplayEntry]


def a_recorder_that_keeps_what_it_is_given() -> KeptEntries:
    return KeptEntries()


def the_entry_took(recorded: KeptEntries, latency_ms: int) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        entry = recorded.only()

        if entry.latency_ms != latency_ms:
            raise AssertionError(
                f"Expected the call to have taken [{latency_ms}]ms, got [{entry.latency_ms}]."
            )

        return True

    return assertion


def the_entry_was_recorded_for(recorded: KeptEntries, incident_id: str) -> Assertion[Any]:
    def assertion(_result: Any) -> bool:
        entry = recorded.only()

        if entry.incident_id != incident_id:
            raise AssertionError(
                f"Expected the entry recorded for incident [{incident_id}], "
                f"got [{entry.incident_id}]."
            )

        return True

    return assertion