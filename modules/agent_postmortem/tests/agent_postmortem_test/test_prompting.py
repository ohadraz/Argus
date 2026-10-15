"""What the model is asked, and the one shape its answer may take.

The model is handed the incident and the figures Argus already computed, and
asked only for the parts prose can carry. Handed half an incident it will
explain the half it was shown, fluently, and nothing downstream can tell that
from an explanation of the whole.

It writes no figure itself. Every figure in the document is measured, and a
model's restatement of one - rounded, worked out again, or spelled out in words -
is not a second opinion but a second answer nobody can tell apart from the
first. So every figure it is shown carries a name after it, and it writes the
name where the figure goes; code writes the figure in.

Every instant it reads is to the second and every span is in words. The record
keeps what it measured, because the timeline is sorted on it, but a model told
"0.10 hours" or six digits past the second either does the arithmetic or
repeats the figure, and neither is its job.

The three asks are separate functions because they are separate situations. The
opening one states the incident. A refusal rides on the tool call it refuses,
because a provider that has seen a call expects its result next. And where
there was no call to refuse, the incident is put again from the start - the
only shape left, and the one this file exists to keep distinct from the other.
"""

from __future__ import annotations

import re
from datetime import timedelta

import pytest
from agent_postmortem.estimate import ErrorRates, RuleSeriesLevels, Unmeasured
from agent_postmortem.figures import (
    BEGAN_FIGURE,
    DURATION_FIGURE,
    ERRORS_AT_WORST_FIGURE,
    ERRORS_BEFORE_FIGURE,
    HELD_FIGURE,
    RECOVERED_FIGURE,
    figures_of,
    named,
    the_finding_named,
)
from agent_postmortem.log_groups import grouped
from agent_postmortem.prompting import (
    ACTION_ITEMS_FIELD,
    ADDRESSED_BY_FIELD,
    ASSUMPTIONS_FIELD,
    CAUSAL_CHAIN_FIELD,
    CITES_FIELD,
    CONTRIBUTING_FACTORS_FIELD,
    EFFECT_FIELD,
    EXECUTIVE_SUMMARY_FIELD,
    FACTOR_FIELD,
    GOT_LUCKY_FIELD,
    ITEM_FIELD,
    ITEM_TYPE_FIELD,
    LEAD_EFFECTS_FIELD,
    LEAD_FIELD,
    LESSONS_FIELD,
    REQUIRED_FIELDS,
    ROOT_CAUSE_FIELD,
    STEP_FIELD,
    SUBMIT_POSTMORTEM,
    SUBMIT_TOOL_NAME,
    SYMPTOM_FIELD,
    WENT_WELL_FIELD,
    WENT_WRONG_FIELD,
    SubmittedFactor,
    SubmittedItem,
    SubmittedPostmortem,
    SubmittedStep,
    opening_ask,
    opening_ask_again,
    rejecting,
    submit_postmortem_for,
    the_changes_labelled,
    the_evidence_labelled,
)
from argus_core import to_iso
from argus_core.models import (
    ActionItemType,
    Ask,
    ChangeEvent,
    ChangeKind,
    CitedEvidence,
    Lessons,
    OpenedPullRequest,
    Standing,
    ToolCall,
    ToolDefinition,
    ToolResults,
    Transcript,
    Turn,
    Weighing,
)
from argus_testkit import Assertion, Scenario, all_of, the_answer_was

from agent_postmortem_test.framework.builders import (
    AN_HOUR,
    ENDED_AT,
    ONSET,
    RECOVERED_AT,
    STARTED_AT,
    a_candidate,
    a_lead,
    a_measured_incident,
    a_submission_of,
    a_timeline_entry,
    an_action,
    an_answer,
    an_evidence_bundle,
)

SOME_FAULT = "the field [root_cause] was missing from your answer"

# What a lead nobody weighed is said to be, and where people wrote - words
# rather than sentences, so the prose around them is free to be improved.
WHAT_AN_UNWEIGHED_LEAD_IS_CALLED = "never weighed"
THE_THREAD = "thread"
WHEN_A_LEAD_WAS_WEIGHED = "before anything was tried"

# What a change nobody is named for is said to be made by, what a rise at or
# below nothing is told as, and what metrics nobody could read are said to be -
# which metrics that were read never are.
WHAT_AN_UNNAMED_ACTOR_IS_CALLED = "unnamed"
THE_RISE_WHEN_THERE_WAS_NONE = "Rise above baseline: none"
WHAT_AN_UNREAD_METRIC_IS_CALLED = "could not be read"

# What the alert's own words are introduced as, where its sender wrote any.
WHAT_THE_ALERT_SAID = "What the alert said"

# What a shop's integrity check reports, in its own words: two counts and an
# amount.
SOME_FINDING = ("240 of 240 shopper totals do not reconcile with the purchases behind "
                "them. The widest is short by 1,297.31.")

# What the paging rule's series is said to measure where no rise in the errors
# was measured.
THE_SERIES_AS_THE_HARM = "harm"

# A clock time carrying a fraction of a second, in either separator ISO allows.
A_TIME_FINER_THAN_THE_SECOND = re.compile(r"\d{2}:\d{2}:\d{2}[.,]\d")

# Every field the tool offers on an incident nobody wrote about.
EVERY_FIELD_ASKED = (ROOT_CAUSE_FIELD, EXECUTIVE_SUMMARY_FIELD, ASSUMPTIONS_FIELD,
                     CAUSAL_CHAIN_FIELD, CONTRIBUTING_FACTORS_FIELD,
                     ACTION_ITEMS_FIELD, LESSONS_FIELD, SYMPTOM_FIELD)

# Error rates in each relation to their baseline that the prompt tells apart.
ERRORS_THAT_STAYED_FLAT = ErrorRates(baseline=0.02, while_broken=0.02, at_its_worst=0.03)
ERRORS_THAT_FELL = ErrorRates(baseline=0.02, while_broken=0.017, at_its_worst=0.03)
ERRORS_THAT_ROSE = ErrorRates(baseline=0.02, while_broken=0.30, at_its_worst=0.34)

# A series that moved, for the cases about how it is told rather than what it did.
SOME_RULE_SERIES = RuleSeriesLevels(baseline=0.95, while_broken=0.4,
                                    at_its_worst=0.38, worse_when="below")

A_MINUTE_BEFORE_THE_ONSET = to_iso(ONSET - timedelta(minutes=1))


@pytest.mark.unit
def test_the_model_is_told_everything_the_walk_produced() -> None:
    # A model asked to explain an incident it was shown half of will explain
    # the half it was shown, confidently.
    some_alert = "checkout error rate above threshold"
    some_timeline_line = "mitigating at 12:12"
    some_candidate = "flag toggle on checkout-fallback - confirmed"
    some_action = "disabled checkout-fallback restored - confirmed"
    some_log_line = "ERROR checkout: fallback unavailable"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(alert_title=some_alert,
                                           timeline=[a_timeline_entry(some_timeline_line)],
                                           candidates=[a_candidate(some_candidate)],
                                           actions=[an_action(some_action)],
                                           log_lines=[some_log_line])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says(some_alert, some_timeline_line, some_candidate, some_action,
                  some_log_line)
        )


