"""Which client a caller gets when it brings none of its own.

One decision, and it is not the choosing. There is a single adapter and no
alternative to weigh it against, so what this pins is the other half of the
factory's job: a caller that asked for a receipt is handed a client that keeps
one, and a caller that did not is handed the adapter itself rather than a
recorder wrapped around a sink that discards.

Both halves matter, and the second is the one nothing else would catch. A
factory that wrapped unconditionally would pass every test Argus has - the
recording is transparent - while charging a decorator to every agent that
never asked for one and putting a frame between every stack trace and the call
that raised.

`component` rather than `unit`: the factory reads the process's settings and
builds a vendor client out of them, neither of which it takes as a parameter.
Nothing leaves the process, though - constructing an SDK client talks to
nobody - so this costs no tokens and needs no key.
"""

from __future__ import annotations

import pytest
from argus_core.llm import build_llm_client
from argus_core.llm.recorded_client import RecordedLLMClient
from argus_core.replay import Replay
from argus_testkit import Assertion, Scenario

from argus_core_test.framework.replay import a_recorder_that_keeps_what_it_is_given

SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"


@pytest.mark.component
def test_a_caller_that_asked_for_no_receipt_is_handed_the_client_itself() -> None:
    # Unwrapped rather than wrapped around a recorder with nowhere to write:
    # an agent that is not recording should not pay for a decorator, and the
    # absence should be visible in a stack trace rather than one frame down.
    Scenario() \
        .given(
            an_agent_that_is_not_recording := None
        ) \
        .when(
            lambda: build_llm_client(an_agent_that_is_not_recording)
        ) \
        .then(
            _keeps_no_receipt()
        )


@pytest.mark.component
def test_a_caller_that_asked_to_keep_a_receipt_is_handed_one_that_does() -> None:
    # The wrapping happens in the factory rather than at the call site, because
    # the recorder has to be told which model it is recording and that is the
    # one fact a caller managed to avoid knowing.
    Scenario() \
        .given(
            an_incident_keeping_its_receipts := Replay(
                SOME_INCIDENT_ID, a_recorder_that_keeps_what_it_is_given().take)
        ) \
        .when(
            lambda: build_llm_client(an_incident_keeping_its_receipts)
        ) \
        .then(
            _keeps_a_receipt()
        )


def _keeps_a_receipt() -> Assertion[object]:
    def assertion(client: object) -> bool:
        if not isinstance(client, RecordedLLMClient):
            raise AssertionError(
                f"Expected a client that keeps a receipt, got "
                f"[{type(client).__name__}].")

        return True

    return assertion


def _keeps_no_receipt() -> Assertion[object]:
    def assertion(client: object) -> bool:
        if isinstance(client, RecordedLLMClient):
            raise AssertionError(
                "Expected the client itself, and got it wrapped in a recorder "
                "with nothing to record to.")

        return True

    return assertion
