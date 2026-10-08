"""Which explanation on the list is worth an experiment, and what would be done.

The question two nodes share - the investigation choosing where to start, and
the walk choosing where to go after a refutation - so it is asked here once
rather than twice through its callers. What those callers do with the answer is
their own subject; this is only about which candidate comes back.

Two things disqualify one, and neither is confidence. A candidate that named no
cause has nothing to change on its account, and a candidate the walk would
answer with an action it has already taken and undone would be the same
experiment run twice. Everything else on the list is worth trying, however far
down it sits.

The action, not the candidate's own words. What a model calls a leak is prose
about a symptom, so a restart addressed to the alert's service was invisible to
a comparison over subjects - and the cases below say so twice over: once where
two candidates worded nothing alike are the same experiment, and once where one
subject spelled two ways is two different ones.

What an action is worked out from is built here too, once for every node that
asks: the alert's service and keys beside the round's two histories, or nothing
at all where the flag history could not be read.
"""

from __future__ import annotations

import pytest
from argus_core.models import (
    DEPLOYMENT_PLATFORM,
    ActionIdentity,
    Alert,
    Attempt,
    ChangeEvent,
    Circumstances,
    FlagChange,
    Hypothesis,
    RecordedPlacement,
    WhatWouldBeTried,
)
from argus_testkit import Assertion, Scenario, all_of
from orchestrator.walk.candidates import (
    the_circumstances,
    the_next_worth_trying,
    what_each_would_do,
)

from orchestrator_test.framework.builders import (
    a_candidate_blaming,
    a_corruption_blamed_on,
    a_deployment,
    a_determined_hypothesis,
    a_divergence_blamed_on,
    a_leak_blamed_on,
    a_placement,
    a_random_id,
    an_undetermined_hypothesis,
    discarding,
    putting_back,
    restarting,
    rolling_back,
)

SOME_FLAG = "monthly-spend-feature"
ANOTHER_FLAG = "legacy-checkout-fallback"
SOME_SERVICE = "io-shop"
ANOTHER_SERVICE = "io-shop-payments"
DONT_CARE_MOMENT = "2026-09-10T09:12:00+00:00"
DONT_CARE_ALERT_NAME = "HighErrorRate"

type Chosen = tuple[int, Hypothesis] | None


@pytest.mark.unit
def test_the_first_candidate_worth_an_experiment_is_the_one_taken_up() -> None:
    some_incident_id = a_random_id()
    some_best_answer = a_determined_hypothesis(some_incident_id)

    Scenario() \
        .given(
            some_candidates := _answered_by_a_flag_each(
                [some_best_answer, a_determined_hypothesis(some_incident_id)]
            )
        ) \
        .when(
            lambda: the_next_worth_trying(some_candidates, [], start=0)
        ) \
        .then(all_of(
            _the_candidate_taken_up_is(some_best_answer),
            _it_sits_at(0))
        )


@pytest.mark.unit
def test_a_candidate_naming_no_cause_is_passed_over() -> None:
    # "I found no cause" names nothing to change, which is a different answer
    # from being unsure which of several it is. Acting on it would mean changing
    # production with no hypothesis behind the change at all.
    some_incident_id = a_random_id()
    some_candidate_that_named_something = a_determined_hypothesis(some_incident_id)

    Scenario() \
        .given(
            some_candidates := _answered_by_a_flag_each(
                [an_undetermined_hypothesis(some_incident_id),
                 some_candidate_that_named_something]
            )
        ) \
        .when(
            lambda: the_next_worth_trying(some_candidates, [], start=0)
        ) \
        .then(all_of(
            _the_candidate_taken_up_is(some_candidate_that_named_something),
            _it_sits_at(1))
        )