@pytest.mark.unit
def test_the_model_is_told_what_the_alert_itself_found() -> None:
    # The alert's own finding is a measurement - how many totals were wrong, by
    # how much, since when - made by the check that paged. Shown the alert's
    # title alone, a model attributed the count and the date to the
    # Investigator's account and hedged them as unconfirmed. Each of its
    # figures carries its name, which is how the write-up states one.
    some_finding = "240 of 240 shopper totals do not reconcile with the purchases behind them"

    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"alert_finding": some_finding})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says_on_one_line(WHAT_THE_ALERT_SAID, the_finding_named(some_finding))
        )


@pytest.mark.unit
def test_an_alert_that_said_nothing_of_its_own_is_told_by_its_title_alone() -> None:
    # A heading over nothing tells the model there is something it has failed
    # to see.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _does_not_say(WHAT_THE_ALERT_SAID)
        )


@pytest.mark.unit
def test_each_kind_of_evidence_is_labelled_on_its_own_in_the_order_it_is_shown() -> None:
    # The label is what a step of the cause cites, so every line the model can
    # rest a claim on has one, and no two share it: the narration, the changes,
    # the logs, the candidates, then the actions. Each kind counts on its own,
    # and the logs go by message, so a run reading one log line more renames
    # nothing.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(timeline=[a_timeline_entry("a line of the narration")],
                                           changes=[_a_change(reference="a change")],
                                           log_lines=["a log line"],
                                           candidates=[a_candidate("a candidate")],
                                           actions=[an_action("an action")])
        ) \
        .when(
            lambda: the_evidence_labelled(evidence)
        ) \
        .then(
            _labelled_in_order([("T1", "a line of the narration"),
                                ("P1", "a change"),
                                (grouped(["a log line"])[0].label, "a log line"),
                                ("C1", "a candidate"),
                                ("M1", "an action")])
        )


@pytest.mark.unit
def test_the_changes_are_the_evidence_shown_as_changes_under_the_same_labels() -> None:
    # The document lists them under the labels the prose cites them by, so it
    # takes them from here rather than counting them again: two countings are
    # two chances to disagree about which change P2 is.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(timeline=[a_timeline_entry("a line of the narration")],
                                           changes=[_a_change(reference="a change"),
                                                    _a_change(reference="another change")],
                                           log_lines=["a log line"])
        ) \
        .when(
            lambda: the_changes_labelled(evidence)
        ) \
        .then(
            _labelled_in_order([("P1", "a change"), ("P2", "another change")])
        )


@pytest.mark.unit
def test_a_line_outside_the_walk_is_shown_under_a_label_of_its_own() -> None:
    # In the narration where it happened, and counted apart from the walk's
    # lines - so a recorded answer citing T2 names the same line of the walk
    # whether or not somebody wrote in the thread before it this time.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[a_timeline_entry("a line of the walk"),
                          a_timeline_entry("a line outside it", outside_the_walk=True),
                          a_timeline_entry("another line of the walk")],
                log_lines=[],
                candidates=[],
                actions=[])
        ) \
        .when(
            lambda: the_evidence_labelled(evidence)
        ) \
        .then(
            _labelled_in_order([("T1", "a line of the walk"),
                                ("XW1", "a line outside it"),
                                ("T2", "another line of the walk")])
        )


@pytest.mark.unit
def test_the_model_is_shown_each_piece_of_evidence_under_its_label() -> None:
    some_log_line = "ERROR checkout"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[some_log_line])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says(f"[{grouped([some_log_line])[0].label}] {some_log_line}")
        )


@pytest.mark.unit
def test_the_model_is_shown_each_change_the_investigation_read() -> None:
    # A line saying two changes were read back, and never which, leaves the
    # model to guess at what a cause most often is. Each is shown whole - when,
    # what kind, to what, by whom and what it did - because those are the facts
    # a step of the cause would cite it for.
    some_reference = "checkout-fallback"
    some_summary = "turned the fallback off"
    some_actor = "some-engineer"
    some_change = _a_change(reference=some_reference, summary=some_summary, actor=some_actor)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(changes=[some_change])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says_on_one_line("[P1]", some_change.occurred_at, some_change.kind.value,
                              some_reference, some_summary, some_actor)
        )


@pytest.mark.unit
def test_each_figure_in_the_evidence_is_shown_with_its_name() -> None:
    # The name is the only way an answer can state a figure its evidence holds,
    # so the model reads every one with its name beside it.
    some_instant = "2026-09-02T11:59:00Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(changes=[_a_change(occurred_at=some_instant)])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says_on_one_line("[P1]", f"{some_instant} {{P1.1}}")
        )


@pytest.mark.unit
def test_a_change_nobody_is_named_for_is_said_to_be_unnamed() -> None:
    # A change no one is named for is still a real change. Shown with a blank
    # where the name goes, it reads as one made by nobody - or by "None".
    Scenario() \
        .given(
            evidence := an_evidence_bundle(changes=[_a_change(actor=None)])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says_on_one_line("[P1]", WHAT_AN_UNNAMED_ACTOR_IS_CALLED)
        )


@pytest.mark.unit
def test_a_line_that_formed_candidates_names_them_by_their_labels() -> None:
    # Said in full, the line repeats each candidate word for word, and the model
    # reads every one twice - once in the narration, once under its own label -
    # with nothing to say the two are one. Named by label, each is said once,
    # beside its confidence and what became of it. The second is not the
    # second candidate listed: a later round's best sorts between the two.
    some_candidate = "the checkout-fallback flag was disabled"
    some_other_candidate = "the noon deploy broke checkout"
    some_later_candidate = "the cache failed over"
    a_line_said_in_full = a_timeline_entry(
        f"Formed two candidate causes, best first: {some_candidate}; {some_other_candidate}"
    ).model_copy(update={"candidates": [0, 2]})

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[a_line_said_in_full],
                candidates=[a_candidate(some_candidate),
                            a_candidate(some_later_candidate),
                            a_candidate(some_other_candidate)])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says_on_one_line("[T1]", "C1, C3"),
            _says_once(some_candidate),
            _says_once(some_other_candidate)
        ))


@pytest.mark.unit
def test_the_model_is_told_the_action_items_the_record_already_holds() -> None:
    # Numbered before it is asked, so a contributing factor can name one and its
    # own proposals follow on rather than repeat them.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                actions=[],
                pull_request=OpenedPullRequest(
                    number=7, url="https://github.invalid/ohadraz/io-shop/pull/7",
                    branch="argus/fix-abc"))
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("AI-1", "Review and merge the proposed fix")
        )


