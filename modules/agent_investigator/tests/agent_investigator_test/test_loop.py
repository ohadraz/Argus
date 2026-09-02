from __future__ import annotations

from typing import Any
from unittest.mock import Mock

import pytest
from agent_investigator import Findings, Reading
from argus_core.events import RetrievalChannel
from argus_core.ids import new_id
from argus_core.models.attempt import Attempt
from argus_core.models.transcript import Ask
from argus_testkit import Assertion, Scenario, all_of

from .framework.builders.budget import (
    a_budget,
    a_clock_that_runs_out_after,
    a_clock_that_runs_out_after_one_look,
)
from .framework.builders.incident import (
    a_steady_window,
    a_window_that_starts_calm,
    an_alert,
    the_onset_of,
)
from .framework.builders.investigation import an_investigation
from .framework.builders.model import (
    CHANGES_TOOL,
    LOGS_TOOL,
    WINDOW_START_ARG,
    a_model_that_is_always_cut_short,
    a_model_that_never_stops_reading,
    a_model_that_says,
    a_turn_answering,
    a_turn_calling,
    a_turn_saying,
    a_turn_that_was_cut_short,
    a_turn_the_model_declined,
    an_explanation,
    some_windows,
)

"""The loop: what the model decides, and what the loop decides for it.

Two things are deliberately not the model's. The onset is measured before its
first turn, because a sampled anchor makes two investigations of one incident
incomparable. The budget is arithmetic the loop does between turns, because a
bound the model could talk past is not a bound.

Everything else is the model's - which channel, which window, in what order,
and when it has seen enough. So these tests script the model and assert what
the loop did about it, and none of them needs a recording.
"""

# The bounds' own names, restated rather than imported from `Budget`. This is
# the wording a human reads when an investigation gives up, and a test that
# imported it would agree with whatever it was renamed to.
THE_TOOL_CALL_BOUND = "tool calls"
THE_TOKEN_BOUND = "tokens"
THE_TIME_BOUND = "time"

# What the loop says when one turn is all that is left. Restated for the same
# reason as the bounds above: the model has to be able to act on it.
THE_LAST_TURN_WARNING = "last turn"

# The two turns that are not turns, as the incident record has to say them. A
# human picking up an escalation acts differently on "it was cut off" than on
# "it said no", so the distinction has to survive as far as the summary.
THE_ANSWER_WAS_CUT_SHORT = "cut short"
THE_MODEL_DECLINED = "declined"


@pytest.mark.unit
def test_the_answer_the_model_gave_is_what_the_investigation_returns() -> None:
    # The typed exit. The loop ends when the answer tool is called, and every
    # explanation in that call comes back - the walk tries them in turn when
    # the first one is refuted.
    the_best_explanation = "the payments flag was switched on at 11:10"
    the_runner_up = "the 11:04 deploy changed the checkout path"
    investigation = an_investigation(
        a_model_that_says(
            a_turn_answering(
                an_explanation(summary=the_best_explanation, confidence=0.8),
                an_explanation(summary=the_runner_up, confidence=0.6)
            )
        )
    )
    some_incident_id = new_id()

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate(incident_id=some_incident_id)
        ) \
        .then(
            all_of(
                _the_candidates_say(the_best_explanation, the_runner_up),
                _every_candidate_belongs_to(some_incident_id)
            )
        )


@pytest.mark.unit
def test_the_model_chooses_which_channel_to_read() -> None:
    # The point of the change. A model that believes the answer is in what
    # changed reads changes and nothing else; the schedule this replaces would
    # have paid for a log window first, every time.
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(CHANGES_TOOL),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _the_channel_was_read(investigation.change_fetcher, times=1),
                _the_channel_was_never_read(investigation.log_fetcher)
            )
        )


@pytest.mark.unit
def test_a_tool_result_feeds_the_next_turn() -> None:
    # What "agentic" has to mean if it means anything: the second window is one
    # the model chose after seeing the first. A loop that computed both up
    # front would pass every other test in this file and fail this one.
    an_earlier_window_start = "2026-08-20T10:30:00Z"
    a_later_window_start = "2026-08-20T11:00:00Z"
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(LOGS_TOOL, {WINDOW_START_ARG: a_later_window_start}),
            a_turn_calling(LOGS_TOOL, {WINDOW_START_ARG: an_earlier_window_start}),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            _the_windows_read_started_at(
                investigation.log_fetcher, a_later_window_start, an_earlier_window_start
            )
        )


@pytest.mark.unit
def test_a_turn_that_only_talks_is_not_an_answer() -> None:
    # A model that wrote its conclusion as prose has not called the answer
    # tool, and prose is not parsed for one: a wandering model would otherwise
    # be indistinguishable from a finished one.
    some_thinking_aloud = "the flag looks suspicious, let me check the deploy"
    some_answer = "the payments flag was switched on at 11:10"
    investigation = an_investigation(
        a_model_that_says(
            a_turn_saying(some_thinking_aloud),
            a_turn_answering(an_explanation(summary=some_answer))
        )
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            _the_candidates_say(some_answer)
        )