@pytest.mark.unit
def test_an_action_already_taken_disqualifies_the_candidate_that_would_repeat_it() -> None:
    # The same flag was put back earlier in this incident and the service did
    # not recover. Doing it again would be running the experiment that has
    # already been run, against a world that answered once.
    some_incident_id = a_random_id()
    some_candidate_blaming_something_else = a_candidate_blaming(some_incident_id,
                                                                 ANOTHER_FLAG)

    Scenario() \
        .given(
            some_candidates := [
                _a_candidate_answered_by(
                    a_candidate_blaming(some_incident_id, SOME_FLAG),
                    putting_back(SOME_FLAG)
                ),
                _a_candidate_answered_by(some_candidate_blaming_something_else,
                                         putting_back(ANOTHER_FLAG))
            ]
        ) \
        .when(
            lambda: the_next_worth_trying(some_candidates,
                                          [_an_attempt_to(putting_back(SOME_FLAG))],
                                          start=0)
        ) \
        .then(all_of(
            _the_candidate_taken_up_is(some_candidate_blaming_something_else),
            _it_sits_at(1))
        )


@pytest.mark.unit
def test_a_restart_already_taken_disqualifies_a_candidate_worded_nothing_like_it() -> None:
    # The gap the identity closed. Two rounds describe one leak in two sets of
    # words - "io-shop process heap" and "unbounded cache growth" - and a
    # restart addressed to the alert's service is the same experiment in both.
    # Compared by the candidate's own subject nothing matched, and the gate's
    # cap was all that stopped the walk restarting one service per candidate.
    some_incident_id = a_random_id()
    restarting_the_shop = restarting(SOME_SERVICE)

    Scenario() \
        .given(
            some_candidates := [
                _a_candidate_answered_by(
                    a_candidate_blaming(some_incident_id, "unbounded cache growth"),
                    restarting_the_shop
                )
            ]
        ) \
        .when(
            lambda: the_next_worth_trying(some_candidates,
                                          [_an_attempt_to(restarting_the_shop)],
                                          start=0)
        ) \
        .then(_nothing_is_worth_trying())


@pytest.mark.unit
def test_the_same_subject_done_a_different_way_is_still_worth_trying() -> None:
    # Both halves of the identity, or the cap answers a question nobody asked.
    # Restarting io-shop says nothing about whether a flag of the same name may
    # be put back: they are different experiments about the same cause.
    some_incident_id = a_random_id()
    some_only_candidate = a_candidate_blaming(some_incident_id, SOME_SERVICE)

    Scenario() \
        .given(
            some_candidates := [
                _a_candidate_answered_by(some_only_candidate,
                                         putting_back(SOME_SERVICE))
            ]
        ) \
        .when(
            lambda: the_next_worth_trying(
                some_candidates, [_an_attempt_to(restarting(SOME_SERVICE))], start=0
            )
        ) \
        .then(_the_candidate_taken_up_is(some_only_candidate))


@pytest.mark.unit
def test_an_attempt_on_something_nobody_proposed_disqualifies_nothing() -> None:
    # A later round is told everything this incident tried, and most of it will
    # have nothing to do with the explanations now on the list.
    some_incident_id = a_random_id()
    some_only_candidate = a_candidate_blaming(some_incident_id, SOME_FLAG)

    Scenario() \
        .given(
            some_candidates := [
                _a_candidate_answered_by(some_only_candidate, putting_back(SOME_FLAG))
            ]
        ) \
        .when(lambda: the_next_worth_trying(
            some_candidates, [_an_attempt_to(putting_back(ANOTHER_FLAG))], start=0
        )) \
        .then(_the_candidate_taken_up_is(some_only_candidate))


@pytest.mark.unit
def test_a_candidate_nothing_would_be_done_about_is_still_offered() -> None:
    # No strategy answers the cause, or the one that does found nothing to act
    # on. Nothing was tried that matches it, so nothing disqualifies it - the
    # gate is where an unanswerable proposal has always been refused, and
    # skipping it here would refuse it somewhere nobody records a reason.
    some_incident_id = a_random_id()
    some_only_candidate = a_candidate_blaming(some_incident_id, SOME_FLAG)

    Scenario() \
        .given(some_candidates := [_a_candidate_answered_by(some_only_candidate, None)]) \
        .when(lambda: the_next_worth_trying(
            some_candidates, [_an_attempt_to(putting_back(SOME_FLAG))], start=0
        )) \
        .then(_the_candidate_taken_up_is(some_only_candidate))


