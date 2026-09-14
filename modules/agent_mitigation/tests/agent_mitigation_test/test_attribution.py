"""Telling Argus's own flag changes from everybody else's.

The provider records who made each change, and once Argus starts retrying it is
one of the parties making them: it reverts a flag, the revert is recorded, and
the next look at "what recently changed" finds it. Without this, an agent that
identifies a culprit by asking what changed would eventually blame itself for
the change it made trying to fix the incident.
"""
from __future__ import annotations

import pytest
from agent_mitigation.attribution import change_by_actor_to, changes_not_made_by
from argus_core.models import FlagChange
from argus_testkit import Assertion, Scenario

AN_ACTOR = "Argus"
A_HUMAN = "admin"

SOME_FLAG = "monthly-spend-feature"


@pytest.mark.unit
def test_a_change_argus_made_is_dropped() -> None:
    Scenario() \
        .given(
            argus_own_change := a_flag_change(actor=AN_ACTOR)
        ) \
        .when(
            lambda: changes_not_made_by(AN_ACTOR, [argus_own_change])
        ) \
        .then(
            _the_changes_kept_are()
        )


@pytest.mark.unit
def test_a_change_somebody_else_made_is_kept() -> None:
    Scenario() \
        .given(
            somebody_elses_change := a_flag_change(actor=A_HUMAN)
        ) \
        .when(
            lambda: changes_not_made_by(AN_ACTOR, [somebody_elses_change])
        ) \
        .then(
            _the_changes_kept_are(somebody_elses_change)
        )


@pytest.mark.unit
def test_a_change_with_no_recorded_actor_is_kept() -> None:
    # The provider did not say who made it. That is not the same as saying
    # Argus made it, and discarding it would throw away real evidence on a
    # guess - the failure that matters here is dropping a human's change, not
    # keeping one of Argus's.
    Scenario() \
        .given(
            a_change_from_nobody_in_particular := a_flag_change(actor=None)
        ) \
        .when(
            lambda: changes_not_made_by(AN_ACTOR, [a_change_from_nobody_in_particular])
        ) \
        .then(
            _the_changes_kept_are(a_change_from_nobody_in_particular)
        )


@pytest.mark.unit
def test_an_empty_actor_keeps_everything() -> None:
    # A deployment where Argus and its operators share one credential cannot
    # make this distinction at all. Filtering on an empty name would drop every
    # change with no actor recorded, which is the opposite of what not knowing
    # should do.
    Scenario() \
        .given(
            dont_care_changes := [a_flag_change(actor=A_HUMAN), a_flag_change(actor=None)]
        ) \
        .when(
            lambda: changes_not_made_by("", dont_care_changes)
        ) \
        .then(
            _the_changes_kept_are(*dont_care_changes)
        )


@pytest.mark.unit
def test_the_actor_is_matched_regardless_of_case() -> None:
    # The name is seeded in one repository and compared in another. Case
    # drifting between them must not quietly switch the filtering off, which is
    # the one failure this whole mechanism exists to prevent.
    Scenario() \
        .given(
            a_change_recorded_in_another_case := a_flag_change(actor="argus")
        ) \
        .when(
            lambda: changes_not_made_by(AN_ACTOR, [a_change_recorded_in_another_case])
        ) \
        .then(
            _the_changes_kept_are()
        )


@pytest.mark.unit
def test_the_remaining_changes_keep_their_order() -> None:
    # Callers read the last mention of a flag as its current state, so an
    # order this reshuffled would change which state gets put back.
    an_older_change = a_flag_change(flag="first", actor=A_HUMAN)
    argus_own_change = a_flag_change(flag="second", actor=AN_ACTOR)
    a_newer_change = a_flag_change(flag="third", actor=A_HUMAN)

    Scenario() \
        .given(
            an_older_change, argus_own_change, a_newer_change
        ) \
        .when(
            lambda: changes_not_made_by(
                AN_ACTOR, [an_older_change, argus_own_change, a_newer_change]
            )
        ) \
        .then(
            _the_changes_kept_are(an_older_change, a_newer_change)
        )


@pytest.mark.unit
def test_argus_own_change_to_the_flag_is_found() -> None:
    # The question a resumed walk asks: did the change I was making land? Asked
    # of the provider's log, which is the only place that knows.
    Scenario() \
        .given(
            argus_own_change := a_flag_change(flag=SOME_FLAG, actor=AN_ACTOR)
        ) \
        .when(
            lambda: change_by_actor_to(SOME_FLAG, AN_ACTOR, [argus_own_change])
        ) \
        .then(
            _the_answer_was(True)
        )


@pytest.mark.unit
def test_a_change_to_another_flag_is_not_this_one() -> None:
    Scenario() \
        .given(
            argus_change_elsewhere := a_flag_change(flag="another-flag", actor=AN_ACTOR)
        ) \
        .when(
            lambda: change_by_actor_to(SOME_FLAG, AN_ACTOR, [argus_change_elsewhere])
        ) \
        .then(
            _the_answer_was(False)
        )


@pytest.mark.unit
def test_somebody_elses_change_to_the_flag_is_not_argus_own() -> None:
    # A human turning the same flag off is not evidence that Argus's action
    # landed - and acting on it as though it were would leave the incident
    # crediting itself with somebody else's fix.
    Scenario() \
        .given(
            somebody_elses_change := a_flag_change(flag=SOME_FLAG, actor=A_HUMAN)
        ) \
        .when(
            lambda: change_by_actor_to(SOME_FLAG, AN_ACTOR, [somebody_elses_change])
        ) \
        .then(
            _the_answer_was(False)
        )


@pytest.mark.unit
def test_an_unattributable_deployment_cannot_answer_at_all() -> None:
    # Argus and its operators sharing one credential means the provider cannot
    # say who acted. `None`, not `False`: "I could not have been told" is not
    # "it did not happen", and the caller does different things with each.
    Scenario() \
        .given(
            dont_care_change := a_flag_change(flag=SOME_FLAG, actor=None)
        ) \
        .when(
            lambda: change_by_actor_to(SOME_FLAG, "", [dont_care_change])
        ) \
        .then(
            _the_answer_was(None)
        )


def _the_changes_kept_are(*expected: FlagChange) -> Assertion[list[FlagChange]]:
    """Exactly these changes, in this order.

    Order is asserted rather than membership because callers read the last
    mention of a flag as its current state: a filter that reshuffled its input
    would change which state gets put back, and a set comparison would pass.
    """
    def assertion(kept: list[FlagChange]) -> bool:
        if kept != list(expected):
            raise AssertionError(
                f"Expected the changes {[change.flag for change in expected]} to be "
                f"kept, got {[change.flag for change in kept]}."
            )

        return True

    return assertion


def _the_answer_was(expected: bool | None) -> Assertion[bool | None]:
    """That the question was answered with this, identity and all.

    `is` rather than `==`, because `None` and `False` are the whole distinction
    here - "nobody can say" against "it did not happen" - and they compare equal
    to nothing but themselves only under identity.
    """
    def assertion(answer: bool | None) -> bool:
        if answer is not expected:
            raise AssertionError(f"Expected [{expected}], got [{answer}].")

        return True

    return assertion


def a_flag_change(flag: str = "some-flag", actor: str | None = None) -> FlagChange:
    """A recorded change whose only interesting property is who made it."""
    return FlagChange(
        flag=flag,
        enabled=True,
        occurred_at="2026-08-29T16:00:00Z",
        actor=actor,
    )