@pytest.mark.unit
def test_the_model_is_told_how_long_the_incident_ran() -> None:
    # The duration is context for the prose rather than a figure the model may
    # restate as its own. It is said the way a reader says it, because a summary
    # saying "an hour and a quarter" is the sentence this is for - and "1.25
    # hours" is arithmetic the model would have to do first.
    an_hour_and_a_quarter = timedelta(hours=1, minutes=15)

    Scenario() \
        .given(
            an_incident_of_known_length := a_measured_incident(
                duration_in_hours=an_hour_and_a_quarter / AN_HOUR)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_of_known_length)
        ) \
        .then(
            _says("1 hour 15 minutes")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("span", "in_words"), [
    (timedelta(minutes=6), "6 minutes"),
    (timedelta(hours=2), "2 hours"),
    (timedelta(hours=1, minutes=15), "1 hour 15 minutes"),
    (timedelta(minutes=14, seconds=40), "14 minutes 40 seconds"),
    (timedelta(seconds=20), "20 seconds"),
    (timedelta(microseconds=500), "less than a second"),
    (timedelta(days=1, minutes=1), "1 day 1 minute"),
    (timedelta(days=6, hours=23, minutes=59), "6 days 23 hours 59 minutes"),
    (timedelta(days=7, seconds=40, microseconds=662_789), "7 days 40 seconds")
])
def test_a_span_is_told_in_days_hours_and_minutes(span: timedelta, in_words: str) -> None:
    # Never as a fraction of an hour: "0.10 hours" is six minutes a reader has
    # to work out, and a model handed it works it out or repeats it. Exact to
    # the second, like every instant the model reads, and in whole units only -
    # nothing is "2 hours 0 minutes". The model is given the measurement, not a
    # rounding of it - and its name, to state it by.
    Scenario() \
        .given(
            an_incident_held_that_long := a_measured_incident(
                time_to_close_in_hours=span / AN_HOUR)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_held_that_long)
        ) \
        .then(
            _says(f"held the incident for {in_words} {{{HELD_FIGURE}}},")
        )


@pytest.mark.unit
def test_no_instant_is_told_finer_than_the_second() -> None:
    # The record keeps its microseconds, because the timeline is sorted on
    # them. The model is told none of them: a fraction of a second is precision
    # no postmortem has a use for, and six more digits in every instant it reads.
    some_fraction_of_a_second = timedelta(microseconds=123_456)
    some_change_dated_finer_than_the_second = _a_change(
        occurred_at=(ONSET - timedelta(minutes=1) + some_fraction_of_a_second).isoformat())

    Scenario() \
        .given(
            evidence := an_evidence_bundle(started_at=STARTED_AT + some_fraction_of_a_second,
                                           ended_at=ENDED_AT + some_fraction_of_a_second,
                                           changes=[some_change_dated_finer_than_the_second]),
            measured := a_measured_incident(onset_at=ONSET + some_fraction_of_a_second,
                                            recovered_at=RECOVERED_AT + some_fraction_of_a_second)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _says(to_iso(STARTED_AT + some_fraction_of_a_second),
                  to_iso(ENDED_AT + some_fraction_of_a_second)),
            _tells_no_instant_finer_than_the_second()
        ))


@pytest.mark.unit
def test_the_model_is_told_how_far_the_errors_rose() -> None:
    # Stated as a share of traffic, which is what the measurement is. A model
    # given a bare number writes prose about a bare number.
    some_baseline = 0.02
    some_rate_while_broken = 0.30

    Scenario() \
        .given(
            an_incident_whose_errors_rose := a_measured_incident(
                error_rates=ErrorRates(baseline=some_baseline,
                                       while_broken=some_rate_while_broken,
                                       at_its_worst=0.34))
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_whose_errors_rose)
        ) \
        .then(
            _says(f"{some_rate_while_broken - some_baseline:.1%}")
        )


@pytest.mark.unit
@pytest.mark.parametrize("error_rates", [ERRORS_THAT_STAYED_FLAT, ERRORS_THAT_FELL],
                         ids=["flat", "fell"])
def test_a_rise_at_or_below_nothing_is_told_as_none(error_rates: ErrorRates) -> None:
    # The rise is attribution - the traffic that failed and would not have
    # otherwise - and none failed that way. "-0.3% of traffic failed" says the
    # opposite of what it means, and a model handed it explains a failure
    # nobody measured. The levels beside it still say what the rate was.
    Scenario() \
        .given(
            an_incident_whose_errors_did_not_rise := a_measured_incident(
                error_rates=error_rates)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_whose_errors_did_not_rise)
        ) \
        .then(
            _says(THE_RISE_WHEN_THERE_WAS_NONE)
        )


@pytest.mark.unit
def test_the_model_is_told_the_levels_as_well_as_the_rise() -> None:
    # Two questions, two numbers. Severity is what the levels answer and
    # attribution is what the rise answers, and a model handed one figure
    # labelled as the error rate went to the per-minute logs for the other -
    # correctly, because the page could not tell it what it was asking for.
    some_baseline = 0.02
    some_rate_while_broken = 0.31
    the_worst_minute = 0.34

    Scenario() \
        .given(
            an_incident_measured_at_every_level := a_measured_incident(
                error_rates=ErrorRates(baseline=some_baseline,
                                       while_broken=some_rate_while_broken,
                                       at_its_worst=the_worst_minute))
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(),
                                an_incident_measured_at_every_level)
        ) \
        .then(all_of(
            _says(f"{some_baseline:.1%}"),
            _says(f"{some_rate_while_broken:.1%}"),
            _says(f"{the_worst_minute:.1%}")
        ))


@pytest.mark.unit
def test_a_rise_nobody_could_measure_is_said_to_be_unknown_rather_than_flat() -> None:
    # The prompt has to say which of the two happened. An incident whose
    # metrics could not be read, described to the model as one where nothing
    # rose, gets prose explaining why a service that was fine had an outage -
    # and the prose will be fluent, because it always is.
    Scenario() \
        .given(
            an_incident_whose_metrics_could_not_be_read := a_measured_incident(
                error_rates=None)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(),
                                an_incident_whose_metrics_could_not_be_read)
        ) \
        .then(
            _says("not known")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("why", "said"), [
    (Unmeasured.NOTHING_READ, WHAT_AN_UNREAD_METRIC_IS_CALLED),
    (Unmeasured.NO_MINUTE_BEFORE_THE_ONSET, "before the onset"),
    (Unmeasured.NO_MINUTE_WHILE_BROKEN, "while the service was broken")
])
def test_an_error_rate_nobody_could_measure_is_told_with_the_reason(why: Unmeasured,
                                                                    said: str) -> None:
    # Three gaps that read alike as an absent figure and are not alike: a read
    # that came back empty, one that never reached the calm before a week-old
    # onset, and one holding nothing of the broken stretch. Each is what the
    # model has to explain, so each is what it is told.
    Scenario() \
        .given(
            an_incident_measured_without_error_rates := a_measured_incident(
                error_rates=None).model_copy(update={"error_rates_unmeasured": why})
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_measured_without_error_rates)
        ) \
        .then(
            _says(said)
        )