@pytest.mark.unit
def test_a_doubtful_candidate_is_worth_an_experiment_like_any_other() -> None:
    # The list is ordered by confidence, so a candidate this far down is only
    # ever reached once everything the model believed more has been refuted - by
    # which point the ranking has been proved wrong about the ones above it.
    some_incident_id = a_random_id()
    some_barely_believed = 0.05
    some_doubtful_candidate = a_determined_hypothesis(some_incident_id,
                                                      confidence=some_barely_believed)

    Scenario() \
        .given(some_candidates := _answered_by_a_flag_each([some_doubtful_candidate])) \
        .when(lambda: the_next_worth_trying(some_candidates, [], start=0)) \
        .then(_the_candidate_taken_up_is(some_doubtful_candidate))


@pytest.mark.unit
def test_what_the_walk_has_already_passed_is_not_reconsidered() -> None:
    # `start` is where the walk has got to, not a hint. A candidate behind it
    # was either tried or passed over on its own merits, and reaching back for
    # it would put the walk in a loop over the same list.
    some_incident_id = a_random_id()
    dont_care_determined_candidate = a_determined_hypothesis(some_incident_id)
    some_determined_candidate_after_it = a_determined_hypothesis(some_incident_id)

    Scenario() \
        .given(
            some_candidates := _answered_by_a_flag_each(
                [dont_care_determined_candidate, some_determined_candidate_after_it]
            )
        ) \
        .when(
            lambda: the_next_worth_trying(some_candidates, [], start=1)
        ) \
        .then(all_of(
            _the_candidate_taken_up_is(some_determined_candidate_after_it),
            _it_sits_at(1))
        )


@pytest.mark.unit
def test_a_list_with_nothing_left_on_it_is_spent() -> None:
    # Which is what buys another investigation, or ends the walk. Distinct from
    # any candidate at all, so the caller can tell "nothing worth trying" from
    # "the first one".
    some_incident_id = a_random_id()

    Scenario() \
        .given(
            every_candidate_tried := [
                _a_candidate_answered_by(
                    a_candidate_blaming(some_incident_id, SOME_FLAG),
                    putting_back(SOME_FLAG)
                ),
                _a_candidate_answered_by(
                    an_undetermined_hypothesis(some_incident_id), None
                )
            ]
        ) \
        .when(lambda: the_next_worth_trying(
            every_candidate_tried, [_an_attempt_to(putting_back(SOME_FLAG))], start=0
        )) \
        .then(_nothing_is_worth_trying())


@pytest.mark.unit
def test_a_candidate_whose_platform_is_unreachable_is_passed_over() -> None:
    # The whole of what a platform failure buys. Five of the seven generic
    # mitigations act through the deployment platform, so a platform that is not
    # answering has taken five candidates away at once - and the walk's right move
    # is to reach for one that acts through something else rather than to end.
    #
    # Passed over rather than refuted: nothing was attempted, so nothing was
    # tested, and a record saying otherwise would have the postmortem report that
    # the evidence ruled a cause out when nothing ruled it out.
    some_incident_id = a_random_id()
    the_flag_is_still_revertible = a_candidate_blaming(some_incident_id, SOME_FLAG)

    Scenario() \
        .given(
            some_candidates := [
                _a_candidate_answered_by(
                    a_candidate_blaming(some_incident_id, SOME_SERVICE),
                    rolling_back(SOME_SERVICE)
                ),
                _a_candidate_answered_by(
                    the_flag_is_still_revertible, putting_back(SOME_FLAG)
                )
            ]
        ) \
        .when(
            lambda: the_next_worth_trying(
                some_candidates, [], start=0,
                unreachable_platforms=[DEPLOYMENT_PLATFORM]
            )
        ) \
        .then(all_of(
            _the_candidate_taken_up_is(the_flag_is_still_revertible),
            _it_sits_at(1)
        ))


@pytest.mark.unit
def test_a_list_whose_every_candidate_needs_the_unreachable_platform_is_spent() -> None:
    # The other ending, and the one the walk has to tell from the first. Nothing
    # here is worth trying while the platform is down, and no further
    # investigation would change that - a later round re-reads the same evidence
    # and arrives at candidates on the same dead platform.
    some_incident_id = a_random_id()

    Scenario() \
        .given(
            every_candidate_needs_the_platform := _answered_by_a_rollback_each(
                [SOME_SERVICE, ANOTHER_SERVICE], some_incident_id
            )
        ) \
        .when(
            lambda: the_next_worth_trying(
                every_candidate_needs_the_platform, [], start=0,
                unreachable_platforms=[DEPLOYMENT_PLATFORM]
            )
        ) \
        .then(_nothing_is_worth_trying())


