from __future__ import annotations

import pytest
from agent_communicator import notify


@pytest.mark.unit
def test_notify_emits_the_incident_and_the_message() -> None:
    some_incident_id = "kuki-123"
    some_message = "escalating"
    emitted: list[str] = []

    notify(some_incident_id, some_message, emit=emitted.append)

    assert some_incident_id in emitted[0]
    assert some_message in emitted[0]


@pytest.mark.unit
def test_notify_does_not_raise_on_the_escalation_path() -> None:
    # This is a stub it must still be a *working* stub, or "Argus could not 
    # determine the cause" crashes the graph instead of reaching a human.
    notify("kuki-123", "escalating")
