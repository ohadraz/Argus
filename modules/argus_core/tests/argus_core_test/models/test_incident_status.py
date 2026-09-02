from __future__ import annotations

import pytest
from argus_core.models.incident_status import IncidentStatus

"""Which statuses an incident can still move out of.

Asked by anything that waits on an incident - a page that polls, a report that
counts what is still open. It lives on the status rather than in the caller
because "is there more to come?" is a fact about the state machine (spec §10),
and a second copy of it in a template is a second copy that can be wrong.
"""


@pytest.mark.unit
def test_a_resolved_incident_has_nowhere_left_to_go() -> None:
    assert IncidentStatus.RESOLVED.is_terminal() is True


@pytest.mark.unit
def test_an_escalated_incident_has_nowhere_left_to_go() -> None:
    # The walk hands over to a human here, and it does not come back.
    assert IncidentStatus.ESCALATED.is_terminal() is True


@pytest.mark.unit
def test_an_investigating_incident_is_still_going() -> None:
    assert IncidentStatus.INVESTIGATING.is_terminal() is False


@pytest.mark.unit
def test_a_mitigating_incident_is_still_going() -> None:
    assert IncidentStatus.MITIGATING.is_terminal() is False


@pytest.mark.unit
def test_a_fixing_incident_is_still_going() -> None:
    # `fixing` reads like an ending and is not one: it is where an incident
    # sits while Code-Fix looks for a permanent fix, so an incident in it is
    # one Argus is still working on.
    assert IncidentStatus.FIXING.is_terminal() is False
