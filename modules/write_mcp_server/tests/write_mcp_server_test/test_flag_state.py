"""Planning a flag's change, making it only where nobody has moved the flag since
the plan, and saying what a failure to make one left behind.

The write tier's one act on the flag provider, in two calls. The plan reads the
flag as the provider holds it - through the admin API, never the cached
evaluation - and dates the read by the provider's own clock, changing nothing. A
flag already in the state asked for has nothing left to change, and the plan
refuses it as an exhausted action. A write asked for the state its plan found is
refused as well rather than taken on the caller's word - a plain refusal that
left nothing, since the plan is what says whether the action is spent.

The change is then made over the plan, and a flag's value cannot say whether it
still stands as planned: it is a bool, and two changes put it back where it was.
So the provider's history since the plan's read is what decides, read once and
before the write. The changes to the state the plan found that come before any
move away from it are set aside, whoever made them: the provider dates its read
to the whole second, so a change made a moment before the read is in the history
after it. No change to the flag left is the flag as planned, and it is written
as it always was. Argus's own changes and nobody else's, the last of them
leaving the flag in the state asked for, are the change asked again after its
answer was lost - answered as made, dated by the change that moved the flag
there, and not written twice; the last of them back to the state the plan found
is the flag as planned again, and it is written. Anybody else's is a change
made since, and is refused without a write: writing over it would overwrite a
person's decision - a put-back after Argus's flip included. A change nobody can
attribute, or a history that could not be read, is a question nobody could
answer, and writes nothing.

How the provider is reached, and how long it takes to show a change, are the
adapter's and are pinned in its own suite; what is left here is the tier's part:
the change asked of the provider is the one the caller asked for, what comes back
is the undo the provider's write produced, and a failure reaches the caller as a
refusal saying what it left - nothing, something it cannot vouch for, or the undo
that puts the flag back.

That third is the one worth the most. A write the provider took and nobody saw
evaluating has flipped the flag, and recorded nowhere else it is a flag no
withdrawal would ever touch.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock, create_autospec

import pytest
from argus_testkit import (
    Assertion,
    Scenario,
    all_of,
    attempting,
    calling,
    one_record_was_logged,
    the_answer_was,
    the_error_mentioned,
)
from core import to_iso
from core.models import FlagChange, FlagState, FlagUndo, Planned
from flag_provider import FlagProviderUnavailable, FlagProviderWrites, FlagWriteFailed
from mcp_transport import ToolRefusalKind, ToolRefused
from write_mcp_server.flag_state import (
    FlagNotSet,
    plan_flag,
    set_flag,
    still_argus_s,
    whether_it_was_made,
)

from write_mcp_server_test.framework.refusals import (
    it_left_behind,
    it_was_refused_as,
    its_change_is_said_performed,
    what_it_left_is_known,
)
from write_mcp_server_test.framework.resuming import (
    it_is_still_argus_s,
    it_refused_as_the_write_does,
    it_was_changed_since,
    it_was_made,
    nobody_can_say,
    nothing_landed,
)

SOME_FLAG = "monthly-spend-feature"
SOME_OTHER_FLAG = "recommendations-v2"
DONT_CARE_FLAG = "dont-care-flag"
DONT_CARE_ENABLED = False
# The state a plan finds its flag in, unless a case says otherwise, and the
# state its write asks for - away from it. A change in the histories below moves
# the flag to the state asked for unless the case says otherwise, so every case
# that leaves a change's `to` at its default asks its plan for that state.
SOME_STATE_FOUND = True
THE_STATE_ASKED_FOR = not SOME_STATE_FOUND
# Less than the whole second the provider dates its read to.
SOME_FRACTION_OF_A_SECOND = timedelta(milliseconds=261)

# The provider's own time on its answer to the admin read - what a plan is dated
# by, and what its history is asked from when the change is made.
SOME_READ_AT = datetime(2026, 9, 6, 17, 37, tzinfo=UTC)

SOME_UNDO = FlagUndo(
    flag=SOME_FLAG,
    was_enabled=True,
    environment="production",
    written_at=datetime(2026, 9, 6, 17, 38, tzinfo=UTC)
)
SOME_PROVIDER_WORDS = "the provider said something about it"

# Whose a change in the provider's history was, as its adapter says: `None` where
# nobody can say.
BY_ARGUS = True
BY_SOMEBODY_ELSE = False
BY_NOBODY_ANYONE_CAN_NAME = None

# Moments in the history, ordered as named, every one inside the window it is
# asked from - which opens at the plan's read, dated to the whole second, so a
# change in that second may have come before the read.
SOME_EARLIER_OTHER_CHANGE_AT = SOME_READ_AT + timedelta(minutes=1)
SOME_ARGUS_CHANGE_AT = SOME_EARLIER_OTHER_CHANGE_AT + timedelta(minutes=1)
SOME_LATER_ARGUS_CHANGE_AT = SOME_ARGUS_CHANGE_AT + timedelta(minutes=1)
SOME_OTHER_CHANGE_AT = SOME_LATER_ARGUS_CHANGE_AT + timedelta(minutes=1)
SOME_LAST_ARGUS_CHANGE_AT = SOME_OTHER_CHANGE_AT + timedelta(minutes=1)

NOTHING_CHANGED: list[FlagChange] = []


def _a_change(flag: str, by: bool | None, at: datetime,
              to: bool = THE_STATE_ASKED_FOR) -> FlagChange:
    """One change in the provider's history, as its adapter reads it: which flag,
    which state it moved the flag `to`, when by the provider's clock, and whether
    it was Argus's.

    Up here rather than among the helpers below, because a parametrized case
    builds its history when the module is read."""
    return FlagChange(flag=flag, enabled=to, occurred_at=to_iso(at), made_by_argus=by)


@pytest.mark.unit
@pytest.mark.parametrize("found", [False, True], ids=["off", "on"])
def test_a_plan_records_the_state_the_admin_read_found(found: bool) -> None:
    # The state the flag is in, never the opposite of the one asked for: a flag
    # somebody already moved is planned from where it is, and put back there.
    # Nothing is written, so nothing is dated.
    Scenario() \
        .given(flags := _a_provider_reading(found)) \
        .when(lambda: plan_flag(SOME_FLAG, not found, flags)) \
        .then(_the_plan_puts_back(SOME_FLAG, found))


@pytest.mark.unit
@pytest.mark.parametrize("found", [False, True], ids=["off", "on"])
def test_a_plan_finding_the_flag_already_in_the_state_asked_for_is_refused_as_exhausted(
        found: bool) -> None:
    # A flag already where it was asked to go has nothing left to change.
    # Refused rather than planned as a no-op: a caller told it was done would
    # record a mitigation that never happened and judge the service against it,
    # and the action spent is what lets the walk move on to another candidate.
    Scenario() \
        .given(flags := _a_provider_reading(found)) \
        .when(attempting(lambda: plan_flag(SOME_FLAG, found, flags))) \
        .then(all_of(
            it_was_refused_as(FlagNotSet),
            _the_refusal_says_the_action_is_exhausted(),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
def test_a_plan_is_dated_by_the_providers_own_time_for_the_read() -> None:
    # The provider's clock, not this process's: the history the change is later
    # made over is stamped by the provider, and two clocks compared hide
    # whatever they disagree by.
    Scenario() \
        .given(flags := _a_provider_reading(DONT_CARE_ENABLED, read_at=SOME_READ_AT)) \
        .when(lambda: plan_flag(DONT_CARE_FLAG, not DONT_CARE_ENABLED, flags)) \
        .then(_the_plan_is_dated(SOME_READ_AT))


@pytest.mark.unit
def test_a_plan_reads_the_flag_through_the_admin_api_and_not_the_evaluation() -> None:
    # Evaluation is cached and says only which flags are on; the admin read is
    # the provider's own record of the flag.
    Scenario() \
        .given(flags := _a_provider_reading(DONT_CARE_ENABLED)) \
        .when(lambda: plan_flag(SOME_FLAG, not DONT_CARE_ENABLED, flags)) \
        .then(all_of(
            _the_admin_read_was_asked_for(flags, SOME_FLAG),
            _the_evaluation_was_never_read(flags)
        ))


@pytest.mark.unit
def test_a_plan_changes_nothing() -> None:
    Scenario() \
        .given(flags := _a_provider_reading(DONT_CARE_ENABLED)) \
        .when(lambda: plan_flag(DONT_CARE_FLAG, not DONT_CARE_ENABLED, flags)) \
        .then(_nothing_was_written(flags))


@pytest.mark.unit
def test_a_plan_whose_read_failed_is_refused_as_having_changed_nothing() -> None:
    # Nothing was asked to change, and the refusal says so in the provider's
    # words.
    Scenario() \
        .given(flags := _a_provider_whose_read_fails(
            FlagProviderUnavailable(SOME_PROVIDER_WORDS)
        )) \
        .when(attempting(lambda: plan_flag(DONT_CARE_FLAG, DONT_CARE_ENABLED, flags))) \
        .then(all_of(
            it_was_refused_as(FlagNotSet),
            what_it_left_is_known(True),
            it_left_behind(None),
            the_error_mentioned(SOME_PROVIDER_WORDS),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
def test_a_flag_nobody_changed_since_the_plan_is_asked_of_the_provider_in_the_state_asked_for(
        enabled: bool) -> None:
    # Both directions, one tool: a flag causes an incident by changing, and the
    # damaging direction is not always "on".
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(NOTHING_CHANGED)) \
        .when(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=not enabled), enabled, flags)) \
        .then(lambda _: _the_provider_was_asked_to_set(flags, SOME_FLAG, enabled))


@pytest.mark.unit
@pytest.mark.parametrize("by", [BY_SOMEBODY_ELSE, BY_NOBODY_ANYONE_CAN_NAME],
                         ids=["somebody-else", "nobody-anyone-can-name"])
def test_a_change_to_another_flag_since_the_plan_does_not_hold_the_write_back(
        by: bool | None) -> None:
    # The history is the environment's, every flag in it; only the flag being
    # changed has a say in whether its plan still stands.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(SOME_OTHER_FLAG, by=by, at=SOME_OTHER_CHANGE_AT)
        ])) \
        .when(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND),
                               THE_STATE_ASKED_FOR, flags)) \
        .then(lambda _: _the_provider_was_asked_to_set(flags, SOME_FLAG, THE_STATE_ASKED_FOR))


@pytest.mark.unit
@pytest.mark.parametrize("enabled", [False, True], ids=["off", "on"])
def test_a_change_to_the_state_the_plan_found_is_refused_before_anything_is_asked(
        enabled: bool) -> None:
    # The plan refuses a change to where the flag already is, and the write does
    # not take it on the caller's word: written, it would change nothing and be
    # answered as a mitigation made. Refused before the history is read, so the
    # refusal says it left nothing.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(NOTHING_CHANGED)) \
        .when(attempting(lambda: set_flag(
            _a_plan(DONT_CARE_FLAG, was_enabled=enabled), enabled, flags
        ))) \
        .then(all_of(
            it_was_refused_as(FlagNotSet),
            _it_is_refused_as_changed_since(False),
            what_it_left_is_known(True),
            it_left_behind(None),
            _nothing_was_asked_of_the_provider(flags)
        ))


@pytest.mark.unit
def test_what_comes_back_is_the_undo_the_providers_write_produced() -> None:
    # Whole, as the provider's write made it: the provider's own time for it is
    # what an undo later asks the history from.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(NOTHING_CHANGED,
                                                                    answering=SOME_UNDO)) \
        .when(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND),
                               THE_STATE_ASKED_FOR, flags)) \
        .then(the_answer_was(SOME_UNDO))


@pytest.mark.unit
def test_a_flag_argus_alone_changed_since_the_plan_is_answered_as_made_and_not_written() -> None:
    # The change asked again after its first answer was lost: it landed, and
    # writing it twice would put a second change in the provider's history that
    # nobody asked for. What comes back still puts the flag back where the plan
    # found it, dated by the provider's time for the first of Argus's changes -
    # the one that moved the flag off the plan, and what an undo later asks the
    # history from. Dated by a later one, the undo would take that first change
    # for somebody else's.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_LATER_ARGUS_CHANGE_AT)
        ])) \
        .when(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND),
                               THE_STATE_ASKED_FOR, flags)) \
        .then(all_of(
            _nothing_was_written(flags),
            _it_puts_back(SOME_FLAG, SOME_STATE_FOUND, written_at=SOME_ARGUS_CHANGE_AT)
        ))


@pytest.mark.unit
@pytest.mark.parametrize("by", [BY_ARGUS, BY_SOMEBODY_ELSE, BY_NOBODY_ANYONE_CAN_NAME],
                         ids=["argus", "somebody-else", "nobody-anyone-can-name"])
def test_a_change_to_the_state_the_plan_found_within_its_second_does_not_hold_the_write_back(
        by: bool | None) -> None:
    # The provider dates its read to the whole second, so a change made a moment
    # before the read sits in the history after it. It is the state the plan
    # read, not a move off it: a put-back made in the second Argus's own change
    # landed found that change, took it for the put-back already made, and left
    # the flag where the incident had moved it.
    a_moment_before_the_read = SOME_READ_AT + SOME_FRACTION_OF_A_SECOND

    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(SOME_FLAG, by=by, at=a_moment_before_the_read, to=SOME_STATE_FOUND)
        ])) \
        .when(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND),
                               THE_STATE_ASKED_FOR, flags)) \
        .then(lambda _: _the_provider_was_asked_to_set(flags, SOME_FLAG, THE_STATE_ASKED_FOR))


@pytest.mark.unit
def test_argus_s_change_to_the_state_the_plan_found_before_its_flip_dates_the_flip_by_the_flip(
) -> None:
    # The change to where the plan found the flag came before the read, and is
    # the read's past: the flip that follows is the one already made, dated by
    # its own time.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_READ_AT, to=SOME_STATE_FOUND),
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT)
        ])) \
        .when(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND),
                               THE_STATE_ASKED_FOR, flags)) \
        .then(all_of(
            _nothing_was_written(flags),
            _it_puts_back(SOME_FLAG, SOME_STATE_FOUND, written_at=SOME_ARGUS_CHANGE_AT)
        ))


@pytest.mark.unit
def test_a_flip_argus_s_own_change_put_back_is_written_again() -> None:
    # Argus's flip, then Argus's own change back to where the plan found the
    # flag: the flip no longer stands, so it is not answered as made - the flag
    # is where the plan found it, and the change asked for is written.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_LATER_ARGUS_CHANGE_AT, to=SOME_STATE_FOUND)
        ])) \
        .when(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND),
                               THE_STATE_ASKED_FOR, flags)) \
        .then(lambda _: _the_provider_was_asked_to_set(flags, SOME_FLAG, THE_STATE_ASKED_FOR))


@pytest.mark.unit
def test_a_flip_argus_made_again_after_its_own_put_back_is_answered_as_made_dated_by_the_last(
) -> None:
    # Argus's flip, Argus's own change back to where the plan found the flag,
    # and Argus's flip again: the first flip no longer stands, and the flag is
    # where the last one moved it - so that one dates the change made, and is
    # what an undo later asks the history from.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_LATER_ARGUS_CHANGE_AT, to=SOME_STATE_FOUND),
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_LAST_ARGUS_CHANGE_AT)
        ])) \
        .when(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND),
                               THE_STATE_ASKED_FOR, flags)) \
        .then(all_of(
            _nothing_was_written(flags),
            _it_puts_back(SOME_FLAG, SOME_STATE_FOUND, written_at=SOME_LAST_ARGUS_CHANGE_AT)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    ("history", "left_behind", "performed"),
    [
        ([_a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT)], None, False),
        ([_a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
          _a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT)],
         FlagUndo(flag=SOME_FLAG, was_enabled=SOME_STATE_FOUND, written_at=SOME_READ_AT), True),
        ([_a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_EARLIER_OTHER_CHANGE_AT),
          _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT)],
         FlagUndo(flag=SOME_FLAG, was_enabled=SOME_STATE_FOUND, written_at=SOME_READ_AT), True),
        # Argus's flip landed and its answer was lost, and a person put the
        # flag back before Argus asked again: their change is to where the plan
        # found the flag, and it is still their decision.
        ([_a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
          _a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT,
                    to=SOME_STATE_FOUND)],
         FlagUndo(flag=SOME_FLAG, was_enabled=SOME_STATE_FOUND, written_at=SOME_READ_AT), True),
        ([_a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_EARLIER_OTHER_CHANGE_AT),
          _a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT,
                    to=SOME_STATE_FOUND)],
         None, False)
    ],
    ids=["alone", "after-argus", "before-argus", "put-back-after-argus", "away-and-back"]
)
def test_a_flag_somebody_else_changed_since_the_plan_is_refused_as_changed_since(
        history: list[FlagChange], left_behind: FlagUndo | None, performed: bool) -> None:
    # Somebody's decision, made after Argus read the flag - whichever side of
    # Argus's own change it landed. Writing over it would overwrite them. Where
    # Argus's own flip landed too, that change is what the refusal leaves
    # behind, so a withdrawal can find it - dated by the plan's read, not by
    # Argus's change: a put-back asks the history from that date, and dated
    # later it would miss a person's change made before Argus's and write over
    # the flag they left. And it says the change was performed: a flag has no
    # suspension before its write, so Argus's flip that landed is the change.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(history)) \
        .when(attempting(lambda: set_flag(
            _a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND, since=SOME_READ_AT),
            THE_STATE_ASKED_FOR, flags
        ))) \
        .then(all_of(
            it_was_refused_as(FlagNotSet),
            _it_is_refused_as_changed_since(True),
            what_it_left_is_known(True),
            it_left_behind(left_behind),
            its_change_is_said_performed(performed),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
def test_a_flag_whose_change_nobody_could_attribute_is_refused_as_changing_nothing() -> None:
    # The change may be Argus's own, landed, or somebody's decision: a write may
    # overwrite them, and an answer as made may stand on their change rather
    # than Argus's. Nobody could say which, so it is not said to be either.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(DONT_CARE_FLAG, by=BY_NOBODY_ANYONE_CAN_NAME, at=SOME_OTHER_CHANGE_AT,
                      to=DONT_CARE_ENABLED)
        ])) \
        .when(attempting(lambda: set_flag(
            _a_plan(DONT_CARE_FLAG, was_enabled=not DONT_CARE_ENABLED), DONT_CARE_ENABLED, flags
        ))) \
        .then(all_of(
            it_was_refused_as(FlagNotSet),
            _it_is_refused_as_changed_since(False),
            what_it_left_is_known(True),
            it_left_behind(None),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
def test_a_flag_whose_history_could_not_be_read_is_refused_as_changing_nothing() -> None:
    # Unread, Argus's own earlier change may have landed, and so may somebody
    # else's; writing would make the one twice or overwrite the other. The
    # refusal says so in the provider's words.
    Scenario() \
        .given(flags := _a_provider_whose_history_fails(
            FlagProviderUnavailable(SOME_PROVIDER_WORDS)
        )) \
        .when(attempting(lambda: set_flag(
            _a_plan(DONT_CARE_FLAG, was_enabled=not DONT_CARE_ENABLED), DONT_CARE_ENABLED, flags
        ))) \
        .then(all_of(
            it_was_refused_as(FlagNotSet),
            what_it_left_is_known(True),
            it_left_behind(None),
            the_error_mentioned(SOME_PROVIDER_WORDS),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
def test_the_history_is_read_once_from_the_plans_read_and_before_the_write() -> None:
    # From the provider's own time for the plan's read, not this process's
    # clock; before the write, or the write would be its own evidence; and once,
    # so every verdict is drawn from one answer rather than from two the flag
    # may have moved between.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(NOTHING_CHANGED)) \
        .when(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND, since=SOME_READ_AT),
                               THE_STATE_ASKED_FOR, flags)) \
        .then(_the_history_was_read_once_before_the_write(flags, SOME_READ_AT))


@pytest.mark.unit
def test_a_change_is_never_made_over_the_evaluation() -> None:
    # Evaluation says what a flag is, never whose it is.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(NOTHING_CHANGED)) \
        .when(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND),
                               THE_STATE_ASKED_FOR, flags)) \
        .then(_the_evaluation_was_never_read(flags))


@pytest.mark.unit
def test_a_write_the_provider_never_took_is_refused_as_having_changed_nothing() -> None:
    # Nothing was sent, or what was sent was refused: the flag is as it was, and
    # the refusal says so.
    Scenario() \
        .given(flags := _a_provider_whose_write_fails(
            FlagWriteFailed(SOME_PROVIDER_WORDS, known_not_applied=True)
        )) \
        .when(attempting(lambda: set_flag(
            _a_plan(DONT_CARE_FLAG, was_enabled=not DONT_CARE_ENABLED), DONT_CARE_ENABLED, flags
        ))) \
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
        .given(flags := _a_provider_whose_write_fails(
            FlagWriteFailed(SOME_PROVIDER_WORDS, known_not_applied=False)
        )) \
        .when(attempting(lambda: set_flag(
            _a_plan(DONT_CARE_FLAG, was_enabled=not DONT_CARE_ENABLED), DONT_CARE_ENABLED, flags
        ))) \
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
        .given(flags := _a_provider_whose_write_fails(
            FlagWriteFailed(SOME_PROVIDER_WORDS, left_behind=SOME_UNDO)
        )) \
        .when(attempting(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND),
                                          THE_STATE_ASKED_FOR, flags))) \
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
        .given(flags := _a_provider_whose_write_fails(FlagWriteFailed(SOME_PROVIDER_WORDS))) \
        .when(attempting(lambda: set_flag(
            _a_plan(DONT_CARE_FLAG, was_enabled=not DONT_CARE_ENABLED), DONT_CARE_ENABLED, flags
        ))) \
        .then(the_error_mentioned(SOME_PROVIDER_WORDS))


@pytest.mark.unit
def test_a_flag_set_is_logged(caplog: pytest.LogCaptureFixture) -> None:
    # A change to production, and the first line a person reading the write
    # server's log looks for: which flag was switched, and which way.
    Scenario() \
        .given(
            calling(lambda: caplog.set_level(logging.INFO)),
            flags := _a_provider_whose_history_since_the_plan_is(NOTHING_CHANGED)
        ) \
        .when(lambda: set_flag(_a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND),
                               THE_STATE_ASKED_FOR, flags)) \
        .then(one_record_was_logged(caplog, "write_mcp_server.flag_state", logging.INFO,
                                    "flag set",
                                    values={"flag": SOME_FLAG, "enabled": THE_STATE_ASKED_FOR}))


def _a_plan(flag: str, was_enabled: bool, since: datetime = SOME_READ_AT) -> Planned[FlagUndo]:
    """A plan as `plan_flag` makes it: what the flag was found in, nothing
    written yet to date or place it, and the provider's time for the read."""
    return Planned[FlagUndo](descriptor=FlagUndo(flag=flag, was_enabled=was_enabled),
                             since=since)