@pytest.mark.unit
@pytest.mark.parametrize("why", [Unmeasured.NO_MINUTE_BEFORE_THE_ONSET,
                                 Unmeasured.NO_MINUTE_WHILE_BROKEN])
def test_metrics_that_were_read_are_never_said_to_be_unreadable(why: Unmeasured) -> None:
    # Told as metrics that could not be read, an incident whose read returned
    # six hours of minutes - every one of them after an onset a week earlier -
    # was written up as a monitoring outage.
    Scenario() \
        .given(
            an_incident_whose_metrics_were_read := a_measured_incident(
                error_rates=None).model_copy(update={"error_rates_unmeasured": why})
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_whose_metrics_were_read)
        ) \
        .then(
            _does_not_say(WHAT_AN_UNREAD_METRIC_IS_CALLED)
        )


@pytest.mark.unit
def test_the_model_is_told_what_the_rules_series_did() -> None:
    # The series that paged, at the levels the error rate is given at, and which
    # way its rule calls worse. On an incident only that series moved in, the
    # error rate says nothing happened - and a write-up from it alone describes
    # a service that was fine.
    some_calm_share = 0.95
    some_share_while_broken = 0.4
    the_worst_minute = 0.38

    Scenario() \
        .given(
            an_incident_whose_answers_got_worse := a_measured_incident(
                rule_series=RuleSeriesLevels(baseline=some_calm_share,
                                             while_broken=some_share_while_broken,
                                             at_its_worst=the_worst_minute,
                                             worse_when="below"))
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_whose_answers_got_worse)
        ) \
        .then(
            _says(f"{some_calm_share:g}", f"{some_share_while_broken:g}",
                  f"{the_worst_minute:g}", "worse falling")
        )


@pytest.mark.unit
def test_the_rules_series_is_named_by_the_alert_it_paged_under() -> None:
    # "The series the paging rule evaluates" names nothing the model can write
    # about. The alert does: it is what the page was raised under, and a
    # write-up has to say what moved, not that something did.
    some_alert = "categoriser confidence low on io-shop"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(alert_title=some_alert)
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident(rule_series=SOME_RULE_SERIES))
        ) \
        .then(
            _says_on_one_line(some_alert, f"{SOME_RULE_SERIES.baseline:g}")
        )


@pytest.mark.unit
@pytest.mark.parametrize("error_rates", [ERRORS_THAT_STAYED_FLAT, ERRORS_THAT_FELL, None],
                         ids=["flat", "fell", "not known"])
def test_where_no_rise_in_errors_was_measured_the_rules_series_is_the_harm(
        error_rates: ErrorRates | None) -> None:
    # Every request succeeded, so failed requests say nothing happened - and a
    # write-up reading them called the harm "small to none" while its series
    # tripled. Where the errors rose not at all, or nobody could say, what the
    # series did is the harm, and the model is told to report it as that.
    Scenario() \
        .given(
            an_incident_only_its_series_measured := a_measured_incident(
                error_rates=error_rates, rule_series=SOME_RULE_SERIES)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_only_its_series_measured)
        ) \
        .then(
            _says(THE_SERIES_AS_THE_HARM)
        )


@pytest.mark.unit
def test_where_the_errors_rose_they_are_left_to_say_what_the_harm_was() -> None:
    # Failed requests are the harm wherever they rose, in the one unit every
    # reader shares. Pointed at the series as well, a model weighs a share of
    # traffic against a figure in whatever unit the rule watches.
    Scenario() \
        .given(
            an_incident_whose_errors_rose := a_measured_incident(
                error_rates=ERRORS_THAT_ROSE, rule_series=SOME_RULE_SERIES)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_whose_errors_rose)
        ) \
        .then(
            _does_not_say(THE_SERIES_AS_THE_HARM)
        )


@pytest.mark.unit
def test_an_incident_with_no_rules_series_is_told_nothing_of_one() -> None:
    # Not a line saying the series sat at nothing: an incident paged by a rule
    # watching no series of its own has none to report.
    Scenario() \
        .given(
            an_incident_paged_on_the_error_rate := a_measured_incident(rule_series=None)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_paged_on_the_error_rate)
        ) \
        .then(
            _does_not_say("paging rule")
        )


@pytest.mark.unit
def test_an_incident_that_never_recovered_is_given_as_a_lower_bound() -> None:
    # A duration cut short by the metrics running out and a duration measured
    # to a recovery carry the same kind of number and mean different things.
    # Said alike, the model reports a figure nobody measured - which is the
    # unmarked substitution this whole change exists to end.
    Scenario() \
        .given(
            an_incident_still_broken := a_measured_incident(recovered_at=None)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_still_broken)
        ) \
        .then(all_of(
            _says("had not recovered"),
            _says("at least")
        ))


@pytest.mark.unit
def test_an_incident_nobody_could_see_after_its_onset_is_written_up_as_unobserved() -> None:
    # The lower bound above is true and not enough. Where the rows stop at the
    # onset, the stretch it bounds is not one the service spent in trouble - it is
    # one nobody could see at all - and a write-up that said only "had not
    # recovered" would describe a broken shop that was never broken, and report
    # the short window before the onset as though it were the incident.
    Scenario() \
        .given(
            an_incident_nobody_could_see := a_measured_incident(
                recovered_at=None, unobserved_from=ONSET)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_nobody_could_see)
        ) \
        .then(_says("still unobserved", to_iso(ONSET)))


@pytest.mark.unit
def test_an_incident_its_metrics_covered_says_nothing_of_being_unobserved() -> None:
    Scenario() \
        .given(
            an_incident_still_broken := a_measured_incident(recovered_at=None)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_still_broken)
        ) \
        .then(_does_not_say("unobserved"))


@pytest.mark.unit
def test_the_broken_stretch_is_printed_between_both_of_its_endpoints() -> None:
    # A duration printed beside one of its ends invites the subtraction and
    # loses it. The alert is not the onset - they differ by however long the
    # rule took to trip - so a reader taking the difference between the alert
    # and the recovery gets a number Argus never reported. A stated endpoint
    # disagreeing with a stated value is the defect these measurements were
    # corrected for, one field further on.
    Scenario() \
        .given(
            an_incident_that_recovered := a_measured_incident(
                onset_at=ONSET, recovered_at=RECOVERED_AT)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_that_recovered)
        ) \
        .then(all_of(
            _says(to_iso(ONSET)),
            _says(to_iso(RECOVERED_AT)),
            _says("the onset")
        ))


@pytest.mark.unit
def test_a_stretch_dated_from_the_alert_says_that_is_where_it_was_dated_from() -> None:
    # No onset was measured, so the stretch begins at the alert - which is the
    # wrong end, late by however long the rule took to trip. Printed without
    # saying so it is indistinguishable from a measured onset, and the reader
    # would take a short outage for a fact rather than for the artefact of a
    # missing measurement.
    Scenario() \
        .given(
            an_incident_with_no_onset := a_measured_incident(onset_at=None)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_with_no_onset)
        ) \
        .then(_says("no onset could be measured"))


