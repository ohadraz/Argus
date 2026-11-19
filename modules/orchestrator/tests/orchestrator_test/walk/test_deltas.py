"""What a node may change.

A node reports what it found and did; the incident's status is derived from
that, by `status_after`, once - so a node that could name a status would be a
second place deciding it, and the two could disagree.
"""

from __future__ import annotations

import pytest
from argus_testkit import Scenario, an_error_was_raised, attempting
from core.models import IncidentStatus
from orchestrator.walk.deltas import StateDelta
from pydantic import ValidationError

# A status a node might once have named, which none may any more.
SOME_STATUS = IncidentStatus.ESCALATED


@pytest.mark.unit
def test_a_node_cannot_name_the_incident_s_status() -> None:
    # Refused rather than ignored, as every field the delta does not carry is:
    # a status dropped in silence would leave the node believing it had moved
    # the incident.
    Scenario() \
        .when(attempting(lambda: StateDelta.model_validate({"status": SOME_STATUS}))) \
        .then(an_error_was_raised(ValidationError))