def _a_provider_reading(enabled: bool, read_at: datetime = SOME_READ_AT) -> Mock:
    flags: Mock = create_autospec(FlagProviderWrites, instance=True)
    flags.state_of.return_value = FlagState(enabled=enabled, read_at=read_at)

    return flags


def _a_provider_whose_read_fails(failure: FlagProviderUnavailable) -> Mock:
    flags: Mock = create_autospec(FlagProviderWrites, instance=True)
    flags.state_of.side_effect = failure

    return flags


def _a_provider_whose_history_since_the_plan_is(changes: list[FlagChange],
                                                answering: FlagUndo = SOME_UNDO) -> Mock:
    flags: Mock = create_autospec(FlagProviderWrites, instance=True)
    flags.changes_since.return_value = changes
    flags.set.return_value = answering

    return flags


def _a_provider_whose_history_fails(failure: FlagProviderUnavailable) -> Mock:
    flags: Mock = create_autospec(FlagProviderWrites, instance=True)
    flags.changes_since.side_effect = failure

    return flags


def _a_provider_whose_write_fails(failure: FlagWriteFailed) -> Mock:
    flags: Mock = create_autospec(FlagProviderWrites, instance=True)
    flags.changes_since.return_value = NOTHING_CHANGED
    flags.set.side_effect = failure

    return flags