@pytest.mark.unit
def test_the_investigation_stops_at_the_calls_it_was_allowed() -> None:
    # The bound the model would happily spend for ever. Enforced between turns
    # and never expressed to the model, so what stops it is arithmetic rather
    # than persuasion.
    two_calls = 2
    investigation = an_investigation(
        a_model_that_never_stops_reading(), budget=a_budget(tool_calls=two_calls)
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _the_channel_was_read(investigation.log_fetcher, times=two_calls),
                _no_cause_was_determined(),
                _the_summary_mentions(THE_TOOL_CALL_BOUND)
            )
        )


@pytest.mark.unit
def test_the_investigation_stops_when_the_tokens_run_out() -> None:
    # A different failure from running out of calls, and worth telling apart:
    # a model reading three-hour windows is cheap in calls and ruinous here.
    a_turn_worth_of_tokens = 1000
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(LOGS_TOOL, input_tokens=a_turn_worth_of_tokens),
            a_turn_answering(an_explanation())
        ),
        budget=a_budget(tokens=a_turn_worth_of_tokens)
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _no_cause_was_determined(),
                _the_summary_mentions(THE_TOKEN_BOUND)
            )
        )


@pytest.mark.unit
def test_the_investigation_stops_when_the_clock_runs_out() -> None:
    # The bound that answers to the human waiting on the incident rather than
    # to the accountant. An investigation frugal in calls and tokens can still
    # run past the point its answer was worth having.
    investigation = an_investigation(
        a_model_that_never_stops_reading(),
        budget=a_budget(now=a_clock_that_runs_out_after_one_look())
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _no_cause_was_determined(),
                _the_summary_mentions(THE_TIME_BOUND)
            )
        )


@pytest.mark.unit
def test_the_model_is_told_when_one_turn_is_all_that_is_left() -> None:
    # A hint, not a contract - the loop cuts at the bound whatever the model
    # does with it. Without it, a model spends its last turn asking for
    # evidence it will never be shown, and everything the investigation
    # learned is thrown away as "no cause determined".
    some_max_tool_calls_budget = 3
    some_calls_before_last_allowed_call = some_max_tool_calls_budget - 1
    investigation = an_investigation(
        a_model_that_says(
            *(
                a_turn_calling(LOGS_TOOL, {WINDOW_START_ARG: window})
                for window in some_windows(some_calls_before_last_allowed_call)
            ),
            a_turn_answering(an_explanation())
        ),
        budget=a_budget(tool_calls=some_max_tool_calls_budget)
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _the_channel_was_read(
                    investigation.log_fetcher, times=some_calls_before_last_allowed_call
                ),
                _what_the_model_saw_on_turn(
                    investigation.model,
                    turn=some_calls_before_last_allowed_call,
                    mentions=THE_LAST_TURN_WARNING
                )
            )
        )


@pytest.mark.unit
def test_a_turn_cut_short_is_asked_again_when_there_is_budget_for_it() -> None:
    # Nothing is wrong with the model or the request - there was not enough
    # room - so the investigation is not over, and everything already read is
    # still worth an answer. The type says a retry can help; only the loop
    # knows whether there is anything left to buy one with.
    some_answer = "the payments flag was switched on at 11:10"
    once_for_ask_and_once_for_retry = 2
    investigation = an_investigation(
        a_model_that_says(
            a_turn_that_was_cut_short(),
            a_turn_answering(an_explanation(summary=some_answer))
        )
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _the_candidates_say(some_answer),
                _the_model_was_asked(investigation.model, times=once_for_ask_and_once_for_retry)
            )
        )


@pytest.mark.unit
def test_a_turn_cut_short_escalates_when_there_is_no_budget_to_ask_again() -> None:
    # The other half of the same contract, and the reason it is a test rather
    # than a type: an exception can always be swallowed, and a loop that
    # retried regardless of the budget would pass the test above and spend for
    # ever here. The summary says both things - it was cut short, and which
    # bound left no room to try again.
    once_and_never_asked_again = 1
    investigation = an_investigation(
        a_model_that_says(a_turn_that_was_cut_short()),
        budget=a_budget(now=a_clock_that_runs_out_after_one_look())
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _no_cause_was_determined(),
                _the_summary_mentions(THE_ANSWER_WAS_CUT_SHORT, THE_TIME_BOUND),
                _the_model_was_asked(investigation.model, times=once_and_never_asked_again)
            )
        )


