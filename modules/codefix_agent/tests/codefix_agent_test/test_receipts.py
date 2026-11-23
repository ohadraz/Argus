"""A receipt for every read Code-Fix makes.

Written around the read, so each one that returns leaves one row under the read
tier's name for it - its arguments by the names the tier asks them by, its
answer as it came back - and one that raised leaves none.
"""

from __future__ import annotations

import pytest
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    all_of,
    attempting,
    nothing_was_collected,
    the_answer_was,
    the_same_error_reached_the_caller,
)
from codefix_agent.receipts import receipted
from core.models import CodeOutsideThePatch
from core.replay import CallType, Replay, ReplayEntry

SOME_INCIDENT_ID = "8d3f6a52-0000-4000-8000-000000000001"
SOME_TOOL = "read_repository_file"
# What a read names its arguments by, as the tier asks them.
SOME_PATH_NAME = "path"
SOME_REF_NAME = "ref"
SOME_PATH = "src/io_shop/spend_summary.py"
SOME_REF = "main"
SOME_SOURCE = "def average_spend_per_item_this_month(account):\n    ...\n"
DONT_CARE_REASON = "dont care why"


@pytest.mark.unit
def test_a_read_that_returns_leaves_one_receipt_naming_what_it_asked_and_what_came_back(
) -> None:
    receipts: Kept[ReplayEntry] = Kept()

    Scenario() \
        .given(
            a_reading := receipted(Replay(SOME_INCIDENT_ID, receipts.take), SOME_TOOL,
                                   _answering(SOME_SOURCE), SOME_PATH_NAME, SOME_REF_NAME)
        ) \
        .when(
            lambda: a_reading(SOME_PATH, SOME_REF)
        ) \
        .then(
            all_of(
                the_answer_was(SOME_SOURCE),
                _one_receipt(receipts, target=SOME_TOOL,
                             request={"arguments": {SOME_PATH_NAME: SOME_PATH,
                                                    SOME_REF_NAME: SOME_REF}},
                             response={"answer": SOME_SOURCE})
            )
        )


@pytest.mark.unit
def test_a_read_called_by_keyword_files_that_argument_by_its_keyword() -> None:
    # The ports are called positionally today; a read called by keyword would
    # otherwise file the argument under no name at all. Named for the first
    # argument alone, so the second's name can only come from its keyword.
    receipts: Kept[ReplayEntry] = Kept()

    Scenario() \
        .given(
            a_reading := receipted(Replay(SOME_INCIDENT_ID, receipts.take), SOME_TOOL,
                                   _answering(SOME_SOURCE), SOME_PATH_NAME)
        ) \
        .when(
            lambda: a_reading(SOME_PATH, ref=SOME_REF)
        ) \
        .then(
            _one_receipt(receipts, target=SOME_TOOL,
                         request={"arguments": {SOME_PATH_NAME: SOME_PATH,
                                                SOME_REF_NAME: SOME_REF}},
                         response={"answer": SOME_SOURCE})
        )


@pytest.mark.unit
def test_a_read_answering_with_a_model_is_kept_as_its_json() -> None:
    # The log holds JSON: a model kept as itself is a row nothing can write.
    some_answer = CodeOutsideThePatch(uses=[], defined={SOME_PATH: ["average_spend"]})
    receipts: Kept[ReplayEntry] = Kept()

    Scenario() \
        .given(
            a_reading := receipted(Replay(SOME_INCIDENT_ID, receipts.take), SOME_TOOL,
                                   _answering(some_answer), SOME_REF_NAME)
        ) \
        .when(
            lambda: a_reading(SOME_REF)
        ) \
        .then(
            _one_receipt(receipts, target=SOME_TOOL,
                         request={"arguments": {SOME_REF_NAME: SOME_REF}},
                         response={"answer": some_answer.model_dump(mode="json")})
        )


@pytest.mark.unit
def test_a_read_that_raised_leaves_no_receipt_and_its_error_reaches_the_caller() -> None:
    # Nothing was read, so there is nothing to keep a receipt for - and the
    # caller decides what a failed read comes to, as it did before.
    some_failure = RuntimeError(DONT_CARE_REASON)
    receipts: Kept[ReplayEntry] = Kept()

    Scenario() \
        .given(
            a_reading := receipted(Replay(SOME_INCIDENT_ID, receipts.take), SOME_TOOL,
                                   _raising(some_failure), SOME_REF_NAME)
        ) \
        .when(
            attempting(lambda: a_reading(SOME_REF))
        ) \
        .then(
            all_of(
                the_same_error_reached_the_caller(some_failure),
                nothing_was_collected(receipts)
            )
        )


@pytest.mark.unit
def test_a_recorder_that_cannot_write_costs_the_read_nothing() -> None:
    # A receipt is never part of the work: a read that returned is answered
    # whether or not the log could keep it.
    Scenario() \
        .given(
            a_reading := receipted(Replay(SOME_INCIDENT_ID, _a_recorder_that_fails),
                                   SOME_TOOL, _answering(SOME_SOURCE), SOME_REF_NAME)
        ) \
        .when(
            lambda: a_reading(SOME_REF)
        ) \
        .then(
            the_answer_was(SOME_SOURCE)
        )


def _answering[T](answer: T) -> _Read[T]:
    return _Read(answer=answer, failure=None)


def _raising(failure: Exception) -> _Read[str]:
    return _Read(answer="", failure=failure)


class _Read[T]:
    """A read answering with `answer`, or raising `failure` where there is one."""

    def __init__(self, *, answer: T, failure: Exception | None) -> None:
        self._answer = answer
        self._failure = failure

    def __call__(self, *dont_care_arguments: str, **dont_care_keywords: str) -> T:
        if self._failure is not None:
            raise self._failure

        return self._answer


def _a_recorder_that_fails(dont_care_entry: ReplayEntry) -> None:
    raise RuntimeError(DONT_CARE_REASON)


def _one_receipt(receipts: Kept[ReplayEntry], *, target: str, request: dict[str, object],
                 response: dict[str, object]) -> Assertion[object]:
    """That exactly one receipt was kept: a tool call against this incident, for
    `target`, with `request` and `response`."""
    def assertion(_: object) -> bool:
        kept = receipts.only()
        wanted = (SOME_INCIDENT_ID, CallType.MCP, target, request, response)
        got = (kept.incident_id, kept.call_type, kept.target, kept.request, kept.response)
        if got != wanted:
            raise AssertionError(f"Expected the receipt {wanted}, got {got}.")

        return True

    return assertion