def _the_plan_puts_back(flag: str, was_enabled: bool) -> Assertion[Planned[FlagUndo]]:
    def assertion(plan: Planned[FlagUndo]) -> bool:
        wanted = {"flag": flag, "was_enabled": was_enabled, "written_at": None}
        wrong = {
            field: (expected, getattr(plan.descriptor, field))
            for field, expected in wanted.items()
            if getattr(plan.descriptor, field) != expected
        }

        if wrong:
            raise AssertionError(
                f"Expected the plan's descriptor to hold {wanted}, and {wrong} differed "
                f"(expected, got): {plan.descriptor!r}"
            )

        return True

    return assertion


def _the_plan_is_dated(since: datetime) -> Assertion[Planned[FlagUndo]]:
    def assertion(plan: Planned[FlagUndo]) -> bool:
        if plan.since != since:
            raise AssertionError(
                f"Expected the plan dated [{since}], the provider's time for the read, "
                f"got [{plan.since}]."
            )

        return True

    return assertion


def _it_puts_back(flag: str, was_enabled: bool, written_at: datetime) -> Assertion[FlagUndo]:
    """What a put-back does, and the time its history is later asked from."""
    def assertion(undo: FlagUndo) -> bool:
        wanted = {"flag": flag, "was_enabled": was_enabled, "written_at": written_at}
        wrong = {
            field: (expected, getattr(undo, field))
            for field, expected in wanted.items()
            if getattr(undo, field) != expected
        }

        if wrong:
            raise AssertionError(
                f"Expected an undo holding {wanted}, and {wrong} differed (expected, got): "
                f"{undo!r}"
            )

        return True

    return assertion