@pytest.mark.unit
def test_a_candidate_is_not_passed_over_while_its_platform_answers() -> None:
    # The half that decides whether the two above are worth having. A walk that
    # passed over the deployment platform's candidates whenever anything had
    # failed would satisfy both and quietly stop rolling anything back.
    some_incident_id = a_random_id()
    the_rollback_is_still_worth_trying = a_candidate_blaming(
        some_incident_id, SOME_SERVICE
    )

    Scenario() \
        .given(
            some_candidates := [
                _a_candidate_answered_by(
                    the_rollback_is_still_worth_trying, rolling_back(SOME_SERVICE)
                ),
                _a_candidate_answered_by(
                    a_candidate_blaming(some_incident_id, SOME_FLAG),
                    putting_back(SOME_FLAG)
                )
            ]
        ) \
        .when(
            lambda: the_next_worth_trying(
                some_candidates, [], start=0, unreachable_platforms=[]
            )
        ) \
        .then(all_of(
            _the_candidate_taken_up_is(the_rollback_is_still_worth_trying),
            _it_sits_at(0)
        ))


@pytest.mark.unit
def test_a_candidate_nothing_would_be_done_about_survives_an_unreachable_platform() -> None:
    # It acts through nothing, so no platform can take it away. Worth its own case
    # because the obvious implementation asks an absent action which platform it
    # would act through, and the walk that does it crashes rather than skipping -
    # on the one candidate shape that is already the odd one out everywhere else.
    some_incident_id = a_random_id()
    nothing_would_be_done_about_it = an_undetermined_hypothesis(some_incident_id)

    Scenario() \
        .given(
            some_candidates := [
                _a_candidate_answered_by(nothing_would_be_done_about_it, None)
            ]
        ) \
        .when(
            lambda: the_next_worth_trying(
                some_candidates, [], start=0,
                unreachable_platforms=[DEPLOYMENT_PLATFORM]
            )
        ) \
        .then(_nothing_is_worth_trying())


@pytest.mark.unit
def test_a_walk_past_the_end_of_the_list_is_spent() -> None:
    # The ordinary way the last candidate's refutation arrives here.
    some_incident_id = a_random_id()

    Scenario() \
        .given(
            some_candidates := _answered_by_a_flag_each(
                [a_determined_hypothesis(some_incident_id)]
            )
        ) \
        .when(lambda: the_next_worth_trying(some_candidates, [], start=1)) \
        .then(_nothing_is_worth_trying())


@pytest.mark.unit
def test_a_flag_candidate_is_answered_by_putting_that_flag_back() -> None:
    # Asked of Mitigation rather than guessed at, because which action answers
    # which cause is Mitigation's to say - and the flag has to be one the
    # provider actually recorded moving, not one the model named alone.
    some_incident_id = a_random_id()

    Scenario() \
        .given(the_flag_that_moved := [_a_change_to(SOME_FLAG)]) \
        .when(lambda: what_each_would_do(
            [a_candidate_blaming(some_incident_id, SOME_FLAG)],
            Circumstances(service=SOME_SERVICE, flag_changes=the_flag_that_moved)
        )) \
        .then(_each_would_do([putting_back(SOME_FLAG)]))


@pytest.mark.unit
def test_a_leak_candidate_is_answered_by_restarting_the_alerts_service() -> None:
    # The whole reason this is asked of a strategy. The candidate's subject is
    # the model's prose about what is accumulating - one real one read "io-shop
    # process heap (memory_used_bytes / heap of 2048MiB limit)" - and the
    # action is addressed to the service the alert names.
    some_incident_id = a_random_id()

    Scenario() \
        .given(dont_care_changes := [_a_change_to(SOME_FLAG)]) \
        .when(lambda: what_each_would_do(
            [a_leak_blamed_on(some_incident_id,
                               "io-shop process heap (memory_used_bytes)")],
            Circumstances(service=SOME_SERVICE, flag_changes=dont_care_changes)
        )) \
        .then(_each_would_do([restarting(SOME_SERVICE)]))


