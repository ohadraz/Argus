"""A revision said short: as git abbreviates it, and as long as it takes to
name it alone among the revisions an incident read - and found in a sentence,
whole or by a start of it, as the one revision that start names.

One rule in one place, because the postmortem, the dashboard and the channel
each say a revision, and two shortenings are two chances to disagree.
"""

from __future__ import annotations

import pytest
from argus_core import A_REVISION, said_short, short_form, the_revision_named
from argus_testkit import Scenario, the_answer_was

# Two revisions starting nothing alike.
SOME_REVISION = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
SOME_OTHER_REVISION = "4c810f22894e612ced87f5ee3f3062dfeb785050"

# One sharing the first's seven characters and parting from it at the eighth.
SOME_RIVAL = "26f1d7e90000000000000000000000000000000a"

SOME_SHORT_FORM = SOME_REVISION[:7]


@pytest.mark.unit
def test_a_revision_is_said_in_seven_characters_as_git_abbreviates_it() -> None:
    Scenario() \
        .when(
            lambda: short_form(SOME_REVISION, frozenset({SOME_REVISION, SOME_OTHER_REVISION}))
        ) \
        .then(
            the_answer_was(SOME_SHORT_FORM)
        )


@pytest.mark.unit
def test_a_revision_another_starts_like_is_said_as_long_as_it_takes_to_tell_them_apart() -> None:
    Scenario() \
        .when(
            lambda: short_form(SOME_REVISION, frozenset({SOME_REVISION, SOME_RIVAL}))
        ) \
        .then(
            the_answer_was(SOME_REVISION[:8])
        )


@pytest.mark.unit
def test_a_short_form_and_the_whole_revision_it_names_are_one_revision_not_two() -> None:
    # A change's short form beside a candidate naming the same revision whole -
    # or a candidate's short form beside the change's whole one - are two names
    # for one revision, and neither makes the other longer. Taken for rivals,
    # the short one could never be told apart from the whole, however long.
    Scenario() \
        .when(
            lambda: (short_form(SOME_SHORT_FORM, frozenset({SOME_SHORT_FORM, SOME_REVISION})),
                     short_form(SOME_REVISION, frozenset({SOME_REVISION, SOME_REVISION[:9]})))
        ) \
        .then(
            the_answer_was((SOME_SHORT_FORM, SOME_SHORT_FORM))
        )


@pytest.mark.unit
@pytest.mark.parametrize("named", [SOME_REVISION, SOME_REVISION[:8], SOME_SHORT_FORM],
                         ids=["whole", "eight-characters", "short"])
def test_a_revision_is_named_whole_or_by_a_start_of_it(named: str) -> None:
    Scenario() \
        .when(
            lambda: the_revision_named(named, frozenset({SOME_REVISION, SOME_OTHER_REVISION}))
        ) \
        .then(
            the_answer_was(SOME_REVISION)
        )


@pytest.mark.unit
def test_a_start_two_revisions_share_names_neither() -> None:
    # Nothing here can say which was meant.
    Scenario() \
        .when(
            lambda: the_revision_named(SOME_SHORT_FORM, frozenset({SOME_REVISION, SOME_RIVAL}))
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_start_of_no_revision_names_none() -> None:
    # One a few characters off is the postmortem checker's to put right, not
    # this rule's.
    Scenario() \
        .when(
            lambda: the_revision_named("26f1d7f", frozenset({SOME_REVISION, SOME_OTHER_REVISION}))
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
def test_a_start_shorter_than_a_short_form_names_none() -> None:
    # Shorter than git abbreviates one to by default, a start of a revision is
    # any small number, and every small number in a sentence would name one.
    Scenario() \
        .when(
            lambda: the_revision_named(SOME_SHORT_FORM[:6], frozenset({SOME_REVISION}))
        ) \
        .then(
            the_answer_was(None)
        )


@pytest.mark.unit
@pytest.mark.parametrize("said", [f"rolled back off {SOME_REVISION}",
                                  f"rolled back off [{SOME_SHORT_FORM}]"],
                         ids=["whole", "short-and-bracketed"])
def test_a_revision_is_found_in_a_sentence_whole_or_short(said: str) -> None:
    Scenario() \
        .when(
            lambda: [found.group(0) for found in A_REVISION.finditer(said)]
        ) \
        .then(
            the_answer_was([said.removeprefix("rolled back off ").strip("[]")])
        )


@pytest.mark.unit
@pytest.mark.parametrize("said", ["io-shop-7c9f4d8b6-x2kqp", "deadbeef", "1234567"],
                         ids=["inside-a-pod-name", "no-digit", "no-letter"])
def test_hex_that_is_part_of_a_name_or_could_be_a_word_is_no_revision(said: str) -> None:
    # The hash in a pod's name is part of that name, and a run of hex with no
    # digit or no letter in it reads as a word or a number as easily.
    Scenario() \
        .when(
            lambda: A_REVISION.findall(said)
        ) \
        .then(
            the_answer_was([])
        )


@pytest.mark.unit
@pytest.mark.parametrize("named", [SOME_REVISION, SOME_REVISION[:8]],
                         ids=["whole", "by-a-start-of-it"])
def test_a_revision_a_sentence_names_is_said_by_its_short_form(named: str) -> None:
    Scenario() \
        .when(
            lambda: said_short(f"rolled back off [{named}]", {SOME_REVISION: SOME_SHORT_FORM})
        ) \
        .then(
            the_answer_was(f"rolled back off [{SOME_SHORT_FORM}]")
        )


@pytest.mark.unit
def test_a_start_two_revisions_share_is_said_as_written() -> None:
    Scenario() \
        .when(
            lambda: said_short(f"rolled back off {SOME_SHORT_FORM}",
                               {SOME_REVISION: SOME_REVISION[:8], SOME_RIVAL: SOME_RIVAL[:8]})
        ) \
        .then(
            the_answer_was(f"rolled back off {SOME_SHORT_FORM}")
        )


@pytest.mark.unit
def test_a_revision_the_incident_never_read_is_said_as_written() -> None:
    Scenario() \
        .when(
            lambda: said_short(f"rolled back off {SOME_OTHER_REVISION}",
                               {SOME_REVISION: SOME_SHORT_FORM})
        ) \
        .then(
            the_answer_was(f"rolled back off {SOME_OTHER_REVISION}")
        )
