"""The investigation: what the model decides, what the loop decides for it,
what it says as it goes, and what it writes down.

One module, and the three things worth asking of it separately. The sections
below are the files this was merged from, each keeping the account of its own
subject.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock, call, create_autospec

import pytest
from agent_investigator import Findings, Reading, investigate
from agent_investigator.budget import Budget
from agent_investigator.investigation import BRIEF
from agent_investigator.retrieval import (
    ChangeFetcher,
    DependencyFetcher,
    DeploymentDiffFetcher,
    LogFetcher,
    MetricsFetcher,
    RolloutFetcher,
)
from agent_investigator.tools import DEPENDENCIES_TOOL
from argus_core import new_id, parse_iso, to_iso, to_iso_minute
from argus_core.anomaly import THE_JUDGED_SIGNALS
from argus_core.events import (
    ChannelsUnread,
    HypothesisFormed,
    IncidentEvent,
    LogsRetrieved,
    MetricsRetrieved,
    OnsetDetected,
    RetrievalRequested,
    RetrievalUnanswered,
)
from argus_core.llm import a_conversation_recorded_for
from argus_core.mcp_transport import McpToolError
from argus_core.models import (
    DISCARD_CACHE_ENTRIES,
    PIN_AUTOSCALER,
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    SCALE_OUT,
    ActionIdentity,
    AlarmClaim,
    Ask,
    Attempt,
    Evidence,
    MetricBucket,
    ModelPolicy,
    RetrievalChannel,
    RuleReading,
    WorseWhen,
)
from argus_core.replay import CallType, ReplayEntry
from argus_testkit import Assertion, Kept, Scenario, all_of, calling, raising

from agent_investigator_test.framework.builders.budget import (
    a_budget,
    a_clock_that_runs_out_after_one_look,
)
from agent_investigator_test.framework.builders.configuration import (
    some_investigation_settings,
    some_thresholds,
)
from agent_investigator_test.framework.builders.incident import (
    A_STATED_ONSET,
    A_STATED_ONSET_OF_AN_ABSENCE,
    AN_ALERT_TIME,
    CALM_CPU_CAPACITY_CORES,
    CALM_CPU_CORES,
    CALM_ERROR_RATE,
    CALM_MINUTES,
    DONT_CARE_STARTED_AT,
    a_steady_window,
    a_window_of,
    a_window_that_starts_calm,
    a_window_that_stops_reporting,
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

# The column the paging rule's own series is carried under, and the name a
# disproof reports it by. Restated for the reason the bounds are: it is what the
# model reads, and what a human reads when an alarm is closed.
THE_RULES_SERIES = "rule_reading"

# The share of answers given confidently while nothing is wrong - the series a
# quality rule watches, and one that is worse falling.
SOME_CALM_SHARE = 0.9


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
def test_the_addresses_the_alert_carried_are_never_put_to_the_model() -> None:
    # A cache key is an address, and the model is never asked to act on one.
    # What it reasons about is how many entries disagree, by how much, and
    # since when - all of which the alert says in its summary. The addresses
    # travel to the action as a value instead, and a real incident carries
    # hundreds of them: re-rendered on every round of a ReAct loop they would
    # be the incident's largest cost and none of it evidence.
    #
    # This passes the day it is written. It is here because the whole alert is
    # handed to the opening message, so the one thing standing between those
    # keys and the prompt is that nobody has added a line for them.
    the_entries_the_check_found = ("io-shop:summary:2026-09:shopper-4",
                                   "io-shop:summary:2026-09:shopper-9")
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(stale_entry_keys=the_entries_the_check_found)
            )
        ) \
        .then(all_of(
            _what_was_asked_first_mentions(investigation.model, "## Alert"),
            _nothing_the_model_was_shown_names(investigation.model,
                                               *the_entries_the_check_found)
        ))


@pytest.mark.unit
def test_the_model_is_told_when_no_series_corroborates_the_onset() -> None:
    # Said rather than left implicit, for the reason the "opens already
    # elevated" sentence is said. A model handed a confident minute and a flat
    # window reads the flatness as the service being well, and concludes there
    # is nothing to find - which is the one conclusion this kind of incident
    # cannot afford, because the flatness is the mode rather than its absence.
    #
    # The existing sentence would also be a lie here: it tells the model the
    # onset was measured from the metrics below, and it was not.
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(stated_onset=A_STATED_ONSET))
        ) \
        .then(
            all_of(
                _what_was_asked_first_mentions(
                    investigation.model, "stated by the alert", "no series departs"
                ),
                _what_was_asked_first_avoids(
                    investigation.model, "measured from the per-minute metrics"
                )
            )
        )


@pytest.mark.unit
def test_the_model_is_told_the_rows_stop_and_when_they_stopped() -> None:
    # A window that stops is the one shape a model misreads without prompting. An
    # empty table provokes a question; a plausible window that merely ends provokes
    # none, and the natural reading is that Argus retrieved a short span.
    #
    # So the message says where the rows stop and how far that is from the alert.
    # Both figures are Argus's - the model has the firing time and no idea what
    # time it is now - and a subtraction it was never given both halves of is not a
    # judgement it can make.
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))
    the_window_that_stops = a_window_that_stops_reporting()

    Scenario() \
        .given(
            calling(investigation.metrics_showed(the_window_that_stops))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(stated_onset=A_STATED_ONSET_OF_AN_ABSENCE)
            )
        ) \
        .then(
            _what_was_asked_first_mentions(
                investigation.model,
                the_window_that_stops[-1].bucket_id,
                to_iso(AN_ALERT_TIME),
                "stop"
            )
        )


@pytest.mark.unit
def test_the_model_is_not_told_a_window_that_stops_is_all_there_is_to_ask_for() -> None:
    # The sentence that would do the most damage here, and it is in the paragraph
    # about the rows rather than the one about the onset. It tells the model there
    # is no more of this channel to ask for - about the one channel whose return is
    # what ends this incident, over a window that is missing most of what it
    # describes.
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_stops_reporting()))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(stated_onset=A_STATED_ONSET_OF_AN_ABSENCE)
            )
        ) \
        .then(
            _what_was_asked_first_avoids(
                investigation.model,
                "there is no more of this channel to ask for",
                "none of them departs from its baseline"
            )
        )


@pytest.mark.unit
def test_a_window_that_was_read_throughout_is_described_exactly_as_it_was() -> None:
    # The guard on the other two. A flat window is FM-26's, its wording was written
    # for it, and every scenario built before this change walks that branch - so it
    # keeps both sentences a window that stops has to lose.
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(stated_onset=A_STATED_ONSET))
        ) \
        .then(
            all_of(
                _what_was_asked_first_mentions(
                    investigation.model,
                    "no series departs",
                    "the whole span the metrics source keeps"
                ),
                _what_was_asked_first_avoids(investigation.model, "stop")
            )
        )


@pytest.mark.unit
def test_an_investigation_whose_window_stops_says_the_incident_was_never_read() -> None:
    # The fact the gate needs and cannot get. It refuses an action as unconfirmable
    # where the alert dated the incident, on the inference that an alert-dated
    # incident had no series depart and so has nothing to be watched coming back.
    # That holds for a window read throughout and fails here: a channel can be
    # watched coming back by a reading existing as well as by a level falling.
    #
    # Measured here because this is the only place holding both the onset and the
    # window, and carried on the findings because they already cross the boundary
    # the gate sits behind.
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_stops_reporting()))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(stated_onset=A_STATED_ONSET_OF_AN_ABSENCE)
            )
        ) \
        .then(
            _the_readings_cover_the_incident(False)
        )


@pytest.mark.unit
def test_an_investigation_whose_window_was_read_throughout_says_so() -> None:
    # The other alert-dated shape, and the reason the refusal exists. Silent data
    # corruption's window carries every minute of the incident and holds them all
    # flat - so the channel has already said everything it is going to say, and it
    # will say the same thing after the flag goes back. Nothing here may change.
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(stated_onset=A_STATED_ONSET))
        ) \
        .then(
            _the_readings_cover_the_incident(True)
        )


@pytest.mark.unit
def test_the_change_channels_are_read_at_the_stated_onset() -> None:
    # The whole of what a stated onset buys. An alert raised by a check that
    # runs weekly fires long after the writing went wrong, so a window anchored
    # on when it fired asks what changed during the discovery rather than during
    # the fault - which for a week is hundreds of changes and no answer. The
    # minute the alert states narrows that to an hour's worth.
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(CHANGES_TOOL),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(stated_onset=A_STATED_ONSET))
        ) \
        .then(
            _the_channel_was_read_up_to(
                investigation.change_fetcher, to_iso(A_STATED_ONSET)
            )
        )


@pytest.mark.unit
def test_the_metrics_are_not_described_as_what_the_onset_was_measured_from() -> None:
    # The same falsehood the Onset paragraph stopped telling, one section lower
    # and in different words - which is exactly how a caveat added in one place
    # comes to be contradicted by prose nobody re-read. The rows are still worth
    # sending: they are what says the flatness is real.
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(stated_onset=A_STATED_ONSET))
        ) \
        .then(
            _what_was_asked_first_avoids(
                investigation.model, "the minutes the onset was measured from"
            )
        )


@pytest.mark.unit
def test_a_measured_onset_is_still_described_as_measured() -> None:
    # The branch every existing incident takes, asserted beside the new one
    # because a change to this paragraph could quietly reword it for everybody.
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
                _what_was_asked_first_mentions(
                    investigation.model, "measured from the per-minute metrics"
                ),
                _what_was_asked_first_avoids(investigation.model, "stated by the alert")
            )
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
                f",{DONT_CARE_STARTED_AT},{CALM_CPU_CORES},"
                f"{CALM_CPU_CAPACITY_CORES},\n",
                f",{DONT_CARE_STARTED_AT},{CALM_CPU_CORES},"
                f"{CALM_CPU_CAPACITY_CORES},{a_cache_answering_nothing}"
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
def test_an_onset_the_alert_states_is_used_where_the_metrics_show_none() -> None:
    # The branch that lets an incident be found by something other than a health
    # series. A window that is flat because nothing was ever wrong and one that
    # is flat because what is wrong is a stored value are the same window, and
    # only the alert can tell them apart - so where it says when this began, the
    # loop works from that and asks the model, rather than reporting that there
    # was nothing to investigate.
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(stated_onset=A_STATED_ONSET))
        ) \
        .then(
            _the_model_was_asked(investigation.model, times=1)
        )


@pytest.mark.unit
def test_a_flat_window_with_no_stated_onset_is_still_answered_without_the_model() -> None:
    # The other half, asserted beside it because this is the branch every
    # existing incident takes and the one a change here could quietly widen.
    # An alert that states nothing leaves the loop exactly where it was: the
    # metrics are the only word on when this began, and they have none.
    investigation = an_investigation(a_model_that_says())

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(stated_onset=None))
        ) \
        .then(
            all_of(
                _the_model_was_never_asked(investigation.model),
                _no_cause_was_determined()
            )
        )


@pytest.mark.unit
def test_a_series_alarm_over_a_window_with_no_minutes_disproves_nothing() -> None:
    # The gap between the two branches above and below, and a real case rather
    # than a formality. A window that was read and holds no departure
    # contradicts a series alarm; a window with no minutes in it contradicts
    # nothing, because the retrieval answered and had nothing to say - which is
    # nearer to not having been able to see than to having seen a well service.
    #
    # So it ends where every undated incident ended before any of this: no
    # disproof, and no model. Both halves are asserted, because the way this
    # breaks is the branch below reaching for an anchor it should not have - and
    # a walk that invented one would investigate a service nothing was read
    # about, which is what it did the one time this condition was missing.
    investigation = an_investigation(a_model_that_says())

    Scenario() \
        .given(
            calling(investigation.metrics_showed([]))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(stated_onset=None))
        ) \
        .then(
            all_of(
                _nothing_was_disproven(),
                _the_model_was_never_asked(investigation.model),
                _no_cause_was_determined()
            )
        )


@pytest.mark.unit
def test_a_flat_window_under_a_series_alarm_reports_the_alarm_disproven() -> None:
    # The same branch as the case above, asked the question that separates two
    # findings it used to report as one. "I could not work out what is wrong"
    # sends a responder to the service; "nothing is wrong and the rule was
    # looking at a series that never moved" sends them to the rule, and only the
    # second is true here.
    #
    # The signals and the span ride with it because a disproof is the one claim
    # in a walk that nothing later can check. One made over a window too narrow
    # to contain the condition reads exactly like a sound one.
    investigation = an_investigation(a_model_that_says())

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(stated_onset=None))
        ) \
        .then(
            _the_alarm_was_disproven_over(THE_JUDGED_SIGNALS)
        )


@pytest.mark.unit
def test_a_flat_window_under_a_finding_of_the_rules_own_disproves_nothing() -> None:
    # The seam the closure above must not swallow. A check comparing stored
    # values against the records behind them can find a disagreement it cannot
    # date, and the window it arrives with is flat for the same reason every
    # window under such a check is: no series was ever its subject.
    #
    # So the investigation goes on, and the model is asked - where the case above
    # ends without a model ever being opened.
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(stated_onset=None, claim=AlarmClaim.ITS_OWN_FINDING)
            )
        ) \
        .then(
            all_of(
                _nothing_was_disproven(),
                _the_model_was_asked(investigation.model, times=1)
            )
        )


@pytest.mark.unit
def test_an_undated_finding_is_anchored_on_the_minute_the_alarm_fired_in() -> None:
    # What such an investigation works from, since it has to work from
    # something: every window here is anchored on a minute, and the only minute
    # anybody recorded is the one the alarm went off in.
    #
    # Asserted as the alert's own firing minute rather than as "some minute",
    # because the alternative that would also pass a vaguer check is the one
    # worth refusing: an onset invented from the window's first row, which would
    # date the incident from wherever the metrics source happens to reach back to.
    published: list[IncidentEvent] = []
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(stated_onset=None, claim=AlarmClaim.ITS_OWN_FINDING),
                publisher=published.append
            )
        ) \
        .then(
            _the_onset_published_was(published, to_iso_minute(AN_ALERT_TIME))
        )


@pytest.mark.unit
def test_the_metrics_the_loop_reads_are_read_for_the_rule_that_paged() -> None:
    # The onset is measured from this read, so this is the read that has to
    # carry the series the rule watches. A quality incident departs in that
    # series alone, and a window read without it is five flat lines under an
    # alarm.
    some_rule = "kuki-rule"
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm()))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(rule=some_rule))
        ) \
        .then(
            _the_metrics_were_first_read_for(
                investigation.metrics_fetcher, to_iso(AN_ALERT_TIME), some_rule
            )
        )


@pytest.mark.unit
def test_a_flat_window_missing_the_rules_series_disproves_nothing() -> None:
    # The window was never shown what the rule watched, so its flatness says
    # nothing about the alarm. A rule on a quality series is exactly the rule
    # the five fixed signals cannot see, and closing it on them would close
    # every such incident as a well service.
    #
    # So it goes on as an alarm a flat window cannot contradict goes on, and the
    # model is asked.
    some_rule = "kuki-rule"
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(stated_onset=None, rule=some_rule)
            )
        ) \
        .then(
            all_of(
                _nothing_was_disproven(),
                _the_model_was_asked(investigation.model, times=1)
            )
        )


@pytest.mark.unit
def test_the_model_is_told_the_rules_series_could_not_be_read() -> None:
    # Where the case above goes on to, and the paragraph it would otherwise hear
    # is false. An alarm nothing dates was a check's own finding, which knows
    # something no series does - but this rule watches a series, and the series
    # is not in the window at all.
    #
    # So the model is told whose series is missing rather than that the rule saw
    # past the metrics. The fault is in a series it cannot see, not in one no
    # series could ever carry.
    some_rule = "kuki-rule"
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(stated_onset=None, rule=some_rule)
            )
        ) \
        .then(
            all_of(
                _what_was_asked_first_mentions(
                    investigation.model, some_rule, "could not be read"
                ),
                _what_was_asked_first_avoids(
                    investigation.model, "knows something no series does"
                )
            )
        )


@pytest.mark.unit
def test_an_undated_finding_is_not_told_its_rule_watches_a_series() -> None:
    # The case above's counterpart. Every alert Grafana sends names the rule that
    # sent it, a check's own finding included - and that rule evaluates no
    # series, so there is none missing. Its finding is what no series carries.
    some_rule = "kuki-rule"
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window()))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(
                    stated_onset=None, claim=AlarmClaim.ITS_OWN_FINDING, rule=some_rule
                )
            )
        ) \
        .then(
            all_of(
                _what_was_asked_first_mentions(
                    investigation.model, "knows something no series does"
                ),
                _what_was_asked_first_avoids(investigation.model, "could not be read")
            )
        )


@pytest.mark.unit
def test_a_disproof_names_the_rules_series_among_the_signals_it_judged() -> None:
    # The rule's series was read and stayed where it always is, so the alarm is
    # contradicted on the series it fired on as well as on the five. A disproof
    # leaving it out would claim less than was checked, and one naming it where
    # it was never read would claim more - and either reads exactly like a sound
    # one.
    some_rule = "kuki-rule"
    some_steady_share = RuleReading(value=SOME_CALM_SHARE, worse_when="below")
    investigation = an_investigation(a_model_that_says())

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_steady_window(rule_reading=some_steady_share)))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(stated_onset=None, rule=some_rule)
            )
        ) \
        .then(
            _the_alarm_was_disproven_over((*THE_JUDGED_SIGNALS, THE_RULES_SERIES))
        )


@pytest.mark.unit
def test_the_rules_reading_is_carried_as_its_value() -> None:
    # The cell is the number the rule compares with its line. A reading written
    # as the object holding it puts a direction in every row of the window -
    # the repetition the rows exist to avoid - and hands the model a cell to
    # parse before it can compare anything.
    some_departed_share = 0.4
    some_metrics = a_window_of(
        [CALM_ERROR_RATE] * CALM_MINUTES + [0.09, 0.18],
        rule_readings=[
            *[RuleReading(value=SOME_CALM_SHARE, worse_when="below")] * (CALM_MINUTES + 1),
            RuleReading(value=some_departed_share, worse_when="below")
        ]
    )
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(some_metrics))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(rule="dont-care-rule"))
        ) \
        .then(
            all_of(
                _a_row_of_what_was_asked_first_ends_with(
                    investigation.model, f"{some_departed_share}"
                ),
                _what_was_asked_first_avoids(investigation.model, "worse_when")
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(("worse_when", "the_other_way"), [("below", "above"), ("above", "below")])
def test_the_model_is_told_which_rule_the_column_is_and_which_way_is_worse(
        worse_when: WorseWhen,
        the_other_way: str) -> None:
    # A column the model cannot place is a number with no meaning. It is told
    # once which rule paged on it and which way that rule calls worse - the one
    # thing the values cannot say for themselves, since a share of confident
    # answers is worse falling and an error rate is worse rising.
    some_rule = "kuki-rule"
    some_metrics = a_window_of(
        [CALM_ERROR_RATE] * CALM_MINUTES + [0.09, 0.18],
        rule_readings=[RuleReading(value=SOME_CALM_SHARE, worse_when=worse_when)]
        * (CALM_MINUTES + 2)
    )
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(some_metrics))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(rule=some_rule))
        ) \
        .then(
            all_of(
                _what_was_asked_first_mentions(
                    investigation.model, some_rule, f"worse when {worse_when}"
                ),
                _what_was_asked_first_avoids(
                    investigation.model, f"worse when {the_other_way}"
                )
            )
        )


@pytest.mark.unit
def test_the_rules_column_is_explained_before_the_rows_rather_than_after_them() -> None:
    # The rows are what a model scans for where a series turned, and a sentence
    # after the last of them reads as another row - one with no minute and no
    # numbers, in the one table the opening asks to be read row by row.
    some_rule = "kuki-rule"
    some_metrics = a_window_of(
        [CALM_ERROR_RATE] * CALM_MINUTES + [0.09, 0.18],
        rule_readings=[RuleReading(value=SOME_CALM_SHARE, worse_when="below")]
        * (CALM_MINUTES + 2)
    )
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(some_metrics))
        ) \
        .when(
            lambda: investigation.investigate(alert=an_alert(rule=some_rule))
        ) \
        .then(
            _what_was_asked_first_names_the_rule_before_the_rows(investigation.model, some_rule)
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


@pytest.mark.unit
def test_a_scale_out_already_tried_is_described_as_a_scale_out() -> None:
    # Same reason a rollback is. A model told "set io-shop on" reasons about a
    # switch nobody threw - and here the evidence being withheld is the one that
    # matters most: capacity was already added and the service is still unwell,
    # which argues against demand saturation rather than for it.
    some_application_scaled_out = "io-shop"
    some_time_it_was_scaled_out = "2026-08-20T11:12:00Z"
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
                            action_type=SCALE_OUT,
                            subject=some_application_scaled_out
                        ),
                        occurred_at=some_time_it_was_scaled_out
                    )
                ]
            )
        ) \
        .then(all_of(
            _what_was_asked_first_mentions(
                investigation.model,
                f"scaled {some_application_scaled_out} out",
                some_time_it_was_scaled_out
            ),
            _what_was_asked_first_avoids(
                investigation.model, f"set {some_application_scaled_out}"
            )
        ))


@pytest.mark.unit
def test_a_pin_already_tried_is_described_as_a_pin() -> None:
    # The fifth kind, and the one whose absence does not degrade gracefully: the
    # wording is chosen by a chain of comparisons ending in `assert_never`, so a
    # kind nobody added a branch for does not render badly - it raises, and the
    # investigation that would have raised is the second round of a walk whose pin
    # was refuted. That walk is exactly the one this evidence matters to, because
    # "the count was already held still and the service is still unwell" argues
    # against the controller being the cause at all.
    some_pinned_application = "io-shop"
    some_time_it_was_pinned = "2026-08-20T11:12:00Z"
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
                            action_type=PIN_AUTOSCALER,
                            subject=some_pinned_application
                        ),
                        occurred_at=some_time_it_was_pinned
                    )
                ]
            )
        ) \
        .then(all_of(
            _what_was_asked_first_mentions(
                investigation.model,
                f"stopped {some_pinned_application}'s autoscaler scaling it down",
                some_time_it_was_pinned
            ),
            _what_was_asked_first_avoids(
                investigation.model, f"set {some_pinned_application}"
            )
        ))


@pytest.mark.unit
def test_a_discard_already_tried_is_described_as_copies_thrown_away() -> None:
    # The sixth kind, and the one most easily described as something it is not.
    # Told that stale figures were "cleared" or "deleted", a model reasons about
    # data loss and starts looking for what is missing from the shop - where what
    # happened is that copies were thrown away and the records behind them never
    # moved.
    #
    # It also has to carry what the attempt argues. "The stale copies were already
    # discarded and the figures still disagree" is evidence against a divergence
    # being the cause at all, which is only available to a model that understands
    # the action as having removed copies.
    some_service_whose_copies_went = "io-shop"
    some_time_they_were_discarded = "2026-08-20T11:12:00Z"
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
                            action_type=DISCARD_CACHE_ENTRIES,
                            subject=some_service_whose_copies_went
                        ),
                        occurred_at=some_time_they_were_discarded
                    )
                ]
            )
        ) \
        .then(all_of(
            _what_was_asked_first_mentions(
                investigation.model,
                f"discarded {some_service_whose_copies_went}'s stale cached figures",
                some_time_they_were_discarded
            ),
            _what_was_asked_first_avoids(
                investigation.model, f"set {some_service_whose_copies_went}"
            )
        ))


def _the_metrics_were_first_read_for(reader: Mock,
                                     alert_time: str,
                                     rule: str) -> Assertion[Findings]:
    """The loop's own read, before the model's first turn, and what it asked for.

    Compared against `call_args_list` rather than through
    `assert_called_once_with`, which does not survive a spec built from a
    `Protocol`: `self` is left on the signature, so every comparison fails while
    printing identically.
    """
    def assertion(dont_care_findings: Findings) -> bool:
        first = reader.call_args_list[0] if reader.call_args_list else None
        if first != call(alert_time, rule):
            raise AssertionError(
                f"Expected the metrics to be read first anchored on [{alert_time}] "
                f"for the rule [{rule}], and the first read was {first}."
            )

        return True

    return assertion


def _the_readings_cover_the_incident(expected: bool) -> Assertion[Findings]:
    """Whether the findings report any reading of the incident's own minutes.

    The gate decides confirmability on this and cannot work it out: it holds the
    onset and never the window. So the investigation has to say, and what it says
    is a property of the evidence rather than a judgement about it - a window with
    readings from the onset on, or a window with none.
    """
    def assertion(findings: Findings) -> bool:
        if findings.readings_cover_the_incident != expected:
            raise AssertionError(
                f"Expected the findings to report the incident's minutes as "
                f"{'read' if expected else 'unread'}, and they report them as "
                f"{'read' if findings.readings_cover_the_incident else 'unread'} - "
                f"so the gate decides whether anything could confirm an action on "
                f"the wrong fact."
            )

        return True

    return assertion


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


def _the_alarm_was_disproven_over(signals: tuple[str, ...]) -> Assertion[Findings]:
    """That the window was reported as contradicting the alarm, and over what.

    The signals are half the assertion rather than decoration. A disproof is read
    by people and resolved against nothing, so one that named no signals - or
    named a signal nobody judged - is indistinguishable from a sound one, and
    this is the only place the difference is visible.
    """
    def assertion(findings: Findings) -> bool:
        if findings.disproof is None:
            raise AssertionError(
                "Expected the window to have disproven the alarm, and nothing "
                "reported a disproof - so the incident would hand a human a "
                "service that was well throughout."
            )

        if findings.disproof.signals_judged != signals:
            raise AssertionError(
                f"Expected the disproof to have been made over {signals}, and it "
                f"names {findings.disproof.signals_judged}."
            )

        if findings.disproof.minutes_judged < 1:
            raise AssertionError(
                f"Expected a disproof made over minutes that were actually read, "
                f"and it reports {findings.disproof.minutes_judged} - an alarm "
                f"closed on an empty window is closed on no evidence."
            )

        return True

    return assertion


def _nothing_was_disproven() -> Assertion[Findings]:
    """That no disproof was reported, whatever else the investigation concluded."""
    def assertion(findings: Findings) -> bool:
        if findings.disproof is not None:
            raise AssertionError(
                f"Expected no disproof, and the alarm was reported disproven over "
                f"{findings.disproof.signals_judged} - a window says nothing "
                f"about an alarm whose subject no series carries."
            )

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


def _the_channel_was_read_up_to(reader: Mock, moment: str) -> Assertion[Findings]:
    """That the window a channel was asked for ends where the onset is.

    The end rather than the start, because that is the bound the onset sets: a
    change made after the incident began did not cause it. Asserted about the
    call the fetcher actually received, since what the model asked for and what
    the window was defaulted to are two different things and only one of them
    reaches the source.
    """
    def assertion(dont_care_findings: Findings) -> bool:
        if not reader.called:
            raise AssertionError("Expected the channel to have been read at all.")

        dont_care_service, dont_care_start, window_end = reader.call_args.args

        if window_end != moment:
            raise AssertionError(
                f"Expected the channel to be read up to [{moment}], and it was "
                f"read up to [{window_end}]."
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


def _a_row_of_what_was_asked_first_ends_with(model: Mock, cell: str) -> Assertion[Findings]:
    """Some row of the opening's table ends in this cell - whatever the columns
    before it are, which are the bucket's to decide."""
    def assertion(dont_care_findings: Findings) -> bool:
        opening = _the_transcript_of(model, turn=0)[0]
        if not isinstance(opening, Ask):
            raise AssertionError(f"Expected the conversation to open with an ask, got [{opening}].")

        if not any(line.endswith(f",{cell}") for line in opening.text.splitlines()):
            raise AssertionError(
                f"Expected a row of the opening message to end with [{cell}], got "
                f"[{opening.text}]."
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


def _what_was_asked_first_names_the_rule_before_the_rows(model: Mock,
                                                          rule: str) -> Assertion[Findings]:
    """The rule's column is placed before the table, not after its last row.

    A sentence after the last row reads as one more row of it.
    """
    def assertion(dont_care_findings: Findings) -> bool:
        opening = _the_transcript_of(model, turn=0)[0]
        if not isinstance(opening, Ask):
            raise AssertionError(f"Expected the conversation to open with an ask, got [{opening}].")

        named_at = opening.text.find(f"({rule})")
        header_at = opening.text.find(f"{next(iter(MetricBucket.model_fields))},")

        if named_at == -1 or header_at == -1 or named_at > header_at:
            raise AssertionError(
                f"Expected the rule [{rule}] named before the rows' header, got "
                f"[{opening.text}]."
            )

        return True

    return assertion


def _nothing_the_model_was_shown_names(model: Mock,
                                       *forbidden: str) -> Assertion[Findings]:
    """Words that must appear nowhere in the conversation.

    Every turn rather than the opening one, and the whole exchange rather than
    the `Ask` within it. What is claimed is that an address never reaches the
    model at all; the opening message is only where it would reach it first,
    and a tool result or a later ask carrying one is the same leak while
    satisfying a check on turn zero.
    """
    def assertion(dont_care_findings: Findings) -> bool:
        shown = "\n".join(
            repr(exchange)
            for turn in range(len(model.call_args_list))
            for exchange in _the_transcript_of(model, turn)
        )
        said = [word for word in forbidden if word in shown]

        if said:
            raise AssertionError(f"Expected {said} nowhere within [{shown}].")

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
def test_a_departure_only_the_rules_series_shows_is_measured_and_investigated() -> None:
    # The incident this whole channel exists for: every request served as fast
    # and as successfully as before, and the one series that moves is the one
    # the rule that paged evaluates. It is dated where that series fell, and
    # investigated rather than closed - five flat lines are not evidence against
    # an alarm on a sixth that did not stay flat.
    some_metrics = a_window_of(
        [CALM_ERROR_RATE] * (CALM_MINUTES + 2),
        rule_readings=[RuleReading(value=SOME_CALM_SHARE, worse_when="below")] * CALM_MINUTES
        + [RuleReading(value=0.4, worse_when="below")] * 2
    )
    published: list[IncidentEvent] = []
    investigation = an_investigation(a_model_that_says(a_turn_answering(an_explanation())))

    Scenario() \
        .given(
            calling(investigation.metrics_showed(some_metrics))
        ) \
        .when(
            lambda: investigation.investigate(
                alert=an_alert(stated_onset=None, rule="dont-care-rule"),
                publisher=published.append
            )
        ) \
        .then(
            all_of(
                _the_onset_published_was(published, some_metrics[CALM_MINUTES].bucket_id),
                _nothing_was_disproven(),
                _the_model_was_asked(investigation.model, times=1)
            )
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
def test_a_read_that_would_not_answer_is_published_as_having_gone_unanswered() -> None:
    # The third silence, and the one the two tests above set up without
    # covering. A channel nobody asked about is published as unread; a channel
    # that was asked and came back empty is deliberately not. A channel that was
    # asked and would not answer is neither of those, and with no line of its
    # own it reads on the page as the second - as a finding about the service
    # rather than a gap in what Argus was able to find out.
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(DEPENDENCIES_TOOL),
            a_turn_answering(an_explanation())
        )
    )

    Scenario() \
        .given(
            calling(investigation.metrics_showed(a_window_that_starts_calm())),
            calling(investigation.the_register_failed(
                McpToolError("MCP tool call [get_dependencies] failed: timed out")
            ))
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_reads_said_to_have_gone_unanswered(published, "the service register")
        )


