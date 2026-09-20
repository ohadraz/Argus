"""The values an action is known by, and the outcomes it can come back with.

Two subjects, both about a shape a reader downstream has to be able to trust.

What an action *is*, for the purpose of asking whether it has been done before:
the kind and the thing it was done to, together. Asked at two timescales - the
gate asks it within one incident, memory asks it across incidents - and those
were two comparisons over loose strings until they were one type. Loose strings
is how memory came to compare half the pair the gate compares whole, and how a
model's prose about a symptom came to be stored where the name of a service
belonged (spec §11.2, §13).

And the spelling of an outcome no `Verdict` knows (spec §7.3, §13). `Verdict` is
a `StrEnum` and `UnreadVerdict` is a `str`, which is what lets the dashboard and
the postmortem interpolate either and show what the column holds. It is also why
one of them must not be able to hold the other's spelling:
`UnreadVerdict("confirmed")` would compare equal to `Verdict.CONFIRMED` and fail
every `isinstance` narrowing decided against it - read as a verdict where an
outcome is displayed, and absent where one is judged.

Nothing on the read path can make one, since a spelling a verdict has becomes
that verdict. A builder can, which is where this sort of value gets born and is
the whole of the defect `subject` was: a shape production cannot produce, green
in a test. So the type refuses it.
"""

from __future__ import annotations

import pytest
from argus_core.models import (
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ActionIdentity,
    FlagUndo,
    RestartService,
    RevertFeatureFlag,
    UnreadVerdict,
    Verdict,
    the_identity_of,
    the_identity_recorded,
)
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting

SOME_SPELLING_NO_VERDICT_HAS = "dissolved"
A_SPELLING_A_VERDICT_HAS = Verdict.CONFIRMED.value


@pytest.mark.unit
def test_the_identity_of_a_flag_revert_is_its_kind_and_its_flag() -> None:
    some_flag = "kuki-flag"

    Scenario() \
        .given(
            a_flag_revert := _a_revert_of(some_flag)
        ) \
        .when(lambda: the_identity_of(a_flag_revert)) \
        .then(_it_identifies(REVERT_FEATURE_FLAG, some_flag))


@pytest.mark.unit
def test_the_identity_of_a_restart_is_its_kind_and_its_service() -> None:
    some_service = "kuki-service"

    Scenario() \
        .given(
            a_restart := RestartService(service=some_service)
        ) \
        .when(lambda: the_identity_of(a_restart)) \
        .then(_it_identifies(RESTART_SERVICE, some_service))


@pytest.mark.unit
def test_the_same_thing_done_twice_is_the_same_identity() -> None:
    # What both askers are actually asking. Equality is the whole mechanism -
    # the gate counts how many of an incident's attempts match, and memory looks
    # a candidate up among the identities earlier incidents refuted.
    some_flag = "kuki-flag"

    Scenario() \
        .given(
            two_reverts_of_one_flag := (_a_revert_of(some_flag), _a_revert_of(some_flag))
        ) \
        .when(lambda: [the_identity_of(action) for action in two_reverts_of_one_flag]) \
        .then(_they_are_the_same_identity())


@pytest.mark.unit
def test_two_kinds_of_action_on_one_name_are_different_identities() -> None:
    # A service restarted and a flag put back are different experiments that
    # happen to share a name in the record. An identity that was the subject
    # alone would let a refuted restart demote a flag revert, and would let the
    # cap on one kind spend the other's budget.
    some_name_both_could_carry = "checkout"

    Scenario() \
        .given(
            a_revert_and_a_restart := (
                _a_revert_of(some_name_both_could_carry),
                RestartService(service=some_name_both_could_carry)
            )
        ) \
        .when(lambda: [the_identity_of(action) for action in a_revert_and_a_restart]) \
        .then(_they_are_different_identities())


@pytest.mark.unit
def test_an_identity_can_be_looked_up_among_others() -> None:
    # Both askers hold a collection of them and ask whether one is in it, so the
    # value has to be hashable. A mutable model would be a runtime error at the
    # one call site that matters and nowhere else.
    some_flag = "kuki-flag"

    Scenario() \
        .given(
            an_identity := the_identity_of(_a_revert_of(some_flag))
        ) \
        .when(lambda: {an_identity: "what came of it"}) \
        .then(_it_is_found_under(the_identity_of(_a_revert_of(some_flag))))


@pytest.mark.unit
def test_an_identity_can_be_read_back_off_a_stored_row() -> None:
    # The other way one is built, and the one that starts from text. A row's
    # kind is a column, so what comes back out of the table is a `str` - and
    # the record long-term memory compares was written from exactly that.
    some_service = "kuki-service"

    Scenario() \
        .given(what_the_row_holds := (RESTART_SERVICE, some_service)) \
        .when(lambda: the_identity_recorded(*what_the_row_holds)) \
        .then(_the_row_identifies(RESTART_SERVICE, some_service))


