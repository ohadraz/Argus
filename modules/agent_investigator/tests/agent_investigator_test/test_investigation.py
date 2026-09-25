"""The investigation: what the model decides, what the loop decides for it,
what it says as it goes, and what it writes down.

One module, and the three things worth asking of it separately. The sections
below are the files this was merged from, each keeping the account of its own
subject.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock, create_autospec

import pytest
from agent_investigator import Findings, Reading, investigate
from agent_investigator.budget import Budget
from agent_investigator.investigation import BRIEF
from agent_investigator.retrieval import ChangeFetcher, LogFetcher, MetricsFetcher
from argus_core import new_id, parse_iso
from argus_core.events import (
    ChannelsUnread,
    HypothesisFormed,
    IncidentEvent,
    LogsRetrieved,
    MetricsRetrieved,
    OnsetDetected,
    RetrievalRequested,
)
from argus_core.llm import a_conversation_recorded_for
from argus_core.models import (
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    ActionIdentity,
    Ask,
    Attempt,
    Evidence,
    MetricBucket,
    ModelPolicy,
    RetrievalChannel,
)
from argus_core.replay import CallType, ReplayEntry
from argus_testkit import Assertion, Kept, Scenario, all_of, calling

from agent_investigator_test.framework.builders.budget import (
    a_budget,
    a_clock_that_runs_out_after_one_look,
)
from agent_investigator_test.framework.builders.configuration import (
    some_investigation_settings,
    some_thresholds,
)
from agent_investigator_test.framework.builders.incident import (
    CALM_ERROR_RATE,
    DONT_CARE_STARTED_AT,
    a_steady_window,
    a_window_of,
    a_window_that_starts_calm,
    an_alert,
    the_onset_of,
)
from agent_investigator_test.framework.builders.investigation import Investigation, an_investigation
from agent_investigator_test.framework.builders.model import (
    CHANGES_TOOL,
    LOGS_TOOL,
    WINDOW_END_ARG,
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
from agent_investigator_test.framework.recording import a_recorder_that_keeps_what_it_is_given

# ---- from test_loop.py ----

# The loop: what the model decides, and what the loop decides for it.
#
# Two things are deliberately not the model's. The onset is measured before its
# first turn, because a sampled anchor makes two investigations of one incident
# incomparable. The budget is arithmetic the loop does between turns, because a
# bound the model could talk past is not a bound.
#
# Everything else is the model's - which channel, which window, in what order,
# and when it has seen enough. So these tests script the model and assert what
# the loop did about it, and none of them needs a recording.

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
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
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
def test_the_evidence_carries_the_moment_the_model_cited_it_at() -> None:
    # The page links a finding to the minute it rests on, and until now it
    # recovered that minute by running a regex over the sentence. The model is
    # quoting a line it retrieved and knows the instant already, so it is asked
    # for it: a field the model fills in is not a reading somebody downstream
    # has to guess at.
    #
    # The claim travels beside the instant rather than being replaced by it.
    # What the evidence says is prose and stays prose; only the instant was
    # ever structure hiding inside it.
    some_cited = Evidence(
        claim="monthly-spend-feature evaluated on for all 200 requests",
        at=parse_iso("2026-08-30T12:30:00Z")
    )
    investigation = an_investigation(
        a_model_that_says(
            a_turn_answering(an_explanation(supporting_evidence=[some_cited]))
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            _the_evidence_is(some_cited)
        )


@pytest.mark.unit
def test_evidence_that_names_no_moment_says_so_rather_than_borrowing_one() -> None:
    # A real answer from the recordings: "(no changes were recorded for this
    # service in that window)" rests on the absence of a row, which happened at
    # no instant. Null rather than the incident's own time, because a finding
    # handed a plausible minute would link to a row it does not rest on - and a
    # reader following that link would believe it.
    some_cited = Evidence(
        claim="no changes were recorded for this service in that window", at=None
    )
    investigation = an_investigation(
        a_model_that_says(
            a_turn_answering(an_explanation(supporting_evidence=[some_cited]))
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            _the_evidence_is(some_cited)
        )


@pytest.mark.unit
def test_the_transition_the_model_named_is_what_the_candidate_carries() -> None:
    # The two ends of the change as the model stated them, rather than as a
    # page recovers them by picking the `on`s and `off`s out of the summary -
    # which cannot tell a state from a sentence that merely uses the word.
    #
    # Carried through unchanged: how a state is *shown* is the page's business,
    # and a loop that upper-cased them here would be deciding it.
    investigation = an_investigation(
        a_model_that_says(
            a_turn_answering(an_explanation(
                subject="monthly-spend-feature", from_state="off", to_state="on"
            ))
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            _the_transition_is("off", "on")
        )


@pytest.mark.unit
def test_a_claim_broken_across_lines_is_accepted_as_the_sentence_it_is() -> None:
    # Mended where the answer is accepted, not in the view that happens to show
    # it: the same claim reaches a page, a postmortem and whoever is paged, and
    # a repair living in one of those is missing from the other two.
    #
    # Both fields, because the model wraps whichever it happens to be writing
    # when the line runs out.
    some_summary_broken_mid_clause = (
        "the flag was switched on\n   just before the errors began"
    )
    some_cited = Evidence(
        claim="monthly-spend-feature evaluated on\n  for all 198 requests", at=None
    )
    investigation = an_investigation(
        a_model_that_says(
            a_turn_answering(an_explanation(
                summary=some_summary_broken_mid_clause, supporting_evidence=[some_cited]
            ))
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _the_candidates_say(
                    "the flag was switched on just before the errors began"
                ),
                _the_evidence_is(Evidence(
                    claim="monthly-spend-feature evaluated on for all 198 requests",
                    at=None
                ))
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
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
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
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
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
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
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
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
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
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
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
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
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
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
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
def test_a_turn_cut_short_ends_the_investigation_rather_than_being_asked_again() -> None:
    # Asking again would be asking the same question. The transcript is
    # unchanged by a turn that carried nothing, and the seam a loop holds has
    # no room to give - so a second attempt differs from the first only by
    # resampling, while reliably spending another whole cap of output to find
    # that out. Two of these tests used to live here, one for a retry and one
    # for the bound that eventually stopped the retrying; with nothing being
    # retried there is one outcome to state.
    #
    # Whatever the budget has left is deliberately not part of this. A retry
    # this loop cannot make cheaper is not one the budget should be consulted
    # about, and an escalation that named a bound would tell a human the
    # investigation was too expensive when it was not.
    once_and_never_asked_again = 1
    investigation = an_investigation(a_model_that_is_always_cut_short())

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _no_cause_was_determined(),
                _the_summary_mentions(THE_ANSWER_WAS_CUT_SHORT),
                _the_summary_avoids(THE_TIME_BOUND),
                _the_model_was_asked(investigation.model, times=once_and_never_asked_again)
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
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
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
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
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
            calling(investigation.metrics_showed(some_metrics))
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            _what_was_asked_first_mentions(investigation.model, the_onset_of(some_metrics))
        )


@pytest.mark.unit
def test_the_investigation_is_held_with_the_model_its_deployment_named() -> None:
    # Per agent, and this is the agent it matters most for: the investigator
    # is the one whose judgement is the product, so which model answers it and
    # how hard it is asked to think are the two settings most worth being able
    # to move without a release.
    #
    # Asserted where the conversation is built rather than where it is used.
    # A loop holds a `(transcript, tools) -> Turn` and is told nothing about
    # models or effort - that is the seam working as intended, and it means
    # the only place the choice is visible is the asking.
    # `brief` is part of the policy an agent is assembled with rather than
    # an afterthought on it: it is the standing half of what this agent is
    # told, sent once as the request's `system` so that every incident
    # after the first reads it from cache instead of paying for it again.
    # An expected policy omitting it would assert that the Investigator
    # says nothing standing at all.
    some_policy = ModelPolicy(
        model="claude-haiku-4-5", effort="low", brief=BRIEF
    )
    conversations = create_autospec(a_conversation_recorded_for, instance=False)
    conversations.return_value = a_model_that_says(a_turn_answering(an_explanation()))
    investigation = an_investigation(a_model_that_says())

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate(
                settings=some_investigation_settings(
                    model=some_policy.model, effort=some_policy.effort
                ),
                conversations=conversations
            )
        ) \
        .then(
            _the_conversation_was_asked_for_with(conversations, some_policy)
        )


def _the_conversation_was_asked_for_with(conversations: Any,
                                         policy: ModelPolicy) -> Assertion[Findings]:
    """Which model the loop asked to be built for it, and at what effort.

    Read off the request for a conversation rather than off any turn, because
    a turn looks the same whoever answered it. A loop given the wrong model
    investigates perfectly well and bills differently, which is a failure
    nothing downstream of here can see.
    """
    def assertion(dont_care_findings: Findings) -> bool:
        asked = conversations.call_args

        if asked is None or asked.kwargs.get("policy") != policy:
            raise AssertionError(
                f"Expected a conversation asked for with [{policy}], got [{asked}]."
            )

        return True

    return assertion


@pytest.mark.unit
def test_the_minutes_are_carried_as_rows_rather_than_as_an_object_each() -> None:
    # The whole window still goes in front of the model - this is about how it
    # is written down, not how much of it there is. Naming every field on
    # every minute is what makes the opening message the largest thing in an
    # investigation, and the minutes themselves are the part worth paying for.
    some_metrics = a_window_that_starts_calm()
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(some_metrics))
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            all_of(
                _what_was_asked_first_names_each_metric_once(investigation.model),
                _what_was_asked_first_mentions(
                    investigation.model,
                    *(bucket.bucket_id for bucket in some_metrics)
                )
            )
        )


@pytest.mark.unit
def test_a_turn_cut_short_is_charged_for_what_it_generated() -> None:
    # It carried nothing and it was billed in full: running out of room means
    # the model generated to the cap and was stopped there. A loop that
    # retried without charging for it would be an unmanaged loop however many
    # bounds it checked afterwards - the bound that could see the spend is the
    # one that never moves.
    some_truncated_output = 16_000
    some_budget = a_budget()
    investigation = an_investigation(
        a_model_that_says(
            a_turn_that_was_cut_short(output_tokens=some_truncated_output),
            a_turn_answering(an_explanation())
        ),
        budget=some_budget
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            _the_tokens_charged_were(some_budget, some_truncated_output)
        )


@pytest.mark.unit
def test_a_reading_the_service_does_not_have_is_not_a_reading_of_zero() -> None:
    # The one distinction rows can silently lose. A service consulting no
    # cache has no hit ratio; a cache answering nothing has one of zero, and
    # `MetricBucket` says plainly that a reader must be able to tell a
    # deployment without a fast path from one whose fast path has gone.
    #
    # An encoding that wrote both as `0` would be handing the model a cache
    # that is failing where there is no cache at all - and the model would be
    # right to chase it.
    a_cache_answering_nothing = 0.0
    some_metrics = a_window_of(
        [CALM_ERROR_RATE, CALM_ERROR_RATE, 0.09, 0.18],
        cache_hit_ratios=[None, a_cache_answering_nothing, None, None]
    )
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(some_metrics))
        ) \
        .when(
            lambda: investigation.investigate()
        ) \
        .then(
            _what_was_asked_first_mentions(
                investigation.model,
                f",{DONT_CARE_STARTED_AT},\n",
                f",{DONT_CARE_STARTED_AT},{a_cache_answering_nothing}"
            )
        )


def _the_tokens_charged_were(budget: Budget, tokens: int) -> Assertion[Findings]:
    """What the investigation was charged, as a figure.

    Read off the budget rather than inferred from whether a bound bound: a
    test that moved a ceiling until the loop stopped would pass on a turn
    charged twice as readily as on one charged once, and would report neither.
    """
    def assertion(dont_care_findings: Findings) -> bool:
        charged = budget.tokens_spent()
        if charged != tokens:
            raise AssertionError(
                f"Expected [{tokens}] tokens to have been charged, got [{charged}]."
            )

        return True

    return assertion


@pytest.mark.unit
def test_a_window_with_no_anomalous_minute_is_answered_without_asking_the_model() -> None:
    # Nothing was read, so nothing was spent - and there is nothing a model
    # could add. The onset is measured, and a window with no departure from
    # the baseline has none to measure.
    investigation = an_investigation(a_model_that_says())

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
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
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(),
                already_refuted=[
                    Attempt(
                        identity=ActionIdentity(
                            action_type=REVERT_FEATURE_FLAG,
                            subject=some_flag_that_did_not_help
                        ),
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


@pytest.mark.unit
def test_a_restart_already_tried_is_described_as_a_restart() -> None:
    # Every attempt used to be rendered as "set <subject> on/off", which for a
    # restart tells the model a switch was thrown. It reasons about the switch:
    # a real investigation, shown this, wrote that Argus had tried setting the
    # heap off and concluded the toggle was not the cause. The line has to say
    # what was actually done, in the vocabulary of the kind that was done.
    some_restarted_service = "kuki-service"
    some_time_it_was_restarted = "2026-08-20T11:12:00Z"
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(),
                already_refuted=[
                    Attempt(
                        identity=ActionIdentity(
                            action_type=RESTART_SERVICE,
                            subject=some_restarted_service
                        ),
                        occurred_at=some_time_it_was_restarted
                    )
                ]
            )
        ) \
        .then(all_of(
            _what_was_asked_first_mentions(
                investigation.model,
                some_restarted_service,
                some_time_it_was_restarted
            ),
            _what_was_asked_first_avoids(
                investigation.model, f"set {some_restarted_service}"
            )
        ))


@pytest.mark.unit
def test_a_rollback_already_tried_is_described_as_a_rollback() -> None:
    # Same reason a restart is. Shown "set io-shop on", a model reasons about
    # a switch nobody threw - and a rollback that did not help is evidence
    # about the configuration, which is not what a toggle would have told it.
    some_rolled_back_application = "io-shop"
    some_time_it_was_rolled_back = "2026-08-20T11:12:00Z"
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(),
                already_refuted=[
                    Attempt(
                        identity=ActionIdentity(
                            action_type=ROLL_BACK_DEPLOYMENT,
                            subject=some_rolled_back_application
                        ),
                        occurred_at=some_time_it_was_rolled_back
                    )
                ]
            )
        ) \
        .then(all_of(
            _what_was_asked_first_mentions(
                investigation.model,
                some_rolled_back_application,
                some_time_it_was_rolled_back
            ),
            _what_was_asked_first_avoids(
                investigation.model, f"set {some_rolled_back_application}"
            )
        ))


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
            if candidate.failure_mode is not None
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


def _the_summary_avoids(*forbidden: str) -> Assertion[Findings]:
    """What an escalation must not blame.

    The counterpart to the assertion above, and needed because the failure it
    guards reads perfectly well. An outcome reported through the
    out-of-budget sentence when no bound was reached tells a human the
    investigation was too expensive, which is a different incident from the
    one they have - and it arrives with the bound's own name missing from the
    middle of the sentence, where nothing thinks to look.
    """
    def assertion(findings: Findings) -> bool:
        summary = findings.candidates[0].summary.lower()
        blamed = [mention for mention in forbidden if mention.lower() in summary]
        if blamed:
            raise AssertionError(f"Expected the summary not to blame {blamed}, got [{summary}].")

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


def _what_was_asked_first_names_each_metric_once(model: Mock) -> Assertion[Findings]:
    """Each metric named once for the window, not once for every minute.

    An assertion about the encoding rather than about the numbers, because the
    encoding is where this payload's cost lives: repeated once a minute, the
    field names cost more than the readings they label. Measured over a full
    360-minute window, one object per minute is 59,468 tokens and the same
    readings as rows are 17,057 - and none of the difference is information.

    Counted against `MetricBucket`'s own field list rather than against a
    spelling written out here, so a reading added to the bucket is covered on
    the day it arrives rather than on the day somebody remembers this test.
    """
    def assertion(dont_care_findings: Findings) -> bool:
        opening = _the_transcript_of(model, turn=0)[0]
        if not isinstance(opening, Ask):
            raise AssertionError(f"Expected the conversation to open with an ask, got [{opening}].")

        repeated = {
            field: opening.text.count(field)
            for field in MetricBucket.model_fields
            if opening.text.count(field) > 1
        }
        if repeated:
            raise AssertionError(
                f"Expected each metric to be named once in the opening message, and "
                f"{repeated} were named more than once."
            )

        return True

    return assertion


def _what_was_asked_first_avoids(model: Mock, *forbidden: str) -> Assertion[Findings]:
    """Words the opening message must not put in front of the model.

    The counterpart to the assertion above, and needed because the failure it
    guards is a sentence that reads perfectly well: an attempt described in the
    vocabulary of a different kind of action is not missing, it is wrong, and
    the model reasons about the action it was told about.
    """
    def assertion(dont_care_findings: Findings) -> bool:
        opening = _the_transcript_of(model, turn=0)[0]
        if not isinstance(opening, Ask):
            raise AssertionError(f"Expected the conversation to open with an ask, got [{opening}].")

        said = [mention for mention in forbidden if mention in opening.text]
        if said:
            raise AssertionError(
                f"Expected the opening message not to say {said}, got [{opening.text}]."
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


def _the_evidence_is(*cited: Evidence) -> Assertion[Findings]:
    """What the first candidate rests on, claim and instant alike.

    The whole value rather than its instant: a translation that carried the
    moment and dropped the sentence would satisfy a check on the moment alone.
    """
    def assertion(findings: Findings) -> bool:
        rested_on = findings.candidates[0].supporting_evidence

        if rested_on != list(cited):
            raise AssertionError(f"Expected the evidence {list(cited)}, got {rested_on}.")

        return True

    return assertion


def _the_transition_is(from_state: str | None, to_state: str | None) -> Assertion[Findings]:
    """The two ends of the change the first candidate blamed.

    Both at once, because half a transition is the failure worth catching: a
    translation carrying one end and dropping the other would satisfy a check
    on either one alone.
    """
    def assertion(findings: Findings) -> bool:
        blamed = findings.candidates[0]
        moved = (blamed.from_state, blamed.to_state)

        if moved != (from_state, to_state):
            raise AssertionError(
                f"Expected the transition {(from_state, to_state)}, got {moved}."
            )

        return True

    return assertion



# ---- from test_investigator_publishing.py ----

# The investigation, narrated as it happens.
#
# Control flow is the model's now, so two runs of one incident can read
# different evidence - which makes a bug reproduce intermittently and the
# transcript the only way to see why. That is what raises narration here from
# principle to necessity: an account naming every window asked for, in order, is
# what an investigation can be reconstructed from afterwards.
#
# The other half is what was *not* read. A channel nobody asked for and a
# channel that came back empty leave the same silence behind and mean opposite
# things, so the investigation says which channels it never asked.


@pytest.mark.unit
def test_each_retrieval_is_published_with_the_window_it_asked_for() -> None:
    # In order, and naming the windows the model chose rather than any the
    # loop would have chosen for it. This is the record a rerun that read
    # something different is compared against.
    some_window_start = "2026-08-20T10:30:00Z"
    some_window_end = "2026-08-20T11:00:00Z"
    an_earlier_window_start = "2026-08-20T09:30:00Z"
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(LOGS_TOOL, {WINDOW_START_ARG: some_window_start,
                                       WINDOW_END_ARG: some_window_end}),
            a_turn_calling(LOGS_TOOL, {WINDOW_START_ARG: an_earlier_window_start,
                                       WINDOW_END_ARG: some_window_end}),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_windows_asked_about_were(
                published,
                RetrievalChannel.LOGS,
                (some_window_start, some_window_end),
                (an_earlier_window_start, some_window_end)
            )
        )


@pytest.mark.unit
def test_what_a_retrieval_returned_is_published_with_it() -> None:
    # The lines themselves, not a reference to fetch them again: the log store
    # moves on, and a page that re-asked would show what the service says now
    # rather than what Argus read.
    some_lines = ["11:02 ERROR checkout failed", "11:03 ERROR checkout failed"]
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(LOGS_TOOL),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm())),
            calling(investigation.logs_showed(some_lines))
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_lines_published_were(published, some_lines)
        )


@pytest.mark.unit
def test_the_metrics_the_loop_read_itself_are_published() -> None:
    # The one retrieval the model did not choose. It still belongs in the
    # account: the onset every window is anchored on was measured from these
    # minutes, and a reader who cannot see them cannot check it.
    some_metrics = a_window_that_starts_calm()
    published: list[IncidentEvent] = []
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(some_metrics))
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_buckets_published_were(published, some_metrics)
        )


@pytest.mark.unit
def test_the_onset_it_found_is_published() -> None:
    # A measurement, and the anchor of every window that follows - so it is
    # stated in the account rather than left to be re-derived from the buckets
    # by whoever reads it.
    some_metrics = a_window_that_starts_calm()
    published: list[IncidentEvent] = []
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(some_metrics))
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_onset_published_was(published, the_onset_of(some_metrics))
        )


@pytest.mark.unit
def test_every_candidate_it_formed_is_published_with_what_it_rests_on() -> None:
    # Every one, not only the one the walk tries first: a runner-up that never
    # reached the table is a finding a human picking the incident up cannot
    # otherwise see Argus ever having had. Each carries its own evidence,
    # because a claim published without it is an assertion.
    the_best_explanation = "the payments flag was switched on at 11:10"
    the_runner_up = "the 11:04 deploy changed the checkout path"
    some_evidence = [Evidence(claim="11:10 INFO flag payments-v2 enabled", at=None)]
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_answering(
                an_explanation(summary=the_best_explanation,
                               confidence=0.8,
                               supporting_evidence=some_evidence),
                an_explanation(summary=the_runner_up, confidence=0.6)
            )
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            all_of(
                _the_candidates_published_were(published, the_best_explanation, the_runner_up),
                _the_first_candidate_published_rests_on(published, some_evidence)
            )
        )


@pytest.mark.unit
def test_a_published_candidate_carries_the_transition_it_blamed() -> None:
    # The narration renders the change struck-through and picked out, the way
    # the flag table does - so it needs the two states as values. Reading them
    # back out of the published summary is the guess this field exists to end.
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_answering(an_explanation(
                subject="monthly-spend-feature", from_state="off", to_state="on"
            ))
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_first_candidate_published_moved(published, "off", "on")
        )


@pytest.mark.unit
def test_a_channel_that_was_never_asked_for_is_published_as_unread() -> None:
    # "Nobody asked" and "asked, and nothing came back" leave the same silence
    # in an account and mean opposite things - one is a gap in the
    # investigation, the other is a finding about the service.
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(LOGS_TOOL),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_channels_published_as_unread_were(published, RetrievalChannel.CHANGES)
        )


@pytest.mark.unit
def test_a_channel_that_came_back_empty_is_not_published_as_unread() -> None:
    # The other half of the same distinction. A channel that was read and had
    # nothing in it was not a gap in the investigation, and reporting it as one
    # would send a human looking for evidence Argus already went and got.
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(CHANGES_TOOL),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm())),
            calling(investigation.no_changes_were_recorded())
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_channels_published_as_unread_were(published, RetrievalChannel.LOGS)
        )


@pytest.mark.unit
def test_an_investigation_nobody_is_listening_to_concludes_the_same_thing() -> None:
    # Narration is an account of the work, never a participant in it. The
    # investigation with a publisher and the one without must reach the same
    # answer, or the account is changing what it describes.
    the_answer = "the payments flag was switched on at 11:10"
    heard = _an_investigation_answering(the_answer)
    unheard = _an_investigation_answering(the_answer)

    Scenario() \
        .given(
            calling(heard.metrics_showed(a_window_that_starts_calm())),
            calling(unheard.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: (
                heard.investigate(publisher=lambda dont_care_event: None),
                unheard.investigate()
            )
        ) \
        .then(
            _both_concluded_the_same()
        )


def _an_investigation_answering(summary: str) -> Investigation:
    """One incident, arranged twice - so the only difference between the two
    runs is whether anybody is listening."""
    return an_investigation(
        a_model_that_says(
            a_turn_calling(LOGS_TOOL),
            a_turn_answering(an_explanation(summary=summary))
        )
    )


def _the_windows_asked_about_were(published: list[IncidentEvent],
                                  channel: RetrievalChannel,
                                  *windows: tuple[str, str]) -> Assertion[Findings]:
    """Every request on one channel, in the order it was made."""
    def assertion(dont_care_findings: Findings) -> bool:
        asked = [
            (event.window_start, event.window_end)
            for event in published
            if isinstance(event, RetrievalRequested) and event.channel == channel
        ]
        if asked != list(windows):
            raise AssertionError(f"Expected {list(windows)} to have been asked for, got {asked}.")

        return True

    return assertion


def _the_lines_published_were(published: list[IncidentEvent],
                              lines: list[str]) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        retrieved = [event for event in published if isinstance(event, LogsRetrieved)]
        if not retrieved:
            raise AssertionError(
                "Expected the lines that came back to be published, and none were."
            )

        retrieved_lines = retrieved[0].lines
        if retrieved_lines != lines:
            raise AssertionError(f"Expected the lines {lines}, got {retrieved_lines}.")

        return True

    return assertion


def _the_buckets_published_were(published: list[IncidentEvent],
                                buckets: list[MetricBucket]) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        retrieved = [event for event in published if isinstance(event, MetricsRetrieved)]
        if not retrieved:
            raise AssertionError(
                "Expected the metrics that were read to be published, and none were."
            )

        retrieved_buckets = retrieved[0].buckets
        if retrieved_buckets != buckets:
            raise AssertionError(f"Expected the buckets {buckets}, got {retrieved_buckets}.")

        return True

    return assertion


def _the_onset_published_was(published: list[IncidentEvent], onset: str) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        detected = [event for event in published if isinstance(event, OnsetDetected)]
        if not detected:
            raise AssertionError("Expected the onset to be published, and it was not.")

        detected_onset = detected[0].onset
        if detected_onset != onset:
            raise AssertionError(f"Expected the onset [{onset}], got [{detected_onset}].")

        return True

    return assertion


def _the_candidates_published_were(published: list[IncidentEvent],
                                   *summaries: str) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        formed = [
            event.summary for event in published if isinstance(event, HypothesisFormed)
        ]
        if formed != list(summaries):
            raise AssertionError(f"Expected the candidates {list(summaries)}, got {formed}.")

        return True

    return assertion


def _the_first_candidate_published_rests_on(published: list[IncidentEvent],
                                            evidence: list[Evidence]) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        formed = [event for event in published if isinstance(event, HypothesisFormed)]
        if not formed:
            raise AssertionError("Expected a candidate to be published, and none was.")

        formed_evidence = formed[0].evidence
        if formed_evidence != evidence:
            raise AssertionError(
                f"Expected the candidate to rest on {evidence}, got {formed_evidence}."
            )

        return True

    return assertion


def _the_channels_published_as_unread_were(published: list[IncidentEvent],
                                           *channels: RetrievalChannel) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        unread = [event for event in published if isinstance(event, ChannelsUnread)]
        if not unread:
            raise AssertionError("Expected the unread channels to be published, and they were not.")

        unread_channels = unread[0].channels
        if unread_channels != list(channels):
            raise AssertionError(
                f"Expected {list(channels)} to be reported unread, got {unread_channels}."
            )

        return True

    return assertion


def _both_concluded_the_same() -> Assertion[tuple[Findings, Findings]]:
    """The account is not a participant: it changes nothing about the answer."""
    def assertion(concluded: tuple[Findings, Findings]) -> bool:
        heard, unheard = concluded
        said = [candidate.summary for candidate in heard.candidates]
        said_unheard = [candidate.summary for candidate in unheard.candidates]
        if said != said_unheard:
            raise AssertionError(
                f"Expected the same conclusion either way, got {said} and {said_unheard}."
            )

        if heard.already_read != unheard.already_read:
            raise AssertionError(
                f"Expected the same evidence to be read either way, got "
                f"{heard.already_read} and {unheard.already_read}."
            )

        return True

    return assertion


def _the_first_candidate_published_moved(published: list[IncidentEvent],
                                         from_state: str | None,
                                         to_state: str | None) -> Assertion[Findings]:
    def assertion(dont_care_findings: Findings) -> bool:
        formed = [event for event in published if isinstance(event, HypothesisFormed)]
        if not formed:
            raise AssertionError("Expected a candidate to be published, and none was.")

        moved = (formed[0].from_state, formed[0].to_state)
        if moved != (from_state, to_state):
            raise AssertionError(
                f"Expected the published candidate to have moved {(from_state, to_state)}, "
                f"got {moved}."
            )

        return True

    return assertion



# ---- from test_recorded_investigation.py ----

# The one retrieval the loop makes for itself, and its receipt.
#
# Every other read is the model's: it asks, the dispatcher serves, and the
# dispatcher writes it down. The metrics are different - the loop reads them
# before the model has any say, because the onset every window is anchored on has
# to be measured rather than sampled - and that read goes nowhere near the
# dispatcher.
#
# So it needs its own receipt, or a replay can reconstruct every turn of the
# conversation and not the evidence the first one was written from. The buckets
# are in the opening message; without this entry, nothing in the log says what
# they were.
#
# Written down when it happens rather than when the investigation ends, which is
# what the second test is about: an incident whose metrics show nothing never
# reaches a model at all, and that is exactly the run someone later asks "what
# did it actually see" about.

SOME_INCIDENT_ID = "3cd00c42-6c21-4209-9d22-8f2f89455386"

# The channel this read belongs to, named as the model's own metrics calls are
# named, because it is the same channel read by a different caller. Restated
# here rather than imported: it is vocabulary the log's readers depend on, and
# a test that imports the code's spelling agrees with it even when it changes.
METRICS_TOOL = "get_metrics"


@pytest.mark.unit
def test_the_metrics_the_loop_reads_for_itself_are_written_down() -> None:
    # The buckets, not merely the fact of a read: they are what the onset was
    # measured from and what the opening message carried, so an entry without
    # them stands in for nothing.
    some_buckets = a_window_that_starts_calm()

    Scenario() \
        .given(
            recorded := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _an_investigation_recording_to(recorded, saw=some_buckets)
        ) \
        .then(
            all_of(
                _a_metrics_read_was_recorded_for(recorded, SOME_INCIDENT_ID),
                _the_recorded_read_carries(recorded, some_buckets)
            )
        )


@pytest.mark.unit
def test_an_investigation_that_stops_at_the_metrics_still_writes_the_read_down() -> None:
    # No minute departs, so the loop returns before a model is ever asked
    # anything. The read still happened and was still paid for, and this is the
    # run most likely to be re-examined - "it said it found nothing; what did it
    # have in front of it".
    a_window_with_no_incident_in_it = a_steady_window()

    Scenario() \
        .given(
            recorded := a_recorder_that_keeps_what_it_is_given()
        ) \
        .when(
            lambda: _an_investigation_recording_to(
                recorded, saw=a_window_with_no_incident_in_it
            )
        ) \
        .then(
            _a_metrics_read_was_recorded_for(recorded, SOME_INCIDENT_ID)
        )


def _an_investigation_recording_to(recorded: Kept[ReplayEntry],
                                   saw: list[MetricBucket]) -> Any:
    """One whole investigation, whose model answers on its first turn.

    The model is scripted to answer immediately because what these tests are
    about happens before it speaks - a longer conversation would add entries
    the dispatcher wrote, which have their own tests.
    """
    return investigate(
        an_alert(),
        incident_id=SOME_INCIDENT_ID,
        fetch_metrics=create_autospec(MetricsFetcher, instance=True, return_value=saw),
        fetch_logs=create_autospec(LogFetcher, instance=True, return_value=[]),
        fetch_change_events=create_autospec(ChangeFetcher, instance=True, return_value=[]),
        settings=some_investigation_settings(),
        thresholds=some_thresholds(),
        converse=a_model_that_says(a_turn_answering(an_explanation())),
        budget=a_budget(),
        recorder=recorded.take
    )


def _the_metrics_reads_in(recorded: Kept[ReplayEntry]) -> list[ReplayEntry]:
    return [entry for entry in recorded.taken if entry.target == METRICS_TOOL]


def _a_metrics_read_was_recorded_for(recorded: Kept[ReplayEntry],
                                     incident_id: str) -> Assertion[Any]:
    """Exactly one, filed as a tool call, against this incident.

    One rather than at least one: the loop reads the metrics once, and a second
    entry would mean the same read was written down twice - which is what an
    eval counting retrievals would report as an investigation that read more
    than it did.
    """
    def assertion(_result: Any) -> bool:
        reads = _the_metrics_reads_in(recorded)

        if len(reads) != 1:
            raise AssertionError(
                f"Expected exactly one metrics read recorded, got {len(reads)} "
                f"among {[entry.target for entry in recorded.taken]}."
            )

        read = reads[0]

        if read.call_type is not CallType.MCP:
            raise AssertionError(f"Expected a [{CallType.MCP}] entry, got [{read.call_type}].")

        if read.incident_id != incident_id:
            raise AssertionError(
                f"Expected it recorded for [{incident_id}], got [{read.incident_id}]."
            )

        return True

    return assertion


def _the_recorded_read_carries(recorded: Kept[ReplayEntry],
                               buckets: list[MetricBucket]) -> Assertion[Any]:
    """Every minute that came back, by the one thing that identifies a minute.

    The bucket ids rather than the whole payload: what matters is that the
    window was recorded whole, and comparing rendered numbers would make this
    test fail the day a bucket grows a field.
    """
    def assertion(_result: Any) -> bool:
        answered = str(_the_metrics_reads_in(recorded)[0].response)
        missing = [bucket.bucket_id for bucket in buckets if bucket.bucket_id not in answered]

        if missing:
            raise AssertionError(f"Expected the entry to carry {missing}, got {answered}.")

        return True

    return assertion