@pytest.mark.unit
def test_a_candidate_no_strategy_answers_would_have_nothing_done_about_it() -> None:
    # A cause nobody registered an action for, and a flag candidate the
    # provider recorded no change to, reach the same answer: there is nothing
    # this walk would do, so there is nothing to match against what it did.
    some_incident_id = a_random_id()

    Scenario() \
        .given(nothing_the_candidate_blames_moved := [_a_change_to(ANOTHER_FLAG)]) \
        .when(lambda: what_each_would_do(
            [a_candidate_blaming(some_incident_id, SOME_FLAG),
             an_undetermined_hypothesis(some_incident_id)],
            Circumstances(service=SOME_SERVICE,
                          flag_changes=nothing_the_candidate_blames_moved)
        )) \
        .then(_each_would_do([None, None]))


@pytest.mark.unit
def test_a_history_nobody_could_read_answers_nothing_at_all() -> None:
    # Not because every kind of action needs the history - a restart does not -
    # but because the proposal node proposes nothing while the provider cannot
    # be read. An answer here that the node a few steps later contradicts would
    # be the walk skipping a candidate on the strength of an action it then
    # declines to take.
    some_incident_id = a_random_id()

    Scenario() \
        .given(nobody_could_say := None) \
        .when(lambda: what_each_would_do(
            [a_leak_blamed_on(some_incident_id, "io-shop process heap")],
            nobody_could_say
        )) \
        .then(_each_would_do([None]))


@pytest.mark.unit
def test_a_divergence_candidate_is_answered_by_discarding_the_keys_handed_in() -> None:
    # The one candidate whose answer cannot be derived from the candidate. An
    # entry in a store is addressed by a key, a key's format belongs to whoever
    # wrote the store, and so the only thing that can answer this is what the
    # evidence carried - which has to arrive here as an argument or not at all.
    some_incident_id = a_random_id()

    Scenario() \
        .given(the_keys_the_check_named := ["io-shop:summary:2026-09:shopper-4",
                                            "io-shop:summary:2026-09:shopper-9"]) \
        .when(lambda: what_each_would_do(
            [a_divergence_blamed_on(some_incident_id,
                                    "cached monthly totals disagree with the ledger")],
            Circumstances(service=SOME_SERVICE,
                          flag_changes=[_a_change_to(SOME_FLAG)],
                          stale_entry_keys=the_keys_the_check_named)
        )) \
        .then(_each_would_do([discarding(SOME_SERVICE)]))


@pytest.mark.unit
def test_a_corruption_candidate_is_answered_by_the_deployment_recorded() -> None:
    # The other candidate whose answer the candidate cannot give. It names the
    # damage and not the change, so what is undone is whichever change the
    # histories hold - and asked without the deploy history, a corruption a
    # revision caused would come back answered by nothing, and the walk would
    # pass over the one explanation it had.
    some_incident_id = a_random_id()

    Scenario() \
        .given(the_revision_that_went_out := [a_deployment()]) \
        .when(lambda: what_each_would_do(
            [a_corruption_blamed_on(some_incident_id,
                                    "monthly totals fall behind the purchases")],
            Circumstances(service=SOME_SERVICE,
                          flag_changes=[],
                          deployments=the_revision_that_went_out)
        )) \
        .then(_each_would_do([rolling_back(SOME_SERVICE)]))


@pytest.mark.unit
def test_the_circumstances_carry_the_alerts_addresses_beside_the_rounds_histories() -> None:
    # Everything an action can be worked out from, gathered once. The service and
    # the keys are the alert's, because those are addresses and only the alert
    # carries them; the histories are what the round read.
    some_keys = ("io-shop:summary:2026-09:shopper-4",)
    some_flag_changes = [_a_change_to(SOME_FLAG)]
    some_deployments = [a_deployment()]

    Scenario() \
        .given(
            an_alert_naming_entries := Alert(
                service=SOME_SERVICE,
                alert_name=DONT_CARE_ALERT_NAME,
                stale_entry_keys=some_keys,
                stale_entries_found=len(some_keys)
            )
        ) \
        .when(lambda: the_circumstances(
            an_alert_naming_entries, some_flag_changes, some_deployments, None
        )) \
        .then(_the_circumstances_carry(
            service=SOME_SERVICE,
            flag_changes=some_flag_changes,
            stale_entry_keys=some_keys,
            deployments=some_deployments
        ))


