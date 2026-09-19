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

And one thing that is not about the client at all: what it costs to name the
door this is exported from. That is `building.py`'s property - it is the
module that decides when the adapter is reached - and it is here because a
separation stated in a docstring and checked by nothing is a separation that
was quietly undone once already.
"""

from __future__ import annotations

import subprocess
import sys

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


@pytest.mark.component
def test_naming_the_front_door_does_not_import_a_vendor() -> None:
    # The separation this module's docstring claims, asked rather than
    # asserted in prose. It was claimed and untrue for as long as the adapter
    # was named at the top of `building.py`: `argus_core.llm` re-exports
    # `build_llm_client`, so naming the interface cost every caller 0.6
    # seconds of Anthropic SDK. Nothing failed, because nothing asked.
    #
    # Not vacuous in an environment without the SDK: `llm/adapters/
    # test_caching.py` imports `anthropic` outright, so a suite that could
    # pass this by having none would fail there first.
    Scenario() \
        .given(
            naming_the_front_door := "import argus_core.llm"
        ) \
        .when(
            lambda: _the_modules_a_fresh_interpreter_has_after(naming_the_front_door)
        ) \
        .then(
            _nothing_imported("anthropic")
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


def _the_modules_a_fresh_interpreter_has_after(naming: str) -> set[str]:
    """Everything in `sys.modules` of a new interpreter that has run this.

    A subprocess rather than a snapshot of this one. The suite imported the
    adapter long before this test ran - in the three files whose subject it is
    - and an import that has already happened cannot be watched not happening.
    """
    reading_them_back = "import sys; print(' '.join(sys.modules))"
    finished = subprocess.run(
        [sys.executable, "-c", f"{naming}; {reading_them_back}"],
        capture_output=True,
        text=True,
        check=True
    )

    return set(finished.stdout.split())


def _nothing_imported(vendor: str) -> Assertion[set[str]]:
    def assertion(imported: set[str]) -> bool:
        if vendor in imported:
            raise AssertionError(
                f"Expected naming the front door to leave [{vendor}] unimported, "
                f"and {len(imported)} modules were loaded including it."
            )

        return True

    return assertion