def _it_is_refused_as_changed_since(expected: bool) -> Assertion[object]:
    """Both ways: a refusal of a change nobody could attribute is not a change
    somebody else made, and the walk does something different with each."""
    def assertion(raised: object) -> bool:
        kind = raised.refusal.kind if isinstance(raised, ToolRefused) else None

        if (kind is ToolRefusalKind.CHANGED_SINCE) is not expected:
            raise AssertionError(
                f"Expected the refusal {'' if expected else 'not '}to say the flag was "
                f"changed since it was read, and it was a [{kind}] refusal: [{raised}]."
            )

        return True

    return assertion


def _the_refusal_says_the_action_is_exhausted() -> Assertion[object]:
    """Asserted against the kind rather than the sentence, because the
    sentence is allowed to change and the kind is not."""
    def assertion(raised: object) -> bool:
        kind = raised.refusal.kind if isinstance(raised, ToolRefused) else None

        if kind is not ToolRefusalKind.EXHAUSTED:
            raise AssertionError(
                f"Expected the refusal to be [{ToolRefusalKind.EXHAUSTED}], so that a "
                f"caller can tell a spent action from a broken provider, and it was "
                f"[{kind}]: [{raised}]."
            )

        return True

    return assertion


def _the_admin_read_was_asked_for(flags: Mock, flag: str) -> Assertion[object]:
    """Read off `call_args` for the reason `_the_provider_was_asked_to_set` gives."""
    def assertion(dont_care_answer: object) -> bool:
        asked = [call.args for call in flags.state_of.call_args_list]

        if asked != [(flag,)]:
            raise AssertionError(
                f"Expected the provider's admin read asked once for [{flag}], and it was "
                f"asked {asked}."
            )

        return True

    return assertion


