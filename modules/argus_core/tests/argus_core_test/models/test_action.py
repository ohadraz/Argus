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

from typing import get_args

import pytest
from argus_core.models import (
    CACHE,
    DEPLOYMENT_PLATFORM,
    DISCARD_CACHE_ENTRIES,
    FLAG_PROVIDER,
    PIN_AUTOSCALER,
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    SCALE_OUT,
    ActionIdentity,
    ActionType,
    DiscardCacheEntries,
    FlagUndo,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
    ScaleOut,
    UnreadVerdict,
    Verdict,
    changes_something_persistent,
    leaves_something_to_put_back,
    reports_what_it_changed,
    the_actions_through,
    the_direction_of,
    the_identity_of,
    the_identity_recorded,
    the_platform_of,
)
from argus_testkit import Assertion, Scenario, all_of, an_error_was_raised, attempting
from pydantic import ValidationError

SOME_SPELLING_NO_VERDICT_HAS = "dissolved"
A_SPELLING_A_VERDICT_HAS = Verdict.CONFIRMED.value
SOME_APPLICATION = "io-shop"


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


@pytest.mark.unit
def test_the_identity_of_a_rollback_is_its_kind_and_its_application() -> None:
    Scenario() \
        .given(
            a_rollback := _a_rollback_of(SOME_APPLICATION)
        ) \
        .when(lambda: the_identity_of(a_rollback)) \
        .then(_it_identifies(ROLL_BACK_DEPLOYMENT, SOME_APPLICATION))


@pytest.mark.unit
def test_a_rollback_and_a_restart_on_one_name_are_different_identities() -> None:
    # Both act on the same deployment and they are not the same evidence: a
    # restart that did not help says nothing about whether the configuration
    # is wrong, and the gate counts them separately for that reason.
    Scenario() \
        .given([
            _a_rollback_of(SOME_APPLICATION),
            RestartService(service=SOME_APPLICATION)
        ]) \
        .when(lambda: [
            the_identity_of(_a_rollback_of(SOME_APPLICATION)),
            the_identity_of(RestartService(service=SOME_APPLICATION))
        ]) \
        .then(_they_are_different_identities())


@pytest.mark.unit
def test_a_rollback_has_no_direction_to_report() -> None:
    # A flag is set on or off and which of those happened is half the
    # sentence. A rollback has one thing it does, and reporting it as having
    # moved something to `true` would be a field invented to keep a shape.
    Scenario() \
        .given(
            a_rollback := _a_rollback_of(SOME_APPLICATION)
        ) \
        .when(lambda: the_direction_of(a_rollback)) \
        .then(_it_has_no_direction())


@pytest.mark.unit
def test_a_rollback_leaves_something_a_withdrawal_has_to_put_back() -> None:
    # Unlike a restart. The row's own column is what tells a descriptor that
    # is missing from a kind that leaves nothing behind - which is fine - from
    # one missing on a kind that does, which is a change nobody accounted for.
    Scenario() \
        .given(ROLL_BACK_DEPLOYMENT) \
        .when(lambda: leaves_something_to_put_back(ROLL_BACK_DEPLOYMENT)) \
        .then(_it_leaves_something_to_put_back(True))


@pytest.mark.unit
def test_a_restart_leaves_nothing_to_put_back() -> None:
    Scenario() \
        .given(RESTART_SERVICE) \
        .when(lambda: leaves_something_to_put_back(RESTART_SERVICE)) \
        .then(_it_leaves_something_to_put_back(False))


@pytest.mark.unit
def test_the_identity_of_a_scale_out_is_its_kind_and_its_application() -> None:
    Scenario() \
        .given(
            a_scale_out := _a_scale_out_of(SOME_APPLICATION)
        ) \
        .when(lambda: the_identity_of(a_scale_out)) \
        .then(_it_identifies(SCALE_OUT, SOME_APPLICATION))


@pytest.mark.unit
def test_a_scale_out_carries_the_application_and_no_count() -> None:
    # The count it replaces is live state only the write tier can read, so an
    # action naming an absolute figure would be asserting what the deployment is
    # running now - a fact nothing that proposes one has in front of it.
    Scenario() \
        .given(
            a_scale_out := _a_scale_out_of(SOME_APPLICATION)
        ) \
        .when(lambda: set(a_scale_out.model_dump())) \
        .then(_it_carries_no_replica_count())


@pytest.mark.unit
def test_a_scale_out_and_a_rollback_on_one_name_are_different_identities() -> None:
    # Both act on the same deployment and neither is evidence about the other: a
    # rollback that did not help says nothing about whether the shop is too small
    # for its traffic, and the gate counts them separately for that reason.
    Scenario() \
        .given([
            _a_scale_out_of(SOME_APPLICATION),
            _a_rollback_of(SOME_APPLICATION)
        ]) \
        .when(lambda: [
            the_identity_of(_a_scale_out_of(SOME_APPLICATION)),
            the_identity_of(_a_rollback_of(SOME_APPLICATION))
        ]) \
        .then(_they_are_different_identities())


