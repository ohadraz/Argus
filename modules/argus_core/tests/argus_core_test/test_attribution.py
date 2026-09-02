from __future__ import annotations

import pytest
from argus_core.attribution import changes_not_made_by
from argus_core.models.flag_change import FlagChange

"""Telling Argus's own flag changes from everybody else's.

The provider records who made each change, and once Argus starts retrying it is
one of the parties making them: it reverts a flag, the revert is recorded, and
the next look at "what recently changed" finds it. Without this, an agent that
identifies a culprit by asking what changed would eventually blame itself for
the change it made trying to fix the incident.
"""

AN_ACTOR = "Argus"
A_HUMAN = "admin"


@pytest.mark.unit
def test_a_change_argus_made_is_dropped() -> None:
    argus_own_change = a_flag_change(actor=AN_ACTOR)

    assert changes_not_made_by(AN_ACTOR, [argus_own_change]) == []


@pytest.mark.unit
def test_a_change_somebody_else_made_is_kept() -> None:
    somebody_elses_change = a_flag_change(actor=A_HUMAN)

    assert changes_not_made_by(AN_ACTOR, [somebody_elses_change]) == [
        somebody_elses_change
    ]


@pytest.mark.unit
def test_a_change_with_no_recorded_actor_is_kept() -> None:
    # The provider did not say who made it. That is not the same as saying
    # Argus made it, and discarding it would throw away real evidence on a
    # guess - the failure that matters here is dropping a human's change, not
    # keeping one of Argus's.
    a_change_from_nobody_in_particular = a_flag_change(actor=None)

    assert changes_not_made_by(AN_ACTOR, [a_change_from_nobody_in_particular]) == [
        a_change_from_nobody_in_particular
    ]


@pytest.mark.unit
def test_an_empty_actor_keeps_everything() -> None:
    # A deployment where Argus and its operators share one credential cannot
    # make this distinction at all. Filtering on an empty name would drop every
    # change with no actor recorded, which is the opposite of what not knowing
    # should do.
    dont_care_changes = [a_flag_change(actor=A_HUMAN), a_flag_change(actor=None)]

    assert changes_not_made_by("", dont_care_changes) == dont_care_changes


@pytest.mark.unit
def test_the_actor_is_matched_regardless_of_case() -> None:
    # The name is seeded in one repository and compared in another. Case
    # drifting between them must not quietly switch the filtering off, which is
    # the one failure this whole mechanism exists to prevent.
    a_change_recorded_in_another_case = a_flag_change(actor="argus")

    assert changes_not_made_by(AN_ACTOR, [a_change_recorded_in_another_case]) == []


@pytest.mark.unit
def test_the_remaining_changes_keep_their_order() -> None:
    # Callers read the last mention of a flag as its current state, so an
    # order this reshuffled would change which state gets put back.
    an_older_change = a_flag_change(flag="first", actor=A_HUMAN)
    argus_own_change = a_flag_change(flag="second", actor=AN_ACTOR)
    a_newer_change = a_flag_change(flag="third", actor=A_HUMAN)

    kept = changes_not_made_by(
        AN_ACTOR, [an_older_change, argus_own_change, a_newer_change]
    )

    assert kept == [an_older_change, a_newer_change]


def a_flag_change(flag: str = "some-flag", actor: str | None = None) -> FlagChange:
    """A recorded change whose only interesting property is who made it."""
    return FlagChange(
        flag=flag,
        enabled=True,
        occurred_at="2026-08-29T16:00:00Z",
        actor=actor,
    )