def _the_history_was_read_once_before_the_write(flags: Mock,
                                                since: datetime) -> Assertion[object]:
    """Read off `method_calls`, in the order they were made, for the reason
    `_the_provider_was_asked_to_set` gives about `assert_called_with`."""
    def assertion(dont_care_answer: object) -> bool:
        asked = [(name, call_args) for name, call_args, _ in flags.method_calls]
        write_at = next((index for index, (name, _) in enumerate(asked) if name == "set"),
                        len(asked))
        expected_before_the_write = [("changes_since", (since,))]

        if asked[:write_at] != expected_before_the_write:
            raise AssertionError(
                f"Expected the provider's history read once, since [{since}], and nothing "
                f"else asked before the write, and it was asked {asked}"
            )

        return True

    return assertion


def _the_evaluation_was_never_read(flags: Mock) -> Assertion[object]:
    def assertion(dont_care_answer: object) -> bool:
        if flags.enabled.called:
            raise AssertionError(
                f"Expected the evaluation never read, and it was read "
                f"[{flags.enabled.call_count}] times."
            )

        return True

    return assertion


def _nothing_was_written(flags: Mock) -> Assertion[object]:
    def assertion(dont_care_answer: object) -> bool:
        written = [call.args for call in flags.set.call_args_list]

        if written:
            raise AssertionError(f"Expected nothing written, and the provider was asked {written}.")

        return True

    return assertion