@pytest.mark.unit
def test_a_tool_the_model_invented_is_not_published_as_a_read_that_would_not_answer() -> None:
    # The half that makes the line worth having at all. "There is no tool called
    # that" comes back by the same route a channel that would not answer does -
    # a failed result the model corrects on its next turn - so a line published
    # on that route alone would put a gap in the account of the incident whose
    # only cause was the model misreading the tool list it was given.
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling("get_everything_at_once"),
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
            _the_reads_said_to_have_gone_unanswered(published)
        )


@pytest.mark.unit
def test_a_window_already_read_is_not_published_as_a_read_that_would_not_answer() -> None:
    # The same distinction on the case that looks most like the thing it is not.
    # A repeat is refused because those lines are already in front of the model,
    # which means the channel answered and the investigation declined to pay for
    # the same minutes twice - the opposite of a channel that would not answer,
    # and indistinguishable from it to anything that looks only at whether the
    # result came back failed.
    some_window_start = "2026-08-20T10:30:00Z"
    some_window_end = "2026-08-20T11:00:00Z"
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(
            a_turn_calling(LOGS_TOOL, {WINDOW_START_ARG: some_window_start,
                                       WINDOW_END_ARG: some_window_end}),
            a_turn_calling(LOGS_TOOL, {WINDOW_START_ARG: some_window_start,
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
            _the_reads_said_to_have_gone_unanswered(published)
        )


@pytest.mark.unit
def test_a_log_read_the_tier_would_not_answer_is_said_rather_than_ending_the_walk() -> None:
    # The same failure as the mitigation's, one node earlier, and the path the
    # read tier is actually most likely to time out on: the log channel is the
    # expensive one, and the load that makes it time out is the polling that
    # asks for it.
    #
    # Nothing caught this. The channel called its fetcher bare and no guard sat
    # between it and the loop, so a tier that would not answer ended the whole
    # investigation - throwing away every minute already read, and the model's
    # remaining turns with them, over a gap the model is perfectly able to
    # report around. The window it asked for is already on the page as a
    # request; what was missing was the line saying it was never answered.
    #
    # The test passing at all is half the claim: an exception here would come
    # out of `investigate` and fail this before any assertion ran.
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
            calling(raising(investigation.log_fetcher, McpToolError(
                "MCP tool call [get_logs] failed: timed out"
            )))
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(
            _the_reads_said_to_have_gone_unanswered(published, "the service's log lines")
        )


@pytest.mark.unit
def test_metrics_that_could_not_be_read_stop_the_investigation_at_its_first_act() -> None:
    # The read that happens before the model is ever asked, and so the failure
    # that costs the most: it ends the investigation at its first act, and
    # nothing above it catches it - the walk dies, and the only account of why
    # is the run's own failure.
    #
    # Ending here rather than carrying on is right, and stays. Every window the
    # model could ask for is anchored on an onset, the onset is measured from
    # these minutes, and without them there is nothing to converse about - so
    # this ends the way an empty window does: one candidate, no cause named, no
    # turn bought.
    #
    # What it must not borrow is that path's account. "No metrics were
    # retrieved" is what an answer with nothing in it earns; a read nobody could
    # take is the opposite claim, and the two arriving in the same sentence is
    # exactly what this line exists to stop.
    published: list[IncidentEvent] = []
    investigation = an_investigation(
        a_model_that_says(a_turn_answering(an_explanation()))
    )

    Scenario() \
        .given(
            calling(raising(investigation.metrics_fetcher, McpToolError(
                "MCP tool call [get_metrics_summary] failed: timed out"
            )))
        ) \
        .when(
            lambda: investigation.investigate(publisher=published.append)
        ) \
        .then(all_of(
            _the_reads_said_to_have_gone_unanswered(published, "the service's metrics"),
            _the_only_candidate_says("could not be read"),
            _the_model_was_never_asked(investigation.model)
        ))


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
        fetch_dependencies=create_autospec(
            DependencyFetcher, instance=True, return_value=[]
        ),
        fetch_what_a_deployment_changed=create_autospec(
            DeploymentDiffFetcher, instance=True, return_value=[]
        ),
        fetch_rollout=create_autospec(RolloutFetcher, instance=True, return_value=[]),
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


def _the_reads_said_to_have_gone_unanswered(
    published: list[IncidentEvent], *what_was_asked: str
) -> Assertion[Findings]:
    """Every read the investigation announced it could not be given, in order.

    What this refuses matters as much as what it expects, which is why the
    expectation is exact and naming none means none. A call the model got wrong
    - a tool nobody offers, a window it had already read - was not a channel
    that would not answer, and announcing one as though it were puts a gap in
    the account of the incident where all that happened was a model correcting
    itself on its next turn.

    Compared by what was asked for rather than by count, because the two
    failures this could have are telling the wrong subject and telling none -
    and a count agrees with both.
    """
    def assertion(dont_care_findings: Findings) -> bool:
        said = [
            event.what_was_asked for event in published
            if isinstance(event, RetrievalUnanswered)
        ]

        if said != list(what_was_asked):
            raise AssertionError(
                f"Expected {list(what_was_asked)} to have been said to have gone "
                f"unanswered, got {said}."
            )

        return True

    return assertion


def _the_only_candidate_says(expected: str) -> Assertion[Findings]:
    """The one candidate a stopped investigation forms, and what it blames.

    Asserted on the summary because that is the sentence a person picking the
    incident up reads first, and the two silences this has to keep apart are a
    phrase apart in it: "no metrics were retrieved" is what an empty answer
    earns, and a read nobody could take must not borrow it.
    """
    def assertion(findings: Findings) -> bool:
        summaries = [candidate.summary for candidate in findings.candidates]

        if len(summaries) != 1:
            raise AssertionError(
                f"Expected one candidate from an investigation that stopped at "
                f"its first act, got {summaries}."
            )

        if expected not in summaries[0]:
            raise AssertionError(
                f"Expected the candidate to say [{expected}], got [{summaries[0]}]."
            )

        return True

    return assertion