@pytest.mark.unit
def test_a_model_that_is_cut_short_every_turn_is_still_ended_by_the_clock() -> None:
    # A retry spent on another truncated turn buys nothing, and nothing
    # charges it for the attempt: a turn that produced no turn adds no tool
    # calls and no tokens. The clock is the only bound that still moves, so it
    # is the only thing that can end this - and it has to, or an investigation
    # meeting a model in this state never finishes at all.
    three_turns = 3
    investigation = an_investigation(
        a_model_that_is_always_cut_short(),
        budget=a_budget(now=a_clock_that_runs_out_after(looks=three_turns))
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _no_cause_was_determined(),
                _the_summary_mentions(THE_ANSWER_WAS_CUT_SHORT, THE_TIME_BOUND),
                _the_model_was_asked(investigation.model, times=three_turns)
            )
        )


@pytest.mark.unit
def test_a_refusal_ends_the_investigation_however_much_budget_is_left() -> None:
    # The one outcome a retry cannot fix: the same question over the same
    # evidence is declined again, so asking twice buys nothing and costs a
    # turn. The budget here is untouched, which is the point - what ends this
    # investigation is the kind of turn it got, not what it had left.
    once_and_never_asked_again = 1
    investigation = an_investigation(a_model_that_says(a_turn_the_model_declined()))

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _no_cause_was_determined(),
                _the_summary_mentions(THE_MODEL_DECLINED),
                _the_model_was_asked(investigation.model, times=once_and_never_asked_again)
            )
        )


@pytest.mark.unit
def test_what_the_investigation_read_comes_back_with_its_answer() -> None:
    # What a later round needs and cannot work out for itself. A round is
    # bought by a refutation, and it must not pay again for evidence this one
    # already has - nor mistake a channel nobody asked for for one that was
    # asked and came back empty. The metrics are in the list because the loop
    # read them itself, before the model's first turn.
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(CHANGES_TOOL),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            _the_channels_read_were(RetrievalChannel.METRICS, RetrievalChannel.CHANGES)
        )


@pytest.mark.unit
def test_the_model_is_told_the_onset_it_does_not_get_to_choose() -> None:
    # Stated as a fact in the opening message, because the onset anchors every
    # window and every later comparison. A model asked to locate it would
    # answer differently on a second run, and two investigations of one
    # incident would stop being comparable.
    some_metrics = a_window_that_starts_calm()
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            investigation.metrics_showed(some_metrics)
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            _what_was_asked_first_mentions(investigation.model, the_onset_of(some_metrics))
        )


@pytest.mark.unit
def test_a_window_with_no_anomalous_minute_is_answered_without_asking_the_model() -> None:
    # Nothing was read, so nothing was spent - and there is nothing a model
    # could add. The onset is measured, and a window with no departure from
    # the baseline has none to measure.
    investigation = an_investigation(a_model_that_says())

    Scenario() \
        .given(
            investigation.metrics_showed(a_steady_window())
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _the_model_was_never_asked(investigation.model),
                _no_cause_was_determined()
            )
        )


@pytest.mark.unit
def test_a_later_round_is_shown_what_was_tried_and_what_was_read() -> None:
    # The more valuable half of what a second round is bought with. The window
    # may reach further back, but a refutation is evidence the model has never
    # seen and cannot infer: a cause was named, acted on, and the service
    # stayed broken.
    some_flag_that_did_not_help = "checkout-v2"
    some_time_the_flag_was_changed = "2026-08-20T11:12:00Z"
    some_window_start_already_read = "2026-08-20T10:30:00Z"
    some_window_end_already_read = "2026-08-20T11:08:00Z"
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            investigation.metrics_showed(a_window_that_starts_calm())
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(),
                already_refuted=[
                    Attempt(
                        subject=some_flag_that_did_not_help,
                        enabled=False,
                        occurred_at=some_time_the_flag_was_changed
                    )
                ],
                already_read=[
                    Reading(
                        channel=RetrievalChannel.LOGS,
                        window_start=some_window_start_already_read,
                        window_end=some_window_end_already_read
                    )
                ]
            )
        ) \
        .then(
            _what_was_asked_first_mentions(
                investigation.model,
                some_flag_that_did_not_help,
                some_window_start_already_read,
                some_window_end_already_read
            )
        )


def _the_candidates_say(*summaries: str) -> Assertion[Findings]:
    """Every explanation the model offered, in the order it offered them."""
    def assertion(findings: Findings) -> bool:
        said = [candidate.summary for candidate in findings.candidates]
        if said != list(summaries):
            raise AssertionError(f"Expected the candidates {list(summaries)}, got {said}.")

        return True

    return assertion


def _every_candidate_belongs_to(incident_id: str) -> Assertion[Findings]:
    """A hypothesis is joined to its incident here, not by the model."""
    def assertion(findings: Findings) -> bool:
        stray = [
            candidate.incident_id
            for candidate in findings.candidates
            if candidate.incident_id != incident_id
        ]
        if stray:
            raise AssertionError(f"Expected every candidate to belong to [{incident_id}], "
                                 f"but some belonged to {stray}.")

        return True

    return assertion