@pytest.mark.unit
def test_a_scale_out_has_no_direction_to_report() -> None:
    Scenario() \
        .given(
            a_scale_out := _a_scale_out_of(SOME_APPLICATION)
        ) \
        .when(lambda: the_direction_of(a_scale_out)) \
        .then(_it_has_no_direction())


@pytest.mark.unit
def test_a_scale_out_leaves_something_a_withdrawal_has_to_put_back() -> None:
    # Two things, in fact - the count and the platform's own reconciliation - and
    # the kind is what says a row with no descriptor against it is a change
    # nobody accounted for.
    Scenario() \
        .given(SCALE_OUT) \
        .when(lambda: leaves_something_to_put_back(SCALE_OUT)) \
        .then(_it_leaves_something_to_put_back(True))


@pytest.mark.unit
def test_the_four_actions_that_reach_the_estate_through_the_deploy_platform_share_it() -> None:
    # The fact the walk narrows itself on. A platform that is not answering has
    # taken all four away at once, which is a different thing from one action
    # failing - and it is only knowable in advance because the kind says which
    # platform it would act through, without the action having been tried.
    Scenario() \
        .given([RESTART_SERVICE, ROLL_BACK_DEPLOYMENT, SCALE_OUT, PIN_AUTOSCALER]) \
        .when(lambda: [
            the_platform_of(RESTART_SERVICE),
            the_platform_of(ROLL_BACK_DEPLOYMENT),
            the_platform_of(SCALE_OUT),
            the_platform_of(PIN_AUTOSCALER)
        ]) \
        .then(_they_all_act_through(DEPLOYMENT_PLATFORM))


@pytest.mark.unit
def test_a_flag_revert_acts_through_something_else() -> None:
    # The half that makes the test above worth having. If every kind named one
    # platform, a platform that went down would take the whole declared set with
    # it and there would be nothing to narrow to - so what this holds is that
    # one action survives it.
    Scenario() \
        .given(REVERT_FEATURE_FLAG) \
        .when(lambda: the_platform_of(REVERT_FEATURE_FLAG)) \
        .then(all_of(
            _it_acts_through(FLAG_PROVIDER),
            _it_does_not_act_through(DEPLOYMENT_PLATFORM)
        ))


@pytest.mark.unit
def test_the_deployment_platform_carries_four_of_the_five_actions() -> None:
    # What an escalation and a narrated line both have to say: not that a
    # platform is down, but what it took away. A reader told only the platform's
    # name has to go and look up which of Argus's actions went with it, which is
    # the thing saying it at all exists to prevent.
    Scenario() \
        .given(DEPLOYMENT_PLATFORM) \
        .when(lambda: the_actions_through(DEPLOYMENT_PLATFORM)) \
        .then(_they_are([
            RESTART_SERVICE, ROLL_BACK_DEPLOYMENT, SCALE_OUT, PIN_AUTOSCALER
        ]))


@pytest.mark.unit
def test_the_flag_provider_carries_the_one_action_that_survives_it() -> None:
    # The half that makes the other worth having. Four and one, so a walk that
    # loses the deployment platform still has somewhere to go - and a reader of
    # the escalation can see that what is left is the flag revert rather than
    # nothing.
    Scenario() \
        .given(FLAG_PROVIDER) \
        .when(lambda: the_actions_through(FLAG_PROVIDER)) \
        .then(_they_are([REVERT_FEATURE_FLAG]))


@pytest.mark.unit
def test_every_kind_is_accounted_for_by_one_of_the_three_platforms() -> None:
    # The claim that keeps the lists above from drifting apart as kinds are
    # added. A seventh mitigation appearing in none of them would be an action
    # nothing says is unavailable when its platform goes down, and nothing here
    # would fail - the lists would simply be quietly incomplete.
    #
    # Three rather than two since the cache arrived, and the sum is what is
    # asserted rather than each list's length: what matters is that no kind is
    # unaccounted for, not how they happen to be distributed today.
    Scenario() \
        .given([DEPLOYMENT_PLATFORM, FLAG_PROVIDER, CACHE]) \
        .when(lambda: sorted(
            the_actions_through(DEPLOYMENT_PLATFORM)
            + the_actions_through(FLAG_PROVIDER)
            + the_actions_through(CACHE)
        )) \
        .then(_they_are(sorted([
            REVERT_FEATURE_FLAG, RESTART_SERVICE, ROLL_BACK_DEPLOYMENT,
            SCALE_OUT, PIN_AUTOSCALER, DISCARD_CACHE_ENTRIES
        ])))