@pytest.mark.unit
def test_the_model_is_asked_for_no_figure_of_its_own() -> None:
    # Every column is measured, so there is nothing here for a model to
    # compute. A tool that accepted a number would be offering it the one
    # opportunity the whole design exists to withhold.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM
        ) \
        .then(
            all_of(
                _asks_only_for(*EVERY_FIELD_ASKED),
                _requires(*REQUIRED_FIELDS),
                _accepts_no_number()
            )
        )


@pytest.mark.unit
def test_the_model_is_told_to_name_a_figure_rather_than_write_one() -> None:
    # In digits it restates a measurement it cannot check, and refused its
    # digits it spelled one out: "one thousand two hundred ninety-seven and
    # thirty-one hundredths". Named, the figure is written in by code, in
    # digits, exactly as it was measured.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.description
        ) \
        .then(
            _the_description_mentions(f"{{{DURATION_FIGURE}}}", "spelled out")
        )


@pytest.mark.unit
def test_the_model_is_told_to_name_a_working_rather_than_do_one() -> None:
    # A figure the incident never measured as one - how long until it
    # recovered, how many times worse it got - is named as what to work out,
    # and code works it out from the figures as shown.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.description
        ) \
        .then(
            _the_description_mentions(f"{{{RECOVERED_FIGURE} - {BEGAN_FIGURE}}}",
                                      f"{{{ERRORS_AT_WORST_FIGURE} / {ERRORS_BEFORE_FIGURE}}}")
        )


@pytest.mark.unit
def test_the_model_is_told_a_size_it_says_has_no_number_in_it() -> None:
    # Told to say a size "roughly", a model wrote "about twenty minutes" for an
    # incident six long, and "a third" - figures in a word, which the check
    # refuses. Shown what it may say and what it may not, it is asked for an
    # answer the check accepts.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.description
        ) \
        .then(
            all_of(
                _the_description_mentions("most requests", "several minutes",
                                          "twenty minutes", "a third", "tripled"),
                _the_description_avoids("roughly")
            )
        )


@pytest.mark.unit
def test_every_sentence_the_answer_would_publish_is_read() -> None:
    # The check reads only what this yields. A field left out is prose whose
    # figures nothing refuses and whose names nothing writes in.
    some_answer = SubmittedPostmortem(
        root_cause="the root cause",
        executive_summary="the summary",
        symptom="the symptom",
        assumptions=["an assumption"],
        lead_effects={"L1": "a lead's effect"},
        causal_chain=[SubmittedStep(step="a step", cites=["T1"])],
        contributing_factors=[SubmittedFactor(factor="a factor", addressed_by=["AI-1"])],
        action_items=[SubmittedItem(item="an item", type=ActionItemType.PREVENT)],
        lessons=Lessons(went_well=["went well"], went_wrong=["went wrong"],
                        got_lucky=["got lucky"]))

    Scenario() \
        .when(
            lambda: list(some_answer.sentences())
        ) \
        .then(
            the_answer_was(["the root cause", "the summary", "the symptom", "an assumption",
                            "a lead's effect", "a step", "a factor", "an item", "went well",
                            "went wrong", "got lucky"])
        )


@pytest.mark.unit
def test_every_figure_the_model_may_name_is_shown_with_its_name() -> None:
    # A figure shown without its name is one the model can only restate. Every
    # figure Argus measured, and every figure the alert reported.
    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"alert_finding": SOME_FINDING}),
            measured := a_measured_incident(error_rates=ERRORS_THAT_ROSE,
                                            rule_series=SOME_RULE_SERIES)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _says(*(named(name, figure) for name, figure in figures_of(evidence, measured).items()))
        )


@pytest.mark.unit
def test_the_cause_is_asked_for_as_the_five_whys_from_the_symptom() -> None:
    # Asked for as "why, of the one before", a chain stopped wherever the prose
    # read well - and at people, where the field said to. The five whys starts
    # from what users saw and stops where the evidence does, never at a person;
    # the brief teaches it, and the field points the model there.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSAL_CHAIN_FIELD]["description"]
        ) \
        .then(all_of(
            _the_description_mentions("five whys", "symptom"),
            _the_description_avoids("about people")
        ))


@pytest.mark.unit
def test_the_model_is_told_what_people_told_the_incident_and_how_it_was_weighed() -> None:
    # What a person said and what the investigation made of it are one fact
    # about the incident: the words without the standing would read as advice
    # Argus followed, and the standing without the words as a verdict on
    # nothing. A lead written too late to be weighed is said to be unweighed,
    # rather than shown bare as one nobody doubted.
    a_supported_lead = a_lead(
        "the kuki flag was flipped at noon",
        Weighing(standing=Standing.SUPPORTED, reason="the flag history agrees"),
        ts="1760000100.000200"
    )
    an_unweighed_lead = a_lead("it is the database again", ts="1760000200.000300")

    Scenario() \
        .when(
            lambda: opening_ask(
                an_evidence_bundle(leads=[a_supported_lead, an_unweighed_lead]),
                a_measured_incident()
            )
        ) \
        .then(
            _says(f"L1 ({a_supported_lead.person_id}",
                  a_supported_lead.text,
                  Standing.SUPPORTED.value,
                  "the flag history agrees",
                  f"L2 ({an_unweighed_lead.person_id}",
                  an_unweighed_lead.text,
                  WHAT_AN_UNWEIGHED_LEAD_IS_CALLED)
        )


@pytest.mark.unit
def test_a_lead_is_told_under_its_writers_name_or_their_id_where_there_is_none() -> None:
    # The document names the person it owes the line to, and a platform id is
    # not a name its reader knows. Where the platform could not say, the id is
    # the one name Argus holds, and one a reader can look up.
    some_name = "Some Person"
    a_named_lead = a_lead("the kuki flag was flipped at noon",
                          ts="1760000100.000200").model_copy(update={"person_name": some_name})
    an_unnamed_lead = a_lead("it is the database again", ts="1760000200.000300")

    Scenario() \
        .when(
            lambda: opening_ask(
                an_evidence_bundle(leads=[a_named_lead, an_unnamed_lead]),
                a_measured_incident()
            )
        ) \
        .then(
            _says(f"L1 ({some_name}", f"L2 ({an_unnamed_lead.person_id}")
        )


@pytest.mark.unit
def test_a_standing_is_said_to_predate_what_the_actions_showed() -> None:
    # Weighed before anything was tried, and a lower candidate can then be the
    # one an action confirms. A lead refuted that way named the cause, and a
    # document reporting the standing bare would say the person was wrong.
    a_refuted_lead = a_lead(
        "the kuki flag was flipped at noon",
        Weighing(standing=Standing.REFUTED, reason="the flag moved after the onset")
    )

    Scenario() \
        .when(
            lambda: opening_ask(an_evidence_bundle(leads=[a_refuted_lead]),
                                a_measured_incident())
        ) \
        .then(
            _says(WHEN_A_LEAD_WAS_WEIGHED)
        )