def _no_cause_was_determined() -> Assertion[Findings]:
    """The honest outcome: one candidate, carrying no cause and no confidence."""
    def assertion(findings: Findings) -> bool:
        named = [
            candidate.summary
            for candidate in findings.candidates
            if candidate.cause_type is not None
        ]
        if named:
            raise AssertionError(f"Expected no cause to be determined, but got {named}.")

        return True

    return assertion


def _the_summary_mentions(*expected: str) -> Assertion[Findings]:
    """Which bound was reached. "I ran out of time" and "I read everything I
    was allowed to and still could not tell" call for different next steps."""
    def assertion(findings: Findings) -> bool:
        summary = findings.candidates[0].summary.lower()
        missing = [mention for mention in expected if mention.lower() not in summary]
        if missing:
            raise AssertionError(f"Expected the summary to mention {missing}, got [{summary}].")

        return True

    return assertion


def _the_channel_was_read(reader: Mock, times: int) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        if reader.call_count != times:
            raise AssertionError(
                f"Expected the channel to be read {times} time(s), "
                f"and it was read {reader.call_count}."
            )

        return True

    return assertion


def _the_channel_was_never_read(reader: Mock) -> Assertion[Findings]:
    """A channel the model did not ask for must not have been read on its
    behalf - reading it anyway is the schedule this replaces, under a new
    name."""
    def assertion(dont_care_findings: Findings) -> bool:
        if reader.called:
            raise AssertionError(
                f"Expected the channel never to be read, and it was read "
                f"{reader.call_count} time(s), for {reader.call_args_list}."
            )

        return True

    return assertion


def _the_windows_read_started_at(reader: Mock, *starts: str) -> Assertion[Findings]:
    """The windows the model asked for, in the order it asked for them."""
    def assertion(dont_care_findings: Findings) -> bool:
        asked_for = [call.args[0] for call in reader.call_args_list]
        if asked_for != list(starts):
            raise AssertionError(
                f"Expected the windows to start at {list(starts)}, got {asked_for}."
            )

        return True

    return assertion


def _the_channels_read_were(*channels: RetrievalChannel) -> Assertion[Findings]:
    """What the investigation reports having read, for the next round's sake."""
    def assertion(findings: Findings) -> bool:
        read = [reading.channel for reading in findings.already_read]
        if read != list(channels):
            raise AssertionError(f"Expected {list(channels)} to have been read, got {read}.")

        return True

    return assertion


def _the_model_was_never_asked(model: Mock) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        if model.called:
            raise AssertionError(
                f"Expected the model not to be asked, and it was asked {model.call_count} time(s)."
            )

        return True

    return assertion


def _the_model_was_asked(model: Mock, times: int) -> Assertion[Findings]:
    """How many turns the loop actually bought.

    The count is the assertion where a turn came back unusable: whether the
    loop asked again is the whole difference between a retry it was allowed
    and one it was not.
    """
    def assertion(dont_care_findings: Findings) -> bool:
        if model.call_count != times:
            raise AssertionError(
                f"Expected the model to be asked {times} time(s), "
                f"and it was asked {model.call_count}."
            )

        return True

    return assertion


def _what_was_asked_first_mentions(model: Mock, *expected: str) -> Assertion[Findings]:
    """The opening message - the one thing Argus writes as prose."""
    def assertion(dont_care_findings: Findings) -> bool:
        opening = _the_transcript_of(model, turn=0)[0]
        if not isinstance(opening, Ask):
            raise AssertionError(f"Expected the conversation to open with an ask, got [{opening}].")

        missing = [mention for mention in expected if mention not in opening.text]
        if missing:
            raise AssertionError(
                f"Expected the opening message to mention {missing}, got [{opening.text}]."
            )

        return True

    return assertion


def _what_the_model_saw_on_turn(model: Mock, turn: int, mentions: str) -> Assertion[Findings]:
    """Everything in the transcript by the model's `turn`th turn - the tool
    results included, which is where a warning about the budget travels."""
    def assertion(dont_care_findings: Findings) -> bool:
        seen = str(_the_transcript_of(model, turn))
        if mentions.lower() not in seen.lower():
            raise AssertionError(
                f"Expected the model to have been told [{mentions}] by its turn {turn}, "
                f"and it was shown [{seen}]."
            )

        return True

    return assertion


def _the_transcript_of(model: Mock, turn: int) -> Any:
    if len(model.call_args_list) <= turn:
        raise AssertionError(
            f"Expected the model to have been asked at least {turn + 1} time(s), "
            f"and it was asked {len(model.call_args_list)}."
        )

    return model.call_args_list[turn].args[0]