def _nothing_was_asked_of_the_provider(flags: Mock) -> Assertion[object]:
    def assertion(dont_care_answer: object) -> bool:
        asked = [name for name, _, _ in flags.method_calls]

        if asked:
            raise AssertionError(
                f"Expected nothing read or written, and the provider was asked {asked}."
            )

        return True

    return assertion


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


# The plan the claim carries: the flag found, read at the provider's time.
# Whether its flip was made, and whether that flip is still Argus's, are both
# asked of the provider's history from this read - the write's own.
THE_CLAIM_S_PLAN = _a_plan(SOME_FLAG, was_enabled=SOME_STATE_FOUND, since=SOME_READ_AT)
# The flip Argus made, as the row recorded it: what puts it back, dated by the
# provider's own time for Argus's change.
ARGUS_S_FLIP = THE_CLAIM_S_PLAN.descriptor.model_copy(
    update={"written_at": SOME_ARGUS_CHANGE_AT}
)


@pytest.mark.unit
@pytest.mark.parametrize(
    "history",
    [
        [_a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT)],
        [_a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
         _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_LATER_ARGUS_CHANGE_AT)],
        [_a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
         _a_change(SOME_OTHER_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT)]
    ],
    ids=["argus-s-own-flip", "argus-s-alone", "another-flag-changed-too"]
)
def test_a_flag_only_argus_changed_since_the_plan_is_still_argus_s(
        history: list[FlagChange]) -> None:
    # The write's own rule, read and not acted on, over its own one read of the
    # history from the plan's read: Argus's own changes are its own, and another
    # flag's are nobody's concern here.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(history)) \
        .when(lambda: still_argus_s(THE_CLAIM_S_PLAN, ARGUS_S_FLIP, flags)) \
        .then(all_of(
            it_is_still_argus_s(),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "history",
    [
        NOTHING_CHANGED,
        [_a_change(SOME_OTHER_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT)]
    ],
    ids=["nothing-since", "only-another-flag-changed"]
)
def test_a_flag_with_no_change_since_the_plan_contradicts_the_row_and_is_nobody_s_to_say(
        history: list[FlagChange]) -> None:
    # The row says Argus's flip was made, and the provider records no change to
    # the flag since the plan - not even Argus's own. One of the two is wrong,
    # and which cannot be said: not "still Argus's", which would watch a change
    # the provider has no record of.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(history)) \
        .when(lambda: still_argus_s(THE_CLAIM_S_PLAN, ARGUS_S_FLIP, flags)) \
        .then(all_of(
            nobody_can_say(),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "history",
    [
        [_a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT)],
        [_a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
         _a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT)],
        # A person putting the flag back after Argus's flip has decided
        # something, though their change is to where the plan found it.
        [_a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
         _a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT,
                   to=SOME_STATE_FOUND)]
    ],
    ids=["alone", "after-argus", "put-back-after-argus"]
)
def test_a_flag_somebody_else_changed_since_the_plan_is_a_change_since(
        history: list[FlagChange]) -> None:
    # Somebody's decision, made since the plan: what the service does now is no
    # longer Argus's change to answer for. What was found names the flag.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(history)) \
        .when(lambda: still_argus_s(THE_CLAIM_S_PLAN, ARGUS_S_FLIP, flags)) \
        .then(all_of(
            it_was_changed_since(f"[{SOME_FLAG}]"),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
def test_a_flag_whose_only_change_since_the_plan_is_to_the_state_it_found_contradicts_the_row(
) -> None:
    # Argus's own change to where the plan found the flag, within the plan's
    # second, is no flip of the claim's: the row says the flip landed and the
    # provider records none - which is nobody's to say, not still Argus's.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_READ_AT,
                      to=THE_CLAIM_S_PLAN.descriptor.was_enabled)
        ])) \
        .when(lambda: still_argus_s(THE_CLAIM_S_PLAN, ARGUS_S_FLIP, flags)) \
        .then(nobody_can_say())