@pytest.mark.unit
def test_an_incident_nobody_wrote_about_is_told_nothing_of_a_thread() -> None:
    # A heading over nothing tells the model there is something it has failed
    # to see, and a request that changed for every incident nobody talked
    # about would be a different request for the same document.
    Scenario() \
        .when(
            lambda: opening_ask(an_evidence_bundle(leads=[]), a_measured_incident())
        ) \
        .then(
            _does_not_say(THE_THREAD)
        )


@pytest.mark.unit
def test_an_incident_nobody_wrote_about_is_asked_for_what_it_always_was() -> None:
    # A field for saying what each lead changed, offered where there are none,
    # is a question about nothing - and a changed tool for every incident.
    Scenario() \
        .when(
            lambda: submit_postmortem_for([])
        ) \
        .then(
            all_of(
                _asks_only_for(*EVERY_FIELD_ASKED),
                _requires(*REQUIRED_FIELDS)
            )
        )


@pytest.mark.unit
def test_an_incident_people_wrote_about_is_asked_what_each_lead_changed() -> None:
    # Required rather than offered: the document owes the person who wrote an
    # answer, and an optional field is one a model leaves out whenever its
    # prose reads well without it. Still no number in it.
    Scenario() \
        .when(
            lambda: submit_postmortem_for([a_lead("the kuki flag was flipped at noon")])
        ) \
        .then(
            all_of(
                _asks_only_for(*EVERY_FIELD_ASKED, LEAD_EFFECTS_FIELD),
                _requires(*REQUIRED_FIELDS, LEAD_EFFECTS_FIELD),
                _accepts_no_number()
            )
        )


@pytest.mark.unit
def test_what_each_lead_changed_is_read_by_the_lead_it_names() -> None:
    Scenario() \
        .given(
            a_submission_saying_what_two_leads_changed := an_answer(
                lead_effects={"L1": "it named the flag reverted",
                              "L2": "it changed nothing"}
            )
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_saying_what_two_leads_changed)
        ) \
        .then(
            _says_of_the_leads({"L1": "it named the flag reverted",
                                "L2": "it changed nothing"})
        )


