"""Changing a flag, and saying what a failure to change one left behind.

The write tier's one act on the flag provider. How the provider is reached, and
how long it takes to show a change, are the adapter's and are pinned in its own
suite; what is left here is the tier's part: the change asked of the provider is
the one the caller asked for, what comes back is the undo the provider's write
produced, and a failure reaches the caller as a refusal saying what it left -
nothing, something it cannot vouch for, or the undo that puts the flag back.

That third is the one worth the most. A write the provider took and nobody saw
evaluating has flipped the flag, and recorded nowhere else it is a flag no
withdrawal would ever touch.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from unittest.mock import Mock, create_autospec

import pytest
from argus_testkit import (
    Scenario,
    all_of,
    attempting,
    calling,
    one_record_was_logged,
    the_answer_was,
    the_error_mentioned,
)
from core.models import FlagUndo
from flag_provider import FlagProviderWrites, FlagWriteFailed
from write_mcp_server.flag_state import FlagNotSet, set_flag

from write_mcp_server_test.framework.refusals import (
    it_left_behind,
    it_was_refused_as,
    what_it_left_is_known,
)

SOME_FLAG = "monthly-spend-feature"
DONT_CARE_FLAG = "dont-care-flag"
DONT_CARE_ENABLED = False

SOME_UNDO = FlagUndo(
    flag=SOME_FLAG,
    was_enabled=True,
    environment="production",
    written_at=datetime(2026, 9, 6, 17, 38, tzinfo=UTC)
)
SOME_PROVIDER_WORDS = "the provider said something about it"


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
def test_the_provider_is_asked_for_the_flag_and_the_state_asked_for(enabled: bool) -> None:
    # Both directions, one tool: a flag causes an incident by changing, and the
    # damaging direction is not always "on".
    Scenario() \
        .given(flags := _a_provider_answering(SOME_UNDO)) \
        .when(lambda: set_flag(SOME_FLAG, enabled, flags)) \
        .then(lambda _: _the_provider_was_asked_to_set(flags, SOME_FLAG, enabled))


@pytest.mark.unit
def test_what_comes_back_is_the_undo_the_providers_write_produced() -> None:
    # Whole, as the provider's write made it: the provider's own time for it is
    # what an undo later asks the history from.
    Scenario() \
        .given(flags := _a_provider_answering(SOME_UNDO)) \
        .when(lambda: set_flag(SOME_FLAG, False, flags)) \
        .then(the_answer_was(SOME_UNDO))


@pytest.mark.unit
def test_a_write_the_provider_never_took_is_refused_as_having_changed_nothing() -> None:
    # Nothing was sent, or what was sent was refused: the flag is as it was, and
    # the refusal says so.
    Scenario() \
        .given(flags := _a_provider_failing(
            FlagWriteFailed(SOME_PROVIDER_WORDS, known_not_applied=True)
        )) \
        .when(attempting(lambda: set_flag(DONT_CARE_FLAG, DONT_CARE_ENABLED, flags))) \
        .then(all_of(
            it_was_refused_as(FlagNotSet),
            what_it_left_is_known(True),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_write_whose_answer_was_lost_is_not_said_to_have_changed_nothing() -> None:
    # The provider may have flipped it. A refusal saying it left nothing would
    # have the record say the flag is as it was.
    Scenario() \
        .given(flags := _a_provider_failing(
            FlagWriteFailed(SOME_PROVIDER_WORDS, known_not_applied=False)
        )) \
        .when(attempting(lambda: set_flag(DONT_CARE_FLAG, DONT_CARE_ENABLED, flags))) \
        .then(all_of(
            it_was_refused_as(FlagNotSet),
            what_it_left_is_known(False),
            it_left_behind(None)
        ))


@pytest.mark.unit
def test_a_write_taken_and_never_seen_in_effect_is_refused_carrying_what_puts_it_back() -> None:
    # The provider took the change, so the flag is flipped whatever evaluation
    # says yet - and the undo is the whole of what it left.
    Scenario() \
        .given(flags := _a_provider_failing(
            FlagWriteFailed(SOME_PROVIDER_WORDS, left_behind=SOME_UNDO)
        )) \
        .when(attempting(lambda: set_flag(SOME_FLAG, False, flags))) \
        .then(all_of(
            it_was_refused_as(FlagNotSet),
            what_it_left_is_known(True),
            it_left_behind(SOME_UNDO)
        ))


@pytest.mark.unit
def test_a_refusal_carries_what_the_provider_said() -> None:
    # The reason is the provider's, and it is what a person reading the
    # incident has to go on.
    Scenario() \
        .given(flags := _a_provider_failing(FlagWriteFailed(SOME_PROVIDER_WORDS))) \
        .when(attempting(lambda: set_flag(DONT_CARE_FLAG, DONT_CARE_ENABLED, flags))) \
        .then(the_error_mentioned(SOME_PROVIDER_WORDS))


@pytest.mark.unit
def test_a_flag_set_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production, and the first line a person reading the write
    # server's log looks for: which flag was switched, and which way.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            flags := _a_provider_answering(SOME_UNDO)
        ) \
        .when(lambda: set_flag(SOME_FLAG, False, flags)) \
        .then(one_record_was_logged(caplog, "write_mcp_server.flag_state", logging.INFO,
                                    "flag set",
                                    values={"flag": SOME_FLAG, "enabled": False}))


def _a_provider_answering(undo: FlagUndo) -> Mock:
    flags: Mock = create_autospec(FlagProviderWrites, instance=True)
    flags.set.return_value = undo

    return flags


def _a_provider_failing(failure: FlagWriteFailed) -> Mock:
    flags: Mock = create_autospec(FlagProviderWrites, instance=True)
    flags.set.side_effect = failure

    return flags


def _the_provider_was_asked_to_set(flags: Mock, flag: str, enabled: bool) -> bool:
    """Read off `call_args` rather than through `assert_called_with`, which does
    not survive a spec built from a `Protocol`: `self` is left on the signature."""
    asked = [call.args for call in flags.set.call_args_list]

    if asked != [(flag, enabled)]:
        raise AssertionError(
            f"Expected the provider to be asked once to set [{flag}] to [{enabled}], "
            f"and it was asked {asked}."
        )

    return True
