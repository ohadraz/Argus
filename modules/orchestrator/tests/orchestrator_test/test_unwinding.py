from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import cast
from unittest.mock import MagicMock, create_autospec

import pytest
from agent_mitigation import UndoAttempt
from argus_core import new_id
from argus_core.events import ChangeUndone, IncidentEvent
from argus_core.models import TakenAction, UndoDescriptor, Undone
from argus_testkit import Assertion, Scenario, all_of
from orchestrator import unwinding
from orchestrator.unwinding import unwind_incident

"""Putting back everything an incident changed, once nobody wants it walked.

The other half of a withdrawal. Marking the incident stops the walk; this is
what makes stopping honest - a walk halted mid-flight has production in a state
it chose for a reason that no longer applies, and nobody but Argus knows what
that state replaced.

Every recorded change goes through the same conditional undo, and none of them
is filtered by what the walk made of it. A change already put back reads as one
somebody else changed, so it is left alone - which makes running this twice cost
nothing, and makes it safe over an incident whose walk had already tidied up
after itself.

What became of each change is published rather than written as a note. There is
one event per change, because an incident that moved three flags and restored
two of them is not a withdrawal that worked, and the one left behind is
somebody's to go and look at.
"""

_DONT_CARE_INCIDENT_ID = "buki-123"


@pytest.fixture
def undo() -> MagicMock:
    return cast(MagicMock, create_autospec(unwinding.UndoChange, instance=True))


@pytest.fixture
def published() -> list[IncidentEvent]:
    return []


@pytest.mark.unit
def test_every_change_the_incident_recorded_is_put_back(
    undo: MagicMock, published: list[IncidentEvent]
) -> None:
    a_first_change = _an_undo_descriptor_for("monthly-spend-feature")
    a_second_change = _an_undo_descriptor_for("checkout-kill-switch")
    undo.return_value = _restored("dont care")

    Scenario() \
        .given(
            an_incident_that_changed := _an_incident_that_changed(
                a_first_change, a_second_change)
        ) \
        .when(
            lambda: unwind_incident(
                _DONT_CARE_INCIDENT_ID,
                taken_actions_of=_reading(an_incident_that_changed),
                undo=undo,
                publisher=published.append,
            )
        ) \
        .then(
            _the_changes_put_back(undo, a_first_change, a_second_change)
        )


@pytest.mark.unit
def test_an_action_that_changed_nothing_has_nothing_to_put_back(
    undo: MagicMock, published: list[IncidentEvent]
) -> None:
    # An action the gate refused, or one that could not be performed at all.
    # There is no descriptor because there was no change, and calling the undo
    # for it would ask the provider about a flag nobody set.
    Scenario() \
        .given(
            an_incident_that_changed_nothing := (
                _an_incident_whose_taken_action_carries_no_descriptor()
            )
        ) \
        .when(
            lambda: unwind_incident(
                _DONT_CARE_INCIDENT_ID,
                taken_actions_of=_reading(an_incident_that_changed_nothing),
                undo=undo,
                publisher=published.append,
            )
        ) \
        .then(all_of(
            _nothing_was_undone(undo),
            _nothing_was_reported(published)
        ))


@pytest.mark.unit
def test_what_each_undo_found_is_published_on_the_incident(
    undo: MagicMock, published: list[IncidentEvent]
) -> None:
    # A human reading a withdrawn incident has to be able to tell what state
    # Argus left behind without going and looking at the environment. The
    # outcome travels as the value rather than inside the sentence: a flag
    # somebody else now owns and a flag nobody could read are different
    # findings, and only one of them is anybody's to act on.
    some_detail = "flag [monthly-spend-feature] was left as found"
    undo.return_value = UndoAttempt(
        flag="monthly-spend-feature",
        outcome=Undone.LEFT_AS_FOUND,
        detail=some_detail,
    )

    Scenario() \
        .given(
            an_incident_that_changed := _an_incident_that_changed(
                _an_undo_descriptor_for("monthly-spend-feature"))
        ) \
        .when(
            lambda: unwind_incident(
                _DONT_CARE_INCIDENT_ID,
                taken_actions_of=_reading(an_incident_that_changed),
                undo=undo,
                publisher=published.append,
            )
        ) \
        .then(all_of(
            _one_change_was_reported(published),
            _the_report_says(published, detail=some_detail),
            _the_report_names(published, Undone.LEFT_AS_FOUND),
            _the_report_is_about(published, "monthly-spend-feature")
        ))


@pytest.mark.unit
def test_one_change_that_cannot_be_read_does_not_stop_the_others(
    undo: MagicMock, published: list[IncidentEvent]
) -> None:
    # The unwind is the last thing that happens to an incident. A flag the
    # provider could not answer for is a flag left behind either way, and
    # letting it take the rest with it leaves more behind, not less.
    undo.side_effect = [
        UndoAttempt(
            flag="monthly-spend-feature",
            outcome=Undone.NOT_ESTABLISHED,
            detail="dont care",
        ),
        _restored("checkout-kill-switch"),
    ]

    Scenario() \
        .given(
            an_incident_that_changed := _an_incident_that_changed(
                _an_undo_descriptor_for("monthly-spend-feature"),
                _an_undo_descriptor_for("checkout-kill-switch"))
        ) \
        .when(
            lambda: unwind_incident(
                _DONT_CARE_INCIDENT_ID,
                taken_actions_of=_reading(an_incident_that_changed),
                undo=undo,
                publisher=published.append,
            )
        ) \
        .then(all_of(
            _both_changes_were_attempted(undo),
            _both_were_reported(published)
        ))