@pytest.mark.unit
def test_a_lead_effect_not_in_its_declared_shape_costs_only_itself() -> None:
    # As an assumption that is not a sentence costs that line: one unreadable
    # entry is one lead the check then names and asks about again, where
    # refusing the list would lose what was said of every other.
    Scenario() \
        .given(
            a_submission_with_one_readable_effect := {
                LEAD_EFFECTS_FIELD: [
                    {LEAD_FIELD: "L1", EFFECT_FIELD: "it named the flag reverted"},
                    {LEAD_FIELD: "L2"},
                    "not an entry"
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_with_one_readable_effect)
        ) \
        .then(
            _says_of_the_leads({"L1": "it named the flag reverted"})
        )


@pytest.mark.unit
def test_the_cause_is_read_as_steps_each_citing_its_evidence() -> None:
    Scenario() \
        .given(
            a_submission_with_a_chain := {
                CAUSAL_CHAIN_FIELD: [
                    {STEP_FIELD: "account pages returned 500", CITES_FIELD: ["E1", "E2"]},
                    {STEP_FIELD: "the divisor was zero", CITES_FIELD: ["E3"]}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(a_submission_with_a_chain).causal_chain
        ) \
        .then(
            the_answer_was([SubmittedStep(step="account pages returned 500", cites=["E1", "E2"]),
                            SubmittedStep(step="the divisor was zero", cites=["E3"])])
        )


@pytest.mark.unit
def test_a_chain_step_not_in_its_declared_shape_costs_only_itself() -> None:
    # A step with no words is no step; one citing in the wrong shape still
    # said something, and is read as citing nothing - which the check then
    # names, rather than the reading silently dropping a claim.
    Scenario() \
        .given(
            a_submission_with_one_readable_step := {
                CAUSAL_CHAIN_FIELD: [
                    {STEP_FIELD: "the divisor was zero", CITES_FIELD: "E3"},
                    {CITES_FIELD: ["E1"]},
                    "not a step"
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_with_one_readable_step).causal_chain
        ) \
        .then(
            the_answer_was([SubmittedStep(step="the divisor was zero", cites=[])])
        )


@pytest.mark.unit
def test_a_contributing_factor_is_read_with_the_items_that_answer_it() -> None:
    Scenario() \
        .given(
            a_submission_with_a_factor := {
                CONTRIBUTING_FACTORS_FIELD: [
                    {FACTOR_FIELD: "the canary started at 40%",
                     ADDRESSED_BY_FIELD: ["AI-2", "AI-4"]}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_with_a_factor).contributing_factors
        ) \
        .then(
            the_answer_was([SubmittedFactor(factor="the canary started at 40%",
                                            addressed_by=["AI-2", "AI-4"])])
        )


@pytest.mark.unit
def test_a_proposed_item_of_a_kind_nobody_declared_costs_only_itself() -> None:
    # The four kinds are Google's, and a fifth is a proposal nobody can file.
    Scenario() \
        .given(
            a_submission_proposing_two := {
                ACTION_ITEMS_FIELD: [
                    {ITEM_FIELD: "add a test for an empty month",
                     ITEM_TYPE_FIELD: "prevent"},
                    {ITEM_FIELD: "be more careful", ITEM_TYPE_FIELD: "vibes"}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_proposing_two).action_items
        ) \
        .then(
            the_answer_was([SubmittedItem(item="add a test for an empty month",
                                          type=ActionItemType.PREVENT)])
        )


@pytest.mark.unit
def test_the_lessons_are_read_as_three_lists() -> None:
    Scenario() \
        .given(
            a_submission_with_lessons := {
                LESSONS_FIELD: {WENT_WELL_FIELD: ["the alert fired fast"],
                                WENT_WRONG_FIELD: ["no test covered an empty month"],
                                GOT_LUCKY_FIELD: []}
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(a_submission_with_lessons).lessons
        ) \
        .then(
            the_answer_was(Lessons(went_well=["the alert fired fast"],
                                   went_wrong=["no test covered an empty month"],
                                   got_lucky=[]))
        )


@pytest.mark.unit
def test_a_refusal_rides_on_the_call_it_refuses() -> None:
    # A provider that has seen a tool call expects its result next, and the
    # result is where a refusal belongs: the model sees what it submitted, is
    # told what was wrong with it, and corrects that - rather than writing a
    # fresh document from an instruction that arrived out of nowhere.
    #
    # Marked failed, which is how a tool result says "this is something to fix"
    # rather than "this is what I found out".
    asked = opening_ask(an_evidence_bundle(), a_measured_incident())

    Scenario() \
        .given(
            submitted := a_submission_of(an_answer(), SUBMIT_TOOL_NAME)
        ) \
        .when(
            lambda: rejecting(asked, submitted, [SOME_FAULT])
        ) \
        .then(
            all_of(
                _carries_the_submission(submitted),
                _answers_the_call(submitted.tool_calls[0].id),
                _refuses_it(),
                _says(SOME_FAULT)
            )
        )


@pytest.mark.unit
def test_a_refusal_answers_every_call_the_submission_made() -> None:
    # A provider expects one result for every call in the turn, together in
    # the next message. A model that submits twice in one turn - the second a
    # placeholder - and is refused on the first call alone is a conversation
    # the provider will not continue.
    asked = opening_ask(an_evidence_bundle(), a_measured_incident())
    submitted_once = a_submission_of(an_answer(), SUBMIT_TOOL_NAME)

    Scenario() \
        .given(
            submitted_twice := submitted_once.model_copy(update={"tool_calls": [
                *submitted_once.tool_calls,
                ToolCall(id="call_2", name=SUBMIT_TOOL_NAME, arguments={})
            ]})
        ) \
        .when(
            lambda: rejecting(asked, submitted_twice, [SOME_FAULT])
        ) \
        .then(
            _refuses_every_call("call_1", "call_2")
        )


@pytest.mark.unit
def test_a_model_that_submitted_nothing_is_asked_again_from_the_start() -> None:
    # The last resort, reachable only when there is no submission to refuse. It
    # repeats what was asked rather than referring back to it, because a
    # conversation the model did not take part in the shape of is not a
    # conversation to continue.
    asked = opening_ask(an_evidence_bundle(), a_measured_incident())

    Scenario() \
        .given(
            asked
        ) \
        .when(
            lambda: opening_ask_again(asked, [SOME_FAULT])
        ) \
        .then(
            all_of(
                _carries_no_submission(),
                _says(SOME_FAULT, SUBMIT_TOOL_NAME)
            )
        )


@pytest.mark.unit
def test_a_field_that_did_not_arrive_as_prose_costs_only_itself() -> None:
    # The whole reason the answer is read leniently. A submission refused
    # outright over one badly typed field would throw away a root cause the
    # model wrote, and the document would then record as unanswered something
    # that was answered - a manufactured absence, in an agent whose entire
    # discipline is telling a real one from a missing measurement.
    some_root_cause = "the checkout fallback was disabled by a flag toggle"

    Scenario() \
        .given(
            a_submission_whose_summary_is_not_prose := {
                ROOT_CAUSE_FIELD: some_root_cause,
                EXECUTIVE_SUMMARY_FIELD: {"nested": "in the wrong shape"}
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_whose_summary_is_not_prose)
        ) \
        .then(
            all_of(
                _answered(ROOT_CAUSE_FIELD, some_root_cause),
                _left_unanswered(EXECUTIVE_SUMMARY_FIELD)
            )
        )


@pytest.mark.unit
def test_a_figure_where_prose_was_asked_for_is_still_an_answer() -> None:
    # Dropped, it would be a root cause the model supplied and the document
    # denies. Written out, it is an answer in the wrong register - which the
    # reader can see, argue with, and ask about.
    some_figure_the_model_sent = 1200

    Scenario() \
        .given(
            a_submission_answering_with_a_number := {
                ROOT_CAUSE_FIELD: some_figure_the_model_sent
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_answering_with_a_number)
        ) \
        .then(
            _answered(ROOT_CAUSE_FIELD, str(some_figure_the_model_sent))
        )


@pytest.mark.unit
def test_a_single_assumption_sent_on_its_own_is_the_list_containing_it() -> None:
    # A model with one thing to disclose sends it as a sentence rather than as
    # a list of one often enough to be worth reading. Refused, the disclosure
    # would go missing - and a disclosure is the one field whose absence the
    # document has no other way to admit to.
    some_assumption = "the log lines shown were the whole of the failing traffic"

    Scenario() \
        .given(
            a_submission_disclosing_one_thing := {
                ASSUMPTIONS_FIELD: some_assumption
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_disclosing_one_thing)
        ) \
        .then(
            _disclosed([some_assumption])
        )


@pytest.mark.unit
def test_an_assumption_that_is_not_a_sentence_costs_that_line_and_no_other() -> None:
    # One unreadable disclosure is one line lost. Refusing the list would lose
    # every other disclosure with it, and the root cause besides.
    some_assumption = "takings in NZD are not in the figure"

    Scenario() \
        .given(
            a_submission_disclosing_one_of_each := {
                ASSUMPTIONS_FIELD: [some_assumption, {"not": "a sentence"}]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_disclosing_one_of_each)
        ) \
        .then(
            _disclosed([some_assumption])
        )


@pytest.mark.unit
def test_a_submission_carrying_nothing_usable_is_empty_rather_than_refused() -> None:
    # The terminating case, and the one the rest of the agent is built on: an
    # answer nothing can be read out of is an empty answer, not an exception.
    # `checking` names every field that went unanswered, the model is asked once
    # more, and a second unusable answer is written down as an incomplete
    # document rather than thrown away entirely.
    Scenario() \
        .given(
            a_submission_of_something_else := {"nonsense": 1}
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_of_something_else)
        ) \
        .then(
            all_of(
                _left_unanswered(ROOT_CAUSE_FIELD),
                _left_unanswered(EXECUTIVE_SUMMARY_FIELD),
                _left_unanswered(CAUSAL_CHAIN_FIELD),
                _left_unanswered(CONTRIBUTING_FACTORS_FIELD),
                _left_unanswered(ACTION_ITEMS_FIELD),
                _left_unanswered(LESSONS_FIELD),
                _disclosed([])
            )
        )


def _a_change(reference: str = "dont care",
              summary: str = "dont care",
              actor: str | None = "dont care",
              occurred_at: str = A_MINUTE_BEFORE_THE_ONSET) -> ChangeEvent:
    """A flag toggled a minute before the onset, as the investigation read it."""
    return ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                       occurred_at=occurred_at,
                       reference=reference,
                       summary=summary,
                       actor=actor)


def _labelled_in_order(expected: list[tuple[str, str]]) -> Assertion[list[CitedEvidence]]:
    """Each label, and a piece of what it names - the rest of the line is the
    prompt's wording, and free to change."""
    def assertion(labelled: list[CitedEvidence]) -> bool:
        got = [(cited.label, cited.text) for cited in labelled]
        matching = (len(got) == len(expected)
                    and all(label == wanted_label and wanted_text in text
                            for (label, text), (wanted_label, wanted_text)
                            in zip(got, expected, strict=True)))

        if not matching:
            raise AssertionError(
                f"Expected the evidence labelled {expected}, in that order, got {got}.")

        return True

    return assertion


def _answered(field: str, expected: str) -> Assertion[SubmittedPostmortem]:
    def assertion(submitted: SubmittedPostmortem) -> bool:
        if getattr(submitted, field) != expected:
            raise AssertionError(
                f"Expected [{field}] to be [{expected}], got "
                f"[{getattr(submitted, field)}].")

        return True

    return assertion


def _left_unanswered(field: str) -> Assertion[SubmittedPostmortem]:
    """That a field carries nothing, rather than carrying something empty.

    The distinction the document rests on: absent is a question nobody
    answered, and an empty string on a page is an answer somebody left blank.
    """
    def assertion(submitted: SubmittedPostmortem) -> bool:
        if getattr(submitted, field) is not None:
            raise AssertionError(
                f"Expected [{field}] to have gone unanswered, got "
                f"[{getattr(submitted, field)}].")

        return True

    return assertion


def _disclosed(expected: list[str]) -> Assertion[SubmittedPostmortem]:
    def assertion(submitted: SubmittedPostmortem) -> bool:
        if submitted.assumptions != expected:
            raise AssertionError(
                f"Expected the assumptions to be {expected}, got "
                f"{submitted.assumptions}.")

        return True

    return assertion


def _says_of_the_leads(expected: dict[str, str]) -> Assertion[SubmittedPostmortem]:
    def assertion(submitted: SubmittedPostmortem) -> bool:
        if submitted.lead_effects != expected:
            raise AssertionError(
                f"Expected what each lead changed to be read as {expected}, got "
                f"{submitted.lead_effects}.")

        return True

    return assertion


def _says(*expected: str) -> Assertion[Transcript]:
    """Everything Argus put in front of the model, in whichever shape.

    An ask and a tool result are different entries and the same act: the model
    is being told something. Which one carries it is asserted separately, by
    the tests about the shape of the second attempt.
    """
    def assertion(transcript: Transcript) -> bool:
        said = _what_was_said(transcript)

        missing = [wanted for wanted in expected if wanted not in said]
        if missing:
            raise AssertionError(
                f"Expected the model to be told {missing}, and it was not: {said}")

        return True

    return assertion


def _says_on_one_line(*expected: str) -> Assertion[Transcript]:
    """Every part of one fact, together on a line of what the model was told.

    For a fact made of parts - a change and its label, a series and its name -
    where each part said somewhere is not the fact said at all.
    """
    def assertion(transcript: Transcript) -> bool:
        said = _what_was_said(transcript)

        if not any(all(wanted in line for wanted in expected) for line in said.splitlines()):
            raise AssertionError(
                f"Expected one line to tell the model {list(expected)}, and none did: {said}")

        return True

    return assertion


def _says_once(expected: str) -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        said = _what_was_said(transcript)
        times = said.count(expected)

        if times != 1:
            raise AssertionError(
                f"Expected the model to be told [{expected}] once, and it was told "
                f"it {times} times: {said}")

        return True

    return assertion


def _does_not_say(unwanted: str) -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        said = _what_was_said(transcript)

        if unwanted in said:
            raise AssertionError(
                f"Expected the model not to be told [{unwanted}], and it was: {said}")

        return True

    return assertion


def _tells_no_instant_finer_than_the_second() -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        said = _what_was_said(transcript)
        finer = A_TIME_FINER_THAN_THE_SECOND.findall(said)

        if finer:
            raise AssertionError(
                f"Expected every instant the model is told to the second, and it was "
                f"told {finer}: {said}")

        return True

    return assertion


def _the_description_mentions(*expected: str) -> Assertion[str]:
    def assertion(description: str) -> bool:
        missing = [mention for mention in expected if mention not in description]

        if missing:
            raise AssertionError(
                f"Expected the description to mention {missing}, and it does not: "
                f"[{description}].")

        return True

    return assertion


def _the_description_avoids(unwanted: str) -> Assertion[str]:
    def assertion(description: str) -> bool:
        if unwanted in description:
            raise AssertionError(
                f"Expected the description not to mention [{unwanted}], and it does: "
                f"[{description}].")

        return True

    return assertion


def _carries_the_submission(submitted: Turn) -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        if submitted not in transcript:
            raise AssertionError(
                "Expected the model's own submission to be carried back to it, "
                "and it was not.")

        return True

    return assertion


def _carries_no_submission() -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        carried = [entry for entry in transcript
                   if isinstance(entry, Turn | ToolResults)]

        if carried:
            raise AssertionError(
                f"Expected a fresh ask with nothing to answer, and it carried "
                f"{carried}")

        return True

    return assertion


def _answers_the_call(expected: str) -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        answering = [result.call_id
                     for entry in transcript if isinstance(entry, ToolResults)
                     for result in entry.results]

        if answering != [expected]:
            raise AssertionError(
                f"Expected the result to answer call [{expected}], got {answering}")

        return True

    return assertion


def _refuses_it() -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        refused = [result.failed
                   for entry in transcript if isinstance(entry, ToolResults)
                   for result in entry.results]

        if refused != [True]:
            raise AssertionError(
                "Expected the rejected submission to be marked failed, so the model "
                f"reads it as something to fix rather than as evidence, got {refused}")

        return True

    return assertion


def _refuses_every_call(*expected: str) -> Assertion[Transcript]:
    def assertion(transcript: Transcript) -> bool:
        answered = [(result.call_id, result.failed)
                    for entry in transcript if isinstance(entry, ToolResults)
                    for result in entry.results]
        wanted = [(call_id, True) for call_id in expected]

        if answered != wanted:
            raise AssertionError(
                f"Expected every call the submission made to be answered and "
                f"refused, {wanted}, got {answered}.")

        return True

    return assertion


def _asks_only_for(*expected: str) -> Assertion[ToolDefinition]:
    def assertion(tool: ToolDefinition) -> bool:
        if sorted(tool.properties) != sorted(expected):
            raise AssertionError(
                f"Expected the tool to ask for {sorted(expected)}, got "
                f"{sorted(tool.properties)}")

        return True

    return assertion


def _requires(*expected: str) -> Assertion[ToolDefinition]:
    def assertion(tool: ToolDefinition) -> bool:
        if sorted(tool.required) != sorted(expected):
            raise AssertionError(
                f"Expected the tool to require {sorted(expected)}, got "
                f"{sorted(tool.required)}")

        return True

    return assertion


def _accepts_no_number() -> Assertion[ToolDefinition]:
    """No field the model could answer with a figure.

    Not a matter of the prompt asking nicely: a field typed `number` is an
    invitation, and a model handed one fills it in.
    """
    def assertion(tool: ToolDefinition) -> bool:
        numeric = [field for field, described in tool.properties.items()
                   if described.get("type") in ("number", "integer")]

        if numeric:
            raise AssertionError(
                f"Expected the model to be asked for no figure of its own, and it "
                f"was asked for {numeric}")

        return True

    return assertion


def _what_was_said(transcript: Transcript) -> str:
    said: list[str] = []

    for entry in transcript:
        if isinstance(entry, Ask):
            said.append(entry.text)
        elif isinstance(entry, ToolResults):
            said.extend(result.content for result in entry.results)

    return "\n".join(said)