@pytest.mark.unit
def test_a_history_nobody_could_read_leaves_no_circumstances() -> None:
    # The one place this is decided, so the node choosing a candidate and the node
    # proposing for it cannot come to disagree about it. "I could not find out
    # what changed" proposes nothing for anything - a restart included.
    Scenario() \
        .given(
            dont_care_alert := Alert(service=SOME_SERVICE,
                                     alert_name=DONT_CARE_ALERT_NAME)
        ) \
        .when(lambda: the_circumstances(dont_care_alert, None, [a_deployment()], None)) \
        .then(_there_are_no_circumstances())


@pytest.mark.unit
def test_an_alert_naming_no_entries_and_an_unread_platform_carry_neither() -> None:
    # Both arrive as `None` and both are carried as empty. An alert that mentions
    # no cache says nothing about entries rather than claiming none is stale, and
    # the one mode that reads deployments proposes a rollback only where one was
    # recorded - so neither absence has anything to tell a strategy.
    Scenario() \
        .given(
            an_alert_naming_no_entries := Alert(service=SOME_SERVICE,
                                                alert_name=DONT_CARE_ALERT_NAME)
        ) \
        .when(lambda: the_circumstances(an_alert_naming_no_entries, [], None, None)) \
        .then(_the_circumstances_carry(
            service=SOME_SERVICE,
            flag_changes=[],
            stale_entry_keys=(),
            deployments=[]
        ))


@pytest.mark.unit
def test_the_circumstances_carry_the_placement_the_round_recorded() -> None:
    # The one piece of evidence an action is worked out from that neither
    # history holds: a replica moved onto another card with nothing deployed.
    # Carried as the round recorded it, onset and all, because which card to pin
    # to is decided from which pods started at that onset.
    Scenario() \
        .given(
            the_placement_recorded := a_placement()
        ) \
        .when(lambda: the_circumstances(
            Alert(service=SOME_SERVICE, alert_name=DONT_CARE_ALERT_NAME),
            [],
            None,
            the_placement_recorded
        )) \
        .then(_the_circumstances_hold_the_placement(the_placement_recorded))


@pytest.mark.unit
def test_a_placement_nobody_could_read_is_carried_as_none() -> None:
    # Unlike the deploy history, never as empty. An empty placement says the
    # service runs on no pod, and a strategy deciding from it finds no replica
    # that moved - which is an outage read as an all-clear. The flag history is
    # what decides whether there are circumstances at all, so this leaves them
    # standing and says only that the placement is unknown.
    Scenario() \
        .given(
            dont_care_alert := Alert(service=SOME_SERVICE,
                                     alert_name=DONT_CARE_ALERT_NAME)
        ) \
        .when(lambda: the_circumstances(dont_care_alert, [], None, None)) \
        .then(_the_circumstances_hold_the_placement(None))


def _the_circumstances_hold_the_placement(
    expected: RecordedPlacement | None
) -> Assertion[Circumstances | None]:
    def assertion(built: Circumstances | None) -> bool:
        if built is None:
            raise AssertionError(
                "Expected circumstances to be built from a readable flag history, "
                "and there were none."
            )

        if built.placement != expected:
            raise AssertionError(
                f"Expected the circumstances to hold the placement {expected!r}, "
                f"got {built.placement!r}."
            )

        return True

    return assertion


def _a_change_to(flag: str) -> FlagChange:
    """One change the provider recorded, switching a flag on."""
    return FlagChange(flag=flag, enabled=True, occurred_at=DONT_CARE_MOMENT)


def _a_candidate_answered_by(candidate: Hypothesis,
                             identity: ActionIdentity | None) -> WhatWouldBeTried:
    """One candidate, beside the action the walk would take about it."""
    return WhatWouldBeTried(candidate=candidate, identity=identity)


def _answered_by_a_flag_each(candidates: list[Hypothesis]) -> list[WhatWouldBeTried]:
    """Candidates whose actions are all distinct, for a case about neither.

    Each is answered by putting back a flag named after where it sits, so no
    two of them collide and nothing is skipped for a reason the case is not
    about.
    """
    return [
        _a_candidate_answered_by(candidate, putting_back(f"some-flag-{index}"))
        for index, candidate in enumerate(candidates)
    ]