@pytest.mark.unit
def test_the_identity_of_a_discard_is_its_kind_and_its_service() -> None:
    # The keys are deliberately not part of it. Identity answers whether this
    # has been done before, and the entries a check finds stale differ between
    # one run and the next - so an identity carrying them would make every
    # attempt a new one, and the cap that stops Argus discarding over and over
    # would never be reached.
    Scenario() \
        .given(
            a_discard := _a_discard_of(SOME_APPLICATION)
        ) \
        .when(lambda: the_identity_of(a_discard)) \
        .then(_it_identifies(DISCARD_CACHE_ENTRIES, SOME_APPLICATION))


@pytest.mark.unit
def test_a_discard_naming_no_entries_is_refused() -> None:
    # An action that would reach the cache and remove nothing. Refused here
    # rather than tolerated, because its count would come back zero and a zero
    # is indistinguishable from entries somebody else had already discarded -
    # so the attempt would be confirmed by a receipt saying nothing happened.
    Scenario() \
        .given(SOME_APPLICATION) \
        .when(
            attempting(
                lambda: DiscardCacheEntries(service=SOME_APPLICATION, keys=())
            )
        ) \
        .then(an_error_was_raised(ValidationError))


@pytest.mark.unit
def test_a_discard_leaves_nothing_to_put_back() -> None:
    # Like a restart and unlike the three that restore something. Nothing was
    # lost: the entries were a copy of records that never moved, and whatever
    # reads one next works it out again. An undo descriptor here would promise
    # to write the stale figures back, which is a promise to recreate the
    # incident.
    Scenario() \
        .given(DISCARD_CACHE_ENTRIES) \
        .when(lambda: leaves_something_to_put_back(DISCARD_CACHE_ENTRIES)) \
        .then(_it_leaves_something_to_put_back(False))


@pytest.mark.unit
def test_a_discard_reaches_the_estate_through_neither_platform_above() -> None:
    # The first action that is not a call to a control plane. No control plane
    # offers this one: a platform's built-in actions reach a workload's
    # lifecycle and its size, and none of them reaches what a cache holds.
    #
    # Which is why it needs a platform of its own rather than being filed under
    # the deployment platform for tidiness. A walk that loses the platform
    # passes over every candidate on it, and a discard filed there would be
    # abandoned over an outage that never touched the cache it acts on.
    Scenario() \
        .given(DISCARD_CACHE_ENTRIES) \
        .when(lambda: the_platform_of(DISCARD_CACHE_ENTRIES)) \
        .then(all_of(
            _it_acts_through(CACHE),
            _it_does_not_act_through(DEPLOYMENT_PLATFORM)
        ))


@pytest.mark.unit
def test_a_discard_has_no_direction_to_report() -> None:
    # Like a restart, a rollback and a scale-out, and unlike the flag revert.
    # There is one thing a discard does - the entries are gone - and no second
    # state it could have been moved to instead. A direction invented here would
    # be a field kept to preserve a shape, and it would be read out in the line
    # the incident is narrated as.
    Scenario() \
        .given(
            a_discard := _a_discard_of(SOME_APPLICATION)
        ) \
        .when(lambda: the_direction_of(a_discard)) \
        .then(_it_has_no_direction())


@pytest.mark.unit
def test_only_the_discard_answers_with_what_it_changed() -> None:
    # What separates the one action that can be confirmed by its own answer from
    # the five that cannot. A discard returns how many entries it removed, which
    # is the store stating they are gone; the others answer that a request was
    # accepted, and what happened next has to be watched for.
    #
    # Asserted over all six rather than of the discard alone, because the claim
    # is that it is the only one. A later action that quietly reported something
    # would otherwise gain a confirmation nobody reasoned about.
    Scenario() \
        .given(every_kind := get_args(ActionType.__value__)) \
        .when(lambda: [
            kind for kind in every_kind if reports_what_it_changed(kind)
        ]) \
        .then(_they_are([DISCARD_CACHE_ENTRIES]))


@pytest.mark.unit
def test_every_action_but_the_restart_changes_something_persistent() -> None:
    # The fact neither predicate beside this one carries, and the one that tells
    # two silences apart. A row with no undo descriptor against it is a restart,
    # which changed nothing and so has nothing to put back, or a discard, which
    # changed something and owes nothing back because the figures were a copy of
    # records it never touched. Those want different sentences, and
    # `leaves_something_to_put_back` is false for both of them.
    #
    # Named for the restart's character rather than the discard's, because the
    # restart is the only member that makes it false. A predicate spelled as
    # owing an undo would be the neighbouring set with the restart flipped - a
    # synonym for the thing beside it whose one distinguishing answer is wrong,
    # and the restart's own case would then read as a change nobody accounted
    # for.
    #
    # Asserted over all six rather than of the restart alone, because the claim
    # is that it is the only one. A seventh kind that changed nothing would
    # otherwise inherit the discard's sentence.
    Scenario() \
        .given(every_kind := get_args(ActionType.__value__)) \
        .when(lambda: [
            kind for kind in every_kind if changes_something_persistent(kind)
        ]) \
        .then(_the_kinds_are(
            "change something persistent",
            [
                REVERT_FEATURE_FLAG, ROLL_BACK_DEPLOYMENT, SCALE_OUT,
                PIN_AUTOSCALER, DISCARD_CACHE_ENTRIES
            ]
        ))


