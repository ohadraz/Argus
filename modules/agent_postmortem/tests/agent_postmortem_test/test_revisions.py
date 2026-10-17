"""The revisions an answer names, held to the ones the incident read.

A revision is a name, and the answer writes it the way a reader meets one: in
its short form, as git abbreviates it and a pull request or a log shows it.
Forty characters in a sentence read as noise, and a document writing one
revision two ways reads as naming two. What code holds it to is being one. A
real revision, short or whole, is written short. One a few characters off is the
revision it starts like, and is written as that: code knows which one it was,
and asking the model again would pay twice to put back a character. One that
starts like none of them, or like more than one, is left as written for the
check to put back to the model (`checking`), because nothing here can know
what it meant.
"""

from __future__ import annotations

import pytest
from agent_postmortem.prompting import (
    SubmittedFactor,
    SubmittedItem,
    SubmittedPostmortem,
    SubmittedStep,
)
from agent_postmortem.revisions import (
    ENOUGH_TO_BE_THE_SAME,
    revisions_of,
    with_revisions_corrected,
)
from argus_core.models import ActionItemType, ChangeEvent, ChangeKind, Lessons
from argus_testkit import Scenario, the_answer_was

from agent_postmortem_test.framework.builders import a_candidate, an_evidence_bundle

# Two revisions the incident read, starting nothing alike.
SOME_REVISION = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
SOME_OTHER_REVISION = "4c810f22894e612ced87f5ee3f3062dfeb785050"

# The first one's short form - seven characters, as git abbreviates a revision -
# and the same revision as a model writes it: at a length of its own choosing,
# and off by its last character.
SOME_SHORT_FORM = SOME_REVISION[:7]
SOME_LONGER_FORM = SOME_REVISION[:10]
SOME_FORM_A_CHARACTER_OFF = SOME_REVISION[:7] + "3"

SOME_FLAG = "checkout-fallback"


@pytest.mark.unit
def test_the_revisions_read_are_what_the_changes_and_the_candidates_name() -> None:
    # A deploy names its revision, and so does a candidate blaming one. A flag
    # is named too, and is no revision.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                changes=[_a_change(ChangeKind.DEPLOY, SOME_REVISION),
                         _a_change(ChangeKind.FLAG_TOGGLE, SOME_FLAG)],
                candidates=[a_candidate("dont care", subject=SOME_OTHER_REVISION),
                            a_candidate("dont care", subject=SOME_FLAG)])
        ) \
        .when(
            lambda: revisions_of(evidence)
        ) \
        .then(
            the_answer_was(frozenset({SOME_REVISION, SOME_OTHER_REVISION}))
        )


@pytest.mark.unit
def test_a_revision_the_incident_read_is_written_short_however_long_it_was_written() -> None:
    # Whole, it is forty characters in the middle of a sentence; at a length
    # the model chose, it is one revision written two ways in one document.
    Scenario() \
        .given(
            an_answer_naming_both := SubmittedPostmortem(
                root_cause=f"{SOME_LONGER_FORM} replaced {SOME_OTHER_REVISION}")
        ) \
        .when(
            lambda: with_revisions_corrected(an_answer_naming_both,
                                             frozenset({SOME_REVISION, SOME_OTHER_REVISION}))
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(
                root_cause=f"{SOME_SHORT_FORM} replaced {SOME_OTHER_REVISION[:7]}"))
        )


@pytest.mark.unit
def test_a_revision_written_short_already_stands() -> None:
    Scenario() \
        .given(
            an_answer_naming_it_short := SubmittedPostmortem(
                root_cause=f"revision {SOME_SHORT_FORM} broke it")
        ) \
        .when(
            lambda: with_revisions_corrected(an_answer_naming_it_short,
                                             frozenset({SOME_REVISION, SOME_OTHER_REVISION}))
        ) \
        .then(
            the_answer_was(an_answer_naming_it_short)
        )


@pytest.mark.unit
def test_two_revisions_alike_for_seven_characters_are_written_as_long_as_tells_them_apart() -> None:
    # A short form two of the incident's revisions share names neither, so it
    # is as short as it can be while still naming one - which is what git does.
    some_revision = "abcdef12" + "0" * 32
    some_twin = "abcdef13" + "0" * 32

    Scenario() \
        .given(
            an_answer_naming_one_whole := SubmittedPostmortem(
                root_cause=f"revision {some_revision} broke it")
        ) \
        .when(
            lambda: with_revisions_corrected(an_answer_naming_one_whole,
                                             frozenset({some_revision, some_twin}))
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause="revision abcdef12 broke it"))
        )


