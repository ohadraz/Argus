"""The pull request an answer names, held to the one the record holds.

The record holds at most one pull request - the draft Code-Fix opened - and the
brief names it, by its name and by its address. So any pull request an answer
names is that one, and is written by its name: a number of its own is one the
answer was handed by another run, as a replay's recording was by the run that
recorded it, and a document saying it names a pull request nobody can open.
"""

from __future__ import annotations

import pytest
from agent_postmortem.prompting import (
    SubmittedFactor,
    SubmittedItem,
    SubmittedPostmortem,
    SubmittedStep,
)
from agent_postmortem.pull_requests import the_pull_request_named, with_the_pull_request_named
from argus_core.models import ActionItemType, Lessons, OpenedPullRequest
from argus_testkit import Scenario, the_answer_was

# The pull request the record holds.
SOME_PULL_REQUEST = OpenedPullRequest(number=1,
                                      url="https://github.invalid/acme/shop/pull/1",
                                      branch="argus/fix-abc")
# The pull request a replay's recording names: the one the recording run opened.
SOME_OTHER_RUNS_NUMBER = 356


@pytest.mark.unit
@pytest.mark.parametrize("named", [
    "PR #356",
    "pull request #356",
    "Pull request #356",
    "https://github.com/acme/shop/pull/356"
], ids=["by-argus-s-name", "in-words", "in-words-opening-a-sentence", "by-its-address"])
def test_a_pull_request_the_answer_names_is_written_as_the_record_s_by_its_name(
        named: str) -> None:
    # A replay's recording names the pull request of the run that recorded it,
    # where the brief and every other line name this run's.
    Scenario() \
        .given(
            an_answer_naming_another := SubmittedPostmortem(
                root_cause=f"the fix ({named}) is waiting on a person")
        ) \
        .when(
            lambda: with_the_pull_request_named(an_answer_naming_another, SOME_PULL_REQUEST)
        ) \
        .then(
            the_answer_was(SubmittedPostmortem(root_cause="the fix (PR #1) is waiting on a person"))
        )


@pytest.mark.unit
def test_a_pull_request_named_where_the_record_holds_none_is_left_as_written() -> None:
    # Nothing here can say which one it meant.
    Scenario() \
        .given(
            an_answer_naming_one := SubmittedPostmortem(root_cause="PR #356 is waiting")
        ) \
        .when(
            lambda: with_the_pull_request_named(an_answer_naming_one, None)
        ) \
        .then(
            the_answer_was(an_answer_naming_one)
        )


@pytest.mark.unit
def test_a_number_naming_no_pull_request_is_left_as_written() -> None:
    # "#356" alone, or a ticket's number, is no pull request's name.
    Scenario() \
        .given(
            an_answer_naming_other_numbers := SubmittedPostmortem(
                root_cause="ticket #356 and item #4 are open")
        ) \
        .when(
            lambda: with_the_pull_request_named(an_answer_naming_other_numbers, SOME_PULL_REQUEST)
        ) \
        .then(
            the_answer_was(an_answer_naming_other_numbers)
        )


@pytest.mark.unit
def test_every_sentence_the_answer_publishes_names_the_record_s_pull_request() -> None:
    # A pull request is named wherever the model names it, and a field left out
    # here reaches the page naming another run's.
    Scenario() \
        .given(
            an_answer_naming_another_everywhere := _an_answer_naming_everywhere("PR #356")
        ) \
        .when(
            lambda: with_the_pull_request_named(an_answer_naming_another_everywhere,
                                                SOME_PULL_REQUEST)
        ) \
        .then(
            the_answer_was(_an_answer_naming_everywhere("PR #1"))
        )


@pytest.mark.unit
def test_prose_naming_another_pull_request_names_the_record_s() -> None:
    # The executive overview is prose of its own, outside any answer, and was
    # once replayed naming the recording run's draft.
    Scenario() \
        .when(
            lambda: the_pull_request_named(_a_draft_fix_awaiting_review(SOME_OTHER_RUNS_NUMBER),
                                           SOME_PULL_REQUEST)
        ) \
        .then(
            the_answer_was(_a_draft_fix_awaiting_review(SOME_PULL_REQUEST.number))
        )


@pytest.mark.unit
def test_prose_naming_a_pull_request_where_the_record_holds_none_is_left_as_written() -> None:
    a_sentence_naming_one = _a_draft_fix_awaiting_review(SOME_OTHER_RUNS_NUMBER)

    Scenario() \
        .when(
            lambda: the_pull_request_named(a_sentence_naming_one, None)
        ) \
        .then(
            the_answer_was(a_sentence_naming_one)
        )


def _a_draft_fix_awaiting_review(number: int) -> str:
    """An overview's sentence naming pull request `number` as Argus names one."""
    return f"A draft fix, PR #{number}, awaits review."


def _an_answer_naming_everywhere(pull_request: str) -> SubmittedPostmortem:
    """An answer naming one pull request in every sentence it would publish."""
    said = f"{pull_request} is waiting on a person"

    return SubmittedPostmortem(
        root_cause=said,
        cause_in_plain_words=said,
        still_at_risk=said,
        symptom=said,
        assumptions=[said],
        lead_effects={"L1": said},
        causal_chain=[SubmittedStep(step=said, cites=["T1"])],
        contributing_factors=[SubmittedFactor(factor=said, addressed_by=["AI-1"])],
        action_items=[SubmittedItem(item=said, type=ActionItemType.PREVENT)],
        lessons=Lessons(went_well=[said], went_wrong=[said], got_lucky=[said])
    )