def _an_attempt_to(identity: ActionIdentity) -> Attempt:
    """A mitigation this incident already took, and undid again.

    Everything but the identity is arbitrary: only the identity is read here,
    and an attempt exists on the list at all only because it failed.
    """
    return Attempt(identity=identity, enabled=False, occurred_at=DONT_CARE_MOMENT)


def _each_would_do(expected: list[ActionIdentity | None]
                   ) -> Assertion[list[WhatWouldBeTried]]:
    def assertion(answered: list[WhatWouldBeTried]) -> bool:
        identities = [entry.identity for entry in answered]

        if identities != expected:
            raise AssertionError(f"Expected {expected}, got {identities}")

        return True

    return assertion


def _the_circumstances_carry(service: str,
                             flag_changes: list[FlagChange],
                             stale_entry_keys: tuple[str, ...],
                             deployments: list[ChangeEvent]
                             ) -> Assertion[Circumstances | None]:
    """Every field compared, and every one that differs reported.

    Compared as lists, because what is asserted is which items arrive in which
    order - not which kind of sequence happens to hold them.
    """
    def assertion(built: Circumstances | None) -> bool:
        if built is None:
            raise AssertionError(
                "Expected circumstances to be built from a readable flag history, "
                "and there were none."
            )

        wrong = [
            f"{name} expected {expected}, got {got}"
            for name, expected, got in (
                ("service", service, built.service),
                ("flag_changes", flag_changes, list(built.flag_changes)),
                ("stale_entry_keys", list(stale_entry_keys),
                 list(built.stale_entry_keys)),
                ("deployments", deployments, list(built.deployments))
            )
            if expected != got
        ]

        if wrong:
            raise AssertionError(
                f"The circumstances do not carry what they were built from: "
                f"{'; '.join(wrong)}."
            )

        return True

    return assertion


def _there_are_no_circumstances() -> Assertion[Circumstances | None]:
    def assertion(built: Circumstances | None) -> bool:
        if built is not None:
            raise AssertionError(
                f"Expected no circumstances where the flag history could not be "
                f"read, got {built!r}."
            )

        return True

    return assertion


def _the_candidate_taken_up_is(expected: Hypothesis) -> Assertion[Chosen]:
    def assertion(chosen: Chosen) -> bool:
        if chosen is None:
            raise AssertionError(
                f"Expected the candidate {expected.summary!r} blaming "
                f"{expected.subject!r}, nothing was worth trying."
            )

        _, candidate = chosen

        if candidate != expected:
            raise AssertionError(
                f"Expected the candidate blaming {expected.subject!r}, "
                f"got the one blaming {candidate.subject!r}"
            )

        return True

    return assertion


def _it_sits_at(expected: int) -> Assertion[Chosen]:
    """Where on the list the candidate came from.

    Asserted beside the candidate itself rather than instead of it: the index is
    what the walk carries forward, so a right answer returned with the wrong
    index sends the next round back over ground it has covered.
    """
    def assertion(chosen: Chosen) -> bool:
        if chosen is None:
            raise AssertionError(f"Expected a candidate at {expected}, got none at all.")

        index, _ = chosen

        if index != expected:
            raise AssertionError(f"Expected the candidate at {expected}, got {index}")

        return True

    return assertion


def _nothing_is_worth_trying() -> Assertion[Chosen]:
    def assertion(chosen: Chosen) -> bool:
        if chosen is not None:
            _, candidate = chosen
            raise AssertionError(
                "Expected a spent list, got the candidate blaming "
                f"{candidate.subject!r}"
            )

        return True

    return assertion


def _answered_by_a_rollback_each(applications: list[str],
                                 incident_id: str) -> list[WhatWouldBeTried]:
    """Candidates every one of which acts through the deployment platform.

    For the case about a list with nothing left on a reachable platform. Distinct
    applications, so that nothing is passed over for having been tried - the only
    reason anything is skipped here is the platform.
    """
    return [
        _a_candidate_answered_by(
            a_candidate_blaming(incident_id, application), rolling_back(application)
        )
        for application in applications
    ]