@pytest.mark.unit
def test_a_row_of_a_kind_this_version_cannot_read_identifies_nothing() -> None:
    # An incident old enough can hand back a kind some version since removed.
    # The row is history and still has to come out of the table, so it is
    # passed over rather than refused - nothing later could match it anyway,
    # because matching it means proposing an action of a kind this Argus no
    # longer has. Refusing it instead would fail the close of an incident
    # somebody is already reading.
    a_kind_nobody_has_any_more = "adjust-the-thermostat"

    Scenario() \
        .given(what_the_row_holds := (a_kind_nobody_has_any_more, "kuki-service")) \
        .when(lambda: the_identity_recorded(*what_the_row_holds)) \
        .then(_the_row_cannot_be_identified())


@pytest.mark.unit
def test_an_outcome_no_verdict_spells_keeps_the_spelling_it_was_read_with() -> None:
    # The raw text, because every destination that shows an outcome shows this
    # one too. A third state that dropped what it could not read would tell an
    # operator less than the column already holds, and leave an escalation
    # unable to say what stopped it.
    Scenario() \
        .given(
            SOME_SPELLING_NO_VERDICT_HAS
        ) \
        .when(
            lambda: UnreadVerdict(SOME_SPELLING_NO_VERDICT_HAS)
        ) \
        .then(all_of(
            _it_is_spelled(SOME_SPELLING_NO_VERDICT_HAS),
            _it_is_no_verdict()
        ))


@pytest.mark.unit
def test_an_outcome_a_verdict_does_spell_is_refused() -> None:
    Scenario() \
        .given(
            A_SPELLING_A_VERDICT_HAS
        ) \
        .when(
            attempting(lambda: UnreadVerdict(A_SPELLING_A_VERDICT_HAS))
        ) \
        .then(all_of(
            an_error_was_raised(ValueError),
            _it_complains_about(A_SPELLING_A_VERDICT_HAS)
        ))


def _a_revert_of(flag: str) -> RevertFeatureFlag:
    return RevertFeatureFlag(
        flag=flag,
        enabled=False,
        undo_descriptor=FlagUndo(flag=flag, was_enabled=True)
    )


def _it_identifies(action_type: str, subject: str) -> Assertion[ActionIdentity]:
    def assertion(identity: ActionIdentity) -> bool:
        if (identity.action_type, identity.subject) != (action_type, subject):
            raise AssertionError(
                f"Expected an identity of [{action_type}] on [{subject}], got "
                f"[{identity.action_type}] on [{identity.subject}]."
            )

        return True

    return assertion


def _the_row_identifies(action_type: str,
                        subject: str) -> Assertion[ActionIdentity | None]:
    def assertion(identity: ActionIdentity | None) -> bool:
        if identity is None:
            raise AssertionError(
                f"Expected an identity of [{action_type}] on [{subject}], the "
                f"row could not be read at all."
            )

        return _it_identifies(action_type, subject)(identity)

    return assertion


def _the_row_cannot_be_identified() -> Assertion[ActionIdentity | None]:
    def assertion(identity: ActionIdentity | None) -> bool:
        if identity is not None:
            raise AssertionError(
                f"Expected a kind this version cannot read to identify "
                f"nothing, got [{identity}]."
            )

        return True

    return assertion


def _they_are_the_same_identity() -> Assertion[list[ActionIdentity]]:
    def assertion(identities: list[ActionIdentity]) -> bool:
        first, second = identities
        if first != second:
            raise AssertionError(
                f"Expected [{first}] and [{second}] to be one identity."
            )

        return True

    return assertion


def _they_are_different_identities() -> Assertion[list[ActionIdentity]]:
    def assertion(identities: list[ActionIdentity]) -> bool:
        first, second = identities
        if first == second:
            raise AssertionError(
                f"Expected [{first}] and [{second}] to be two identities, and "
                f"they compare equal."
            )

        return True

    return assertion


def _it_is_found_under(identity: ActionIdentity) -> Assertion[dict[ActionIdentity, str]]:
    def assertion(kept: dict[ActionIdentity, str]) -> bool:
        if identity not in kept:
            raise AssertionError(
                f"Expected [{identity}] to be found among {list(kept)}."
            )

        return True

    return assertion


def _it_is_spelled(spelling: str) -> Assertion[UnreadVerdict]:
    def assertion(outcome: UnreadVerdict) -> bool:
        if outcome != spelling or f"{outcome}" != spelling:
            raise AssertionError(
                f"Expected an outcome spelled [{spelling}], got [{outcome}]."
            )

        return True

    return assertion


def _it_is_no_verdict() -> Assertion[UnreadVerdict]:
    def assertion(outcome: UnreadVerdict) -> bool:
        if isinstance(outcome, Verdict):
            raise AssertionError(
                f"Expected [{outcome}] to be no `Verdict`, and it is [{outcome!r}] - "
                f"so every branch narrowing on one would take it."
            )

        return True

    return assertion


def _it_complains_about(spelling: str) -> Assertion[Exception | None]:
    def assertion(error: Exception | None) -> bool:
        if spelling not in str(error):
            raise AssertionError(
                f"Expected the refusal to name [{spelling}], and it said: {error}."
            )

        return True

    return assertion