@pytest.mark.unit
def test_a_flag_whose_change_since_nobody_could_attribute_is_nobody_s_to_say() -> None:
    # It may be Argus's own, or somebody's decision: not said to be either.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(SOME_FLAG, by=BY_NOBODY_ANYONE_CAN_NAME, at=SOME_OTHER_CHANGE_AT)
        ])) \
        .when(lambda: still_argus_s(THE_CLAIM_S_PLAN, ARGUS_S_FLIP, flags)) \
        .then(all_of(
            nobody_can_say(),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
def test_a_flag_whose_history_could_not_be_read_is_nobody_s_to_say() -> None:
    # Not "still Argus's": a history never read found nobody, which is not the
    # same as nobody being there.
    Scenario() \
        .given(flags := _a_provider_whose_history_fails(
            FlagProviderUnavailable(SOME_PROVIDER_WORDS)
        )) \
        .when(lambda: still_argus_s(THE_CLAIM_S_PLAN, ARGUS_S_FLIP, flags)) \
        .then(all_of(
            nobody_can_say(),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
def test_a_flip_recorded_a_moment_before_the_time_its_answer_carried_is_still_argus_s(
) -> None:
    # The provider records the toggle before it answers the write, and the
    # answer is dated to the whole second: Argus's own event can sit a fraction
    # before the flip's recorded time. Read from the plan's own moment, as the
    # write reads it, it is found - and read from the flip's time, it would not
    # be, and the flip would contradict its own row.
    the_answer_s_whole_second = SOME_ARGUS_CHANGE_AT
    argus_s_event = the_answer_s_whole_second - SOME_FRACTION_OF_A_SECOND

    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(SOME_FLAG, by=BY_ARGUS, at=argus_s_event)
        ])) \
        .when(lambda: still_argus_s(THE_CLAIM_S_PLAN, ARGUS_S_FLIP, flags)) \
        .then(it_is_still_argus_s())


@pytest.mark.unit
def test_whether_a_flag_is_still_argus_s_is_read_once_from_the_plans_read() -> None:
    # From the provider's own time for the plan's read - the write's own read,
    # on the history's own clock - and once, so the answer is drawn from one
    # reading of it.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(NOTHING_CHANGED)) \
        .when(lambda: still_argus_s(THE_CLAIM_S_PLAN, ARGUS_S_FLIP, flags)) \
        .then(_the_history_was_read_once_before_the_write(flags, SOME_READ_AT))


@pytest.mark.unit
def test_a_flip_argus_alone_made_since_the_plan_is_found_made_and_dated_by_the_first() -> None:
    # The first of Argus's changes is the one that moved the flag off the plan,
    # and what a put-back later asks the history from - so it dates the flip,
    # and the walk's record of when it was made.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_LATER_ARGUS_CHANGE_AT)
        ])) \
        .when(lambda: whether_it_was_made(THE_CLAIM_S_PLAN, flags)) \
        .then(all_of(
            it_was_made(
                THE_CLAIM_S_PLAN.descriptor.model_copy(update={"written_at": SOME_ARGUS_CHANGE_AT}),
                made_at=SOME_ARGUS_CHANGE_AT
            ),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
def test_a_flip_argus_made_again_after_its_own_put_back_is_found_made_and_dated_by_the_last(
) -> None:
    # The write's own rule: the flip that stands is the last, so it dates the
    # flip, and the walk's record of when it was made.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is([
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_LATER_ARGUS_CHANGE_AT, to=SOME_STATE_FOUND),
            _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_LAST_ARGUS_CHANGE_AT)
        ])) \
        .when(lambda: whether_it_was_made(THE_CLAIM_S_PLAN, flags)) \
        .then(all_of(
            it_was_made(
                THE_CLAIM_S_PLAN.descriptor.model_copy(
                    update={"written_at": SOME_LAST_ARGUS_CHANGE_AT}
                ),
                made_at=SOME_LAST_ARGUS_CHANGE_AT
            ),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "history",
    [
        NOTHING_CHANGED,
        [_a_change(SOME_OTHER_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT)],
        [_a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_READ_AT,
                   to=THE_CLAIM_S_PLAN.descriptor.was_enabled)]
    ],
    ids=["nothing-since", "only-another-flag-changed", "only-to-the-state-it-found"]
)
def test_a_flag_nobody_changed_since_the_plan_has_nothing_landed(
        history: list[FlagChange]) -> None:
    # The claim was written and the flip never reached the provider: the walk
    # makes it, as the live walk would - and nothing is written by asking.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(history)) \
        .when(lambda: whether_it_was_made(THE_CLAIM_S_PLAN, flags)) \
        .then(all_of(
            nothing_landed(),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
@pytest.mark.parametrize(
    "history",
    [
        [_a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT)],
        [_a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
         _a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT)],
        [_a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_EARLIER_OTHER_CHANGE_AT),
         _a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT)],
        [_a_change(SOME_FLAG, by=BY_ARGUS, at=SOME_ARGUS_CHANGE_AT),
         _a_change(SOME_FLAG, by=BY_SOMEBODY_ELSE, at=SOME_OTHER_CHANGE_AT,
                   to=SOME_STATE_FOUND)],
        [_a_change(SOME_FLAG, by=BY_NOBODY_ANYONE_CAN_NAME, at=SOME_OTHER_CHANGE_AT)]
    ],
    ids=["somebody-else-alone", "somebody-else-after-argus", "somebody-else-before-argus",
         "somebody-else-put-back-after-argus", "nobody-can-say-whose"]
)
def test_a_flag_changed_since_the_plan_by_anybody_else_is_refused_as_the_write_refuses_it(
        history: list[FlagChange]) -> None:
    # The same history, the same answer: changed since - saying whether Argus's
    # flip landed among it, and leaving behind what the write would - or, where
    # nobody can say whose a change was, refused as nothing the write could
    # establish.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(history)) \
        .when(attempting(lambda: whether_it_was_made(THE_CLAIM_S_PLAN, flags))) \
        .then(all_of(
            it_was_refused_as(FlagNotSet),
            it_refused_as_the_write_does(
                lambda: set_flag(THE_CLAIM_S_PLAN, THE_STATE_ASKED_FOR, flags)
            ),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
def test_a_flag_whose_history_could_not_be_read_is_refused_as_the_write_refuses_it() -> None:
    Scenario() \
        .given(flags := _a_provider_whose_history_fails(
            FlagProviderUnavailable(SOME_PROVIDER_WORDS)
        )) \
        .when(attempting(lambda: whether_it_was_made(THE_CLAIM_S_PLAN, flags))) \
        .then(all_of(
            it_was_refused_as(FlagNotSet),
            it_refused_as_the_write_does(
                lambda: set_flag(THE_CLAIM_S_PLAN, THE_STATE_ASKED_FOR, flags)
            ),
            _nothing_was_written(flags)
        ))


@pytest.mark.unit
def test_whether_a_flip_was_made_is_read_once_from_the_plans_read() -> None:
    # The write's own read: from the provider's time for the plan's read, once.
    Scenario() \
        .given(flags := _a_provider_whose_history_since_the_plan_is(NOTHING_CHANGED)) \
        .when(lambda: whether_it_was_made(THE_CLAIM_S_PLAN, flags)) \
        .then(_the_history_was_read_once_before_the_write(flags, SOME_READ_AT))