def _the_changes_put_back(undo: MagicMock,
                          *expected: UndoDescriptor) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        attempted = [call.args[0] for call in undo.call_args_list]

        if attempted != list(expected):
            raise AssertionError(
                f"Expected the changes {expected} to be put back, got {attempted}."
            )

        return True

    return assertion


def _nothing_was_undone(undo: MagicMock) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        if undo.call_count:
            raise AssertionError(
                f"Expected nothing to be put back, got "
                f"{[call.args[0] for call in undo.call_args_list]}."
            )

        return True

    return assertion


def _nothing_was_reported(published: list[IncidentEvent]) -> Assertion[None]:
    """A change nobody made leaves nothing to say about it. An event here would
    put a restore on the timeline for a flag that was never set."""
    def assertion(_unwound: None) -> bool:
        if _the_changes_undone_in(published):
            raise AssertionError(
                f"Expected nothing to be published, got "
                f"{[event.kind for event in published]}."
            )

        return True

    return assertion


def _one_change_was_reported(published: list[IncidentEvent]) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        reported = _the_changes_undone_in(published)

        if len(reported) != 1:
            raise AssertionError(
                f"Expected one change to be reported, got [{len(reported)}]."
            )

        return True

    return assertion


def _the_report_says(published: list[IncidentEvent], detail: str) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        said = _the_changes_undone_in(published)[0].detail

        if said != detail:
            raise AssertionError(
                f"Expected the report to read [{detail!r}], got [{said!r}]."
            )

        return True

    return assertion


def _the_report_names(published: list[IncidentEvent],
                      outcome: Undone) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        reported = _the_changes_undone_in(published)[0].outcome

        if reported is not outcome:
            raise AssertionError(
                f"Expected the report to name [{outcome}], got [{reported}]."
            )

        return True

    return assertion


def _the_report_is_about(published: list[IncidentEvent],
                         flag: str) -> Assertion[None]:
    """The flag travels with the answer: an unwind reports several of these at
    once, and a reader has to be able to tell which is which."""
    def assertion(_unwound: None) -> bool:
        about = _the_changes_undone_in(published)[0].flag

        if about != flag:
            raise AssertionError(
                f"Expected the report to be about [{flag}], got [{about}]."
            )

        return True

    return assertion


def _both_changes_were_attempted(undo: MagicMock) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        if undo.call_count != 2:
            raise AssertionError(
                f"Expected both changes to be attempted, got [{undo.call_count}]."
            )

        return True

    return assertion


def _both_were_reported(published: list[IncidentEvent]) -> Assertion[None]:
    def assertion(_unwound: None) -> bool:
        reported = _the_changes_undone_in(published)

        if len(reported) != 2:
            raise AssertionError(
                f"Expected both attempts to be reported, got [{len(reported)}]."
            )

        return True

    return assertion


def _the_changes_undone_in(published: list[IncidentEvent]) -> list[ChangeUndone]:
    """Only the restores, in the order they were published.

    Read here rather than in five assertions: every claim below starts by
    holding these, and a filter written five times is five chances to disagree
    about what counts.
    """
    return [event for event in published if isinstance(event, ChangeUndone)]


def _restored(flag: str) -> UndoAttempt:
    return UndoAttempt(
        flag=flag, outcome=Undone.RESTORED, detail=f"flag [{flag}] was put back"
    )


def _an_undo_descriptor_for(flag: str, was_enabled: bool = True) -> UndoDescriptor:
    return UndoDescriptor(
        flag=flag,
        was_enabled=was_enabled,
        environment="production"
    )


def _an_incident_that_changed(*descriptors: UndoDescriptor) -> list[TakenAction]:
    return [_a_taken_action_carrying(descriptor) for descriptor in descriptors]


def _an_incident_whose_taken_action_carries_no_descriptor() -> list[TakenAction]:
    return [_a_taken_action_carrying(None)]


def _reading(recorded: list[TakenAction]) -> Callable[[str], list[TakenAction]]:
    """The incident's own changes, as the unwind asks for them."""
    def taken_actions_of(_incident_id: str) -> list[TakenAction]:
        return recorded

    return taken_actions_of


def _a_taken_action_carrying(undo_descriptor: UndoDescriptor | None) -> TakenAction:
    return TakenAction(
        id=new_id(),
        incident_id=_DONT_CARE_INCIDENT_ID,
        hypothesis_id=new_id(),
        type="revert-feature-flag",
        target="dont-care-flag",
        reversible=True,
        tier="write",
        undo_descriptor=undo_descriptor,
        outcome="dont care",
        taken_at=datetime.now(UTC),
        approved_by=None,
    )
