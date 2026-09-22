"""Which statuses an incident can still move out of.

Asked by anything that waits on an incident - a page that polls, a report that
counts what is still open. It lives on the status rather than in the caller
because "is there more to come?" is a fact about the state machine (spec §10),
and a second copy of it in a template is a second copy that can be wrong.
"""

from __future__ import annotations

import pytest
from argus_core.models.incident_status import IncidentStatus
from argus_testkit import Assertion, Scenario


@pytest.mark.unit
def test_a_resolved_incident_has_nowhere_left_to_go() -> None:
    Scenario() \
        .given(
            resolved := IncidentStatus.RESOLVED
        ) \
        .when(
            lambda: resolved.is_terminal()
        ) \
        .then(
            _nothing_more_is_coming()
        )


@pytest.mark.unit
def test_an_escalated_incident_has_nowhere_left_to_go() -> None:
    # The walk hands over to a human here, and it does not come back.
    Scenario() \
        .given(
            escalated := IncidentStatus.ESCALATED
        ) \
        .when(
            lambda: escalated.is_terminal()
        ) \
        .then(
            _nothing_more_is_coming()
        )


@pytest.mark.unit
def test_an_investigating_incident_is_still_going() -> None:
    Scenario() \
        .given(
            investigating := IncidentStatus.INVESTIGATING
        ) \
        .when(
            lambda: investigating.is_terminal()
        ) \
        .then(
            _there_is_more_to_come()
        )


@pytest.mark.unit
def test_a_mitigating_incident_is_still_going() -> None:
    Scenario() \
        .given(
            mitigating := IncidentStatus.MITIGATING
        ) \
        .when(
            lambda: mitigating.is_terminal()
        ) \
        .then(
            _there_is_more_to_come()
        )


@pytest.mark.unit
def test_a_fixing_incident_is_still_going() -> None:
    # `fixing` reads like an ending and is not one: it is where an incident
    # sits while Code-Fix looks for a permanent fix, so an incident in it is
    # one Argus is still working on.
    Scenario() \
        .given(
            fixing := IncidentStatus.FIXING
        ) \
        .when(
            lambda: fixing.is_terminal()
        ) \
        .then(
            _there_is_more_to_come()
        )


@pytest.mark.unit
def test_a_withdrawn_incident_has_nowhere_left_to_go() -> None:
    # A human took the incident back. Argus stops, and unlike `fixing` there is
    # nothing of Argus's still working on it.
    Scenario() \
        .given(
            withdrawn := IncidentStatus.WITHDRAWN
        ) \
        .when(
            lambda: withdrawn.is_terminal()
        ) \
        .then(
            _nothing_more_is_coming()
        )


@pytest.mark.unit
def test_a_mitigated_incident_has_nowhere_left_to_go() -> None:
    # The service is well and the cause is still there, held back by a flag
    # somebody reverted. Terminal because it is as far as Argus can take it:
    # what would make it `resolved` is a human merging the fix, which is
    # outside Argus's autonomy entirely (spec §13) and nothing here can wait
    # for. An incident that sat here non-terminal would be one a page polls
    # forever.
    Scenario() \
        .given(
            mitigated := IncidentStatus.MITIGATED
        ) \
        .when(
            lambda: mitigated.is_terminal()
        ) \
        .then(
            _nothing_more_is_coming()
        )


def _nothing_more_is_coming() -> Assertion[bool]:
    """That the status is terminal, and says so as a real `bool`.

    Identity rather than truthiness, which is what the assertions this
    replaced were claiming too. Anything that polls this reads the answer
    directly, and a method that returned some truthy object instead would
    satisfy a looser check while serialising as something no page can read.
    """
    def assertion(terminal: bool) -> bool:
        if terminal is not True:
            raise AssertionError(f"Expected a status nothing follows, got [{terminal!r}].")

        return True

    return assertion


def _there_is_more_to_come() -> Assertion[bool]:
    """The other half, and the one whose failure is quieter: a status wrongly
    called terminal ends a walk early rather than leaving a page polling."""
    def assertion(terminal: bool) -> bool:
        if terminal is not False:
            raise AssertionError(f"Expected a status still to be worked on, got [{terminal!r}].")

        return True

    return assertion