@pytest.mark.unit
def test_a_revision_a_character_off_is_written_as_the_one_it_starts_like() -> None:
    Scenario() \
        .given(
            an_answer_a_character_off := SubmittedPostmortem(
                root_cause=f"revision {SOME_FORM_A_CHARACTER_OFF} broke it")
        ) \
        .when(
            lambda: with_revisions_corrected(an_answer_a_character_off,
                                             frozenset({SOME_REVISION, SOME_OTHER_REVISION}))
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause=f"revision {SOME_SHORT_FORM} broke it"))
        )


@pytest.mark.unit
def test_a_revision_sharing_just_enough_of_its_start_with_one_is_that_one() -> None:
    some_revision_sharing_just_enough = SOME_REVISION[:ENOUGH_TO_BE_THE_SAME] + "aaaa"

    Scenario() \
        .given(
            an_answer_sharing_just_enough := SubmittedPostmortem(
                root_cause=f"revision {some_revision_sharing_just_enough} broke it")
        ) \
        .when(
            lambda: with_revisions_corrected(an_answer_sharing_just_enough,
                                             frozenset({SOME_REVISION}))
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause=f"revision {SOME_SHORT_FORM} broke it"))
        )


@pytest.mark.unit
def test_a_revision_sharing_less_than_that_is_left_for_the_check() -> None:
    # Three characters alike is one chance in four thousand, which is not
    # enough to write a revision into a postmortem that nobody named.
    some_revision_sharing_too_little = SOME_REVISION[:ENOUGH_TO_BE_THE_SAME - 1] + "9aaaa"

    Scenario() \
        .given(
            an_answer_sharing_too_little := SubmittedPostmortem(
                root_cause=f"revision {some_revision_sharing_too_little} broke it")
        ) \
        .when(
            lambda: with_revisions_corrected(an_answer_sharing_too_little,
                                             frozenset({SOME_REVISION}))
        ) \
        .then(
            the_answer_was(an_answer_sharing_too_little)
        )


@pytest.mark.unit
def test_a_revision_starting_like_two_is_left_for_the_check() -> None:
    # Nothing says which of the two it meant, and a guess written in as the
    # revision is worse than the question put back.
    some_revision = "abcde123" + "0" * 32
    some_twin = "abcde456" + "0" * 32

    Scenario() \
        .given(
            an_answer_starting_like_both := SubmittedPostmortem(
                root_cause="revision abcde789 broke it")
        ) \
        .when(
            lambda: with_revisions_corrected(an_answer_starting_like_both,
                                             frozenset({some_revision, some_twin}))
        ) \
        .then(
            the_answer_was(an_answer_starting_like_both)
        )


@pytest.mark.unit
def test_a_hash_inside_a_longer_name_is_no_revision() -> None:
    # A pod's name carries its replica set's hash, and the hash is part of the
    # name: rewritten to the revision it happens to start like, the pod would
    # be one that never existed.
    some_revision_like_the_pods_hash = "7d9c4f8b7" + "0" * 31

    Scenario() \
        .given(
            an_answer_naming_a_pod := SubmittedPostmortem(
                root_cause="the pod io-shop-7d9c4f8b6-x2k9p restarted")
        ) \
        .when(
            lambda: with_revisions_corrected(an_answer_naming_a_pod,
                                             frozenset({some_revision_like_the_pods_hash}))
        ) \
        .then(
            the_answer_was(an_answer_naming_a_pod)
        )


@pytest.mark.unit
def test_every_sentence_the_answer_publishes_is_corrected() -> None:
    # A revision is written wherever the model writes it, and a field left out
    # here is one that reaches the page as the model wrote it.
    Scenario() \
        .given(
            an_answer_a_character_off_everywhere := _an_answer_naming_everywhere(
                SOME_FORM_A_CHARACTER_OFF)
        ) \
        .when(
            lambda: with_revisions_corrected(an_answer_a_character_off_everywhere,
                                             frozenset({SOME_REVISION}))
        ) \
        .then(
            the_answer_was(_an_answer_naming_everywhere(SOME_SHORT_FORM))
        )


def _a_change(kind: ChangeKind, reference: str) -> ChangeEvent:
    return ChangeEvent(kind=kind,
                       occurred_at="2026-09-02T11:59:00Z",
                       reference=reference,
                       summary="dont care")


def _an_answer_naming_everywhere(revision: str) -> SubmittedPostmortem:
    """An answer naming one revision in every sentence it would publish."""
    said = f"revision {revision} broke it"

    return SubmittedPostmortem(
        root_cause=said,
        executive_summary=said,
        symptom=said,
        assumptions=[said],
        lead_effects={"L1": said},
        causal_chain=[SubmittedStep(step=said, cites=["T1"])],
        contributing_factors=[SubmittedFactor(factor=said, addressed_by=["AI-1"])],
        action_items=[SubmittedItem(item=said, type=ActionItemType.PREVENT)],
        lessons=Lessons(went_well=[said], went_wrong=[said], got_lucky=[said])
    )