def _the_kinds_are(description: str, expected: list[str]) -> Assertion[list[str]]:
    """Which kinds satisfy a predicate, named in full.

    The description is the predicate in words, because one assertion serves
    several of these and a failure saying only "the kinds" would leave a reader
    comparing two lists with nothing to say what either is a list of.

    Order compared as well as membership, because the filter preserves the
    union's own declaration order: a list that comes back reordered means the
    union was reordered, which is worth being told about rather than passed
    over.
    """
    def assertion(named: list[str]) -> bool:
        if named != expected:
            raise AssertionError(
                f"Expected the kinds that {description} to be {expected}, and "
                f"they are {named}."
            )

        return True

    return assertion


def _it_carries_no_replica_count() -> Assertion[set[str]]:
    def assertion(fields: set[str]) -> bool:
        counts = {field for field in fields if "replica" in field}

        if counts:
            raise AssertionError(
                f"Expected a scale-out to name the application alone, and it "
                f"carries {sorted(counts)} - a figure whatever proposed it "
                f"could not have known."
            )

        return True

    return assertion


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


def _a_rollback_of(application: str) -> RollBackDeployment:
    return RollBackDeployment(application=application)


def _a_scale_out_of(application: str) -> ScaleOut:
    return ScaleOut(application=application)


def _it_has_no_direction() -> Assertion[bool | None]:
    def assertion(direction: bool | None) -> bool:
        if direction is not None:
            raise AssertionError(
                f"Expected an action with no direction to move in, and it "
                f"reported [{direction}]."
            )

        return True

    return assertion


def _it_leaves_something_to_put_back(expected: bool) -> Assertion[bool]:
    def assertion(leaves: bool) -> bool:
        if leaves != expected:
            raise AssertionError(
                f"Expected leaving something to put back to be [{expected}], "
                f"and it was [{leaves}]."
            )

        return True

    return assertion


def _it_acts_through(platform: str) -> Assertion[str]:
    def assertion(named: str) -> bool:
        if named != platform:
            raise AssertionError(
                f"Expected the action to act through [{platform}], and it acts "
                f"through [{named}]."
            )

        return True

    return assertion


def _it_does_not_act_through(platform: str) -> Assertion[str]:
    """Said separately from what it does act through, and not redundant with it.

    The two would be one assertion if there were two platforms for ever. What
    this catches is the day a third is added and the flag revert is quietly
    given the deployment platform's name by a mapping that grew a default.
    """
    def assertion(named: str) -> bool:
        if named == platform:
            raise AssertionError(
                f"Expected the action not to act through [{platform}], and it "
                f"does - so nothing survives that platform going down."
            )

        return True

    return assertion


def _they_all_act_through(platform: str) -> Assertion[list[str]]:
    """Every kind named, and named the same.

    One assertion over the four rather than four tests, because what is claimed
    is not that each has a platform - it is that they share one. A walk passes
    over the rest of a platform's candidates by comparing what it derives for
    each against what failed, and four kinds that each named a platform of their
    own would pass four separate assertions and narrow nothing.
    """
    def assertion(named: list[str]) -> bool:
        wrong = sorted({one for one in named if one != platform})

        if wrong:
            raise AssertionError(
                f"Expected all four to act through [{platform}], and "
                f"{wrong} was named instead."
            )

        return True

    return assertion


def _they_are(expected: list[str]) -> Assertion[list[str]]:
    """The kinds named, and named in full.

    Order compared as well as membership, because this list is read out to a
    person in an escalation and in a narrated line: a set would let the sentence
    reorder itself between two runs of the same incident, which reads as two
    different facts.
    """
    def assertion(named: list[str]) -> bool:
        if named != expected:
            raise AssertionError(
                f"Expected the actions through that platform to be {expected}, "
                f"and they are {named}."
            )

        return True

    return assertion


def _a_discard_of(service: str,
                  keys: tuple[str, ...] = ("io-shop:summary:shopper-1",)
                  ) -> DiscardCacheEntries:
    """A discard of named entries, with a key that looks like a real one.

    The key is spelled as the store spells it rather than as something short,
    because every claim about this action is about carrying addresses faithfully
    and a placeholder would make the one mistake that matters invisible.
    """
    return DiscardCacheEntries(service=service, keys=keys)
