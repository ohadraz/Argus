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
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from agent_postmortem import (
    DeploymentChangesRecord,
    EngagementAnswer,
    IncidentEvidence,
    NotPaged,
)
from agent_postmortem.estimate import ErrorRates, RuleSeriesLevels, Unmeasured
from agent_postmortem.figures import (
    AFTER_THE_WAIT_FIGURE,
    ALERT_RAISED_FIGURE,
    ALERTED_AFTER_THE_ONSET_FIGURE,
    ARGUS_STOPPED_FIGURE,
    BACK_TO_NORMAL_FIGURE,
    BEGAN_FIGURE,
    CUSTOMER_LOSS_FIGURE,
    DURATION_FIGURE,
    ERRORS_AT_WORST_FIGURE,
    ERRORS_BEFORE_FIGURE,
    HELD_FIGURE,
    LOG_READING_ENDED_FIGURE,
    LOGS_REACH_UNTIL_FIGURE,
    RULE_LOOKS_BACK_FIGURE,
    RULE_WAITS_FIGURE,
    Figure,
    figures_of,
    named,
    names_in,
    the_finding_named,
)
from agent_postmortem.log_groups import grouped
from agent_postmortem.prompting import (
    ACTION_ITEMS_FIELD,
    ADDRESSED_BY_FIELD,
    ANSWERS_FIELD,
    ASSUMPTIONS_FIELD,
    CAUSAL_CHAIN_FIELD,
    CAUSE_IN_PLAIN_WORDS_FIELD,
    CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD,
    CITES_FIELD,
    CONTRIBUTING_FACTORS_FIELD,
    EFFECT_FIELD,
    FACTOR_FIELD,
    GOT_LUCKY_FIELD,
    HAD_IT_BEEN_OTHERWISE_FIELD,
    ITEM_FIELD,
    ITEM_TYPE_FIELD,
    LABEL_FIELD,
    LEAD_EFFECTS_FIELD,
    LEAD_FIELD,
    LESSONS_FIELD,
    LOGS_SHOW_SERVING_AS_BEFORE_FIELD,
    REACHES_A_CAUSE_FIELD,
    REQUIRED_FIELDS,
    ROOT_CAUSE_FIELD,
    RULED_OUT_FIELD,
    STEP_FIELD,
    STILL_AT_RISK_FIELD,
    SUBMIT_POSTMORTEM,
    SUBMIT_TOOL_NAME,
    SYMPTOM_FIELD,
    SYMPTOM_WORDS_AT_MOST,
    WENT_WELL_FIELD,
    WENT_WRONG_FIELD,
    WHAT_FIELD,
    SubmittedFactor,
    SubmittedItem,
    SubmittedPostmortem,
    SubmittedRuledOut,
    SubmittedStep,
    figures_shown,
    opening_ask,
    opening_ask_again,
    rejecting,
    submit_postmortem_for,
    the_changes_labelled,
    the_deployment_changes_labelled,
    the_evidence_labelled,
)
from argus_core import to_iso
from argus_core.models import (
    ActionItemType,
    ActionProgress,
    Ask,
    ChangeEvent,
    ChangeKind,
    ChannelReading,
    CitedChange,
    CitedEvidence,
    CodeUse,
    DeploymentComparison,
    FileAsItRan,
    FirstTold,
    Lessons,
    LogsInTheGap,
    OpenedPullRequest,
    ReportChannel,
    Standing,
    ToolCall,
    ToolDefinition,
    ToolResults,
    Transcript,
    Turn,
    Verdict,
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
    a_resolution,
    a_submission_of,
    a_timeline_entry,
    an_action,
    an_answer,
    an_answer_without,
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
THE_RISE_WITHIN_ITS_VARIATION = "none beyond its normal variation"
A_PEAK_WITHIN_ITS_VARIATION = "no higher than"
A_VARIATION_NOBODY_COULD_MEASURE = "can't be told apart from its normal variation"
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

# What the model is asked of a series that got worse: what that meant for the
# people using the service.
WHAT_IT_MEANT_FOR_USERS = "meant for the people using the service"

# What the paging rule's wait before firing is told as: how long it is, that
# there is none, and that it could not be read.
A_RULE_S_WAIT = "before it fires"
A_RULE_FIRING_AT_ONCE = "fires as soon as its condition holds"
A_WAIT_NOBODY_COULD_READ = "waits before it fires could not be read"

# A clock time carrying a fraction of a second, in either separator ISO allows.
# A revision a file was read again at, as the brief names it: by its short form.
SOME_DEPLOYED_REVISION = "53f02e9f6cb774f7f5869637bcc879941dcbc82d"

A_TIME_FINER_THAN_THE_SECOND = re.compile(r"\d{2}:\d{2}:\d{2}[.,]\d")

# Every field the tool offers on an incident nobody wrote about.
EVERY_FIELD_ASKED = (ROOT_CAUSE_FIELD, CAUSE_IN_PLAIN_WORDS_FIELD, STILL_AT_RISK_FIELD,
                     ASSUMPTIONS_FIELD, CAUSAL_CHAIN_FIELD, CONTRIBUTING_FACTORS_FIELD,
                     ACTION_ITEMS_FIELD, LESSONS_FIELD, SYMPTOM_FIELD,
                     REACHES_A_CAUSE_FIELD, CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD)

# Error rates in each relation to their baseline that the prompt tells apart.
ERRORS_THAT_STAYED_FLAT = ErrorRates(baseline=0.02, while_broken=0.02, at_its_worst=0.03,
                                     usual_ceiling=0.03, usual_worst=0.05)
ERRORS_THAT_FELL = ErrorRates(baseline=0.02, while_broken=0.017, at_its_worst=0.03,
                              usual_ceiling=0.03, usual_worst=0.05)
ERRORS_THAT_ROSE = ErrorRates(baseline=0.02, while_broken=0.30, at_its_worst=0.34,
                              usual_ceiling=0.03, usual_worst=0.05)

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
def test_what_the_alert_said_is_evidence_under_a_label_of_its_own() -> None:
    # The check that paged measured what it paged on, and that is the first
    # thing a chain's symptom rests on. Shown with no label, a model had nothing
    # to cite it by: it cited the finding's figures, which are no evidence, and
    # then a candidate cause, which is no fact.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(timeline=[a_timeline_entry("a line of the narration")],
                                           log_lines=[],
                                           candidates=[],
                                           actions=[]).model_copy(
                update={"alert_finding": SOME_FINDING})
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("AL1", SOME_FINDING), ("T1", "a line of the narration")])
        )


@pytest.mark.unit
def test_the_model_is_shown_what_the_alert_said_under_its_label() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"alert_finding": SOME_FINDING})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says_on_one_line(WHAT_THE_ALERT_SAID, "[AL1]")
        )


@pytest.mark.unit
def test_what_the_alert_said_names_its_figures_once() -> None:
    # Its figures already have the names the model writes them by - {A1} - and
    # a second set under its label would be two names for one figure.
    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"alert_finding": SOME_FINDING})
        ) \
        .when(
            lambda: figures_shown(evidence, a_measured_incident())
        ) \
        .then(
            _names_no_figure_starting("AL1")
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
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("T1", "a line of the narration"),
                                ("P1", "a change"),
                                (grouped(["a log line"], None, ONSET.date())[0].label,
                                 "a log line"),
                                ("C1", "a candidate"),
                                ("M1", "an action")])
        )


@pytest.mark.unit
def test_the_changes_are_shown_under_the_same_labels_with_each_revision_written_short() -> None:
    # The document lists them under the labels the prose cites them by, so it
    # takes them from here rather than counting them again: two countings are
    # two chances to disagree about which change P2 is. Each carries its
    # reference as the prose writes it - a revision short, a flag as named - so
    # a row and the sentence citing it name the change alike.
    some_revision = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
    some_deploy = ChangeEvent(kind=ChangeKind.DEPLOY,
                              occurred_at=A_MINUTE_BEFORE_THE_ONSET,
                              reference=some_revision,
                              summary="dont care")
    some_toggle = _a_change(reference="a flag")

    Scenario() \
        .given(
            evidence := an_evidence_bundle(changes=[some_deploy, some_toggle])
        ) \
        .when(
            lambda: the_changes_labelled(evidence)
        ) \
        .then(
            the_answer_was([
                CitedChange(label="P1", change=some_deploy, short_reference=some_revision[:7]),
                CitedChange(label="P2", change=some_toggle, short_reference="a flag")
            ])
        )


@pytest.mark.unit
def test_two_revisions_alike_for_seven_characters_are_each_written_as_long_as_tells_them_apart(
) -> None:
    # As the prose writes them, which is what git does: a short form the two
    # share would name neither.
    some_deploys = [ChangeEvent(kind=ChangeKind.DEPLOY,
                                occurred_at=A_MINUTE_BEFORE_THE_ONSET,
                                reference=revision,
                                summary="dont care")
                    for revision in ("abcdef12" + "0" * 32, "abcdef13" + "0" * 32)]

    Scenario() \
        .given(
            evidence := an_evidence_bundle(changes=some_deploys)
        ) \
        .when(
            lambda: [cited.short_reference for cited in the_changes_labelled(evidence)]
        ) \
        .then(
            the_answer_was(["abcdef12", "abcdef13"])
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
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("T1", "a line of the walk"),
                                ("XW1", "a line outside it"),
                                ("T2", "another line of the walk")])
        )


@pytest.mark.unit
def test_a_time_alone_is_read_on_its_line_s_day_only_in_a_line_the_walk_said() -> None:
    # A line the walk said is Argus's, and says a time alone only on its own
    # day. A message written outside the walk is in its writer's words, and
    # Argus knows neither the day nor the zone of a time said in one.
    day_after_the_onset = ONSET + timedelta(days=1)

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[a_timeline_entry("anchored on 07:44:29", at=day_after_the_onset),
                          a_timeline_entry("back by 07:44:29", at=day_after_the_onset,
                                           outside_the_walk=True)])
        ) \
        .when(
            lambda: {name: figure
                     for name, figure in figures_shown(evidence, a_measured_incident()).items()
                     if name in ("T1.2", "XW1.2")}
        ) \
        .then(
            the_answer_was({"T1.2": Figure(given="07:44:29", written="Sep 03, 07:44:29 UTC"),
                            "XW1.2": Figure(given="07:44:29", written="07:44:29")})
        )


@pytest.mark.unit
def test_a_log_group_s_minute_off_the_day_it_began_is_written_in_with_its_day() -> None:
    # The minute is Argus's, read off the line's stamp in UTC: written in bare,
    # a minute of the next day read as one of the onset's.
    some_line = f"{to_iso(ONSET + timedelta(days=1))} ERROR checkout failed"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[some_line])
        ) \
        .when(
            lambda: figures_shown(evidence, a_measured_incident())[
                f"{grouped([some_line], None, ONSET.date())[0].label}.3"]
        ) \
        .then(
            the_answer_was(Figure(given="12:00", written="Sep 03, 12:00 UTC"))
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
            _says(f"[{grouped([some_log_line], None, ONSET.date())[0].label}] {some_log_line}")
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
def test_a_change_only_argus_read_is_told_as_not_the_investigator_s() -> None:
    # Listed among the investigation's own reads with nothing to tell them
    # apart, a flag only Argus's own read of the flag history found was
    # credited to the Investigator - as ruled out, set aside, or picked over.
    the_flag_both_read = _a_change(reference="monthly-spend-feature",
                                   occurred_at="2026-09-02T11:59:00Z")
    the_flag_only_argus_read = _a_change(reference="an-unrelated-feature",
                                         occurred_at="2026-09-02T12:04:00Z")

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                changes=[the_flag_both_read, the_flag_only_argus_read]
            ).model_copy(update={"changes_the_walk_alone_read": [the_flag_only_argus_read],
                                 "deploys_reading": ChannelReading.READ})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says_on_one_line("[P2]", "an-unrelated-feature",
                              "found only by Argus's read of the flag provider's history",
                              "the Investigator's read of the changes did not return it"),
            _says_once("found only by Argus's read of the flag provider's history")
        ))


@pytest.mark.unit
def test_a_change_only_argus_read_is_not_said_unreturned_by_a_read_never_made() -> None:
    # Where the Investigator never asked for the changes, there was no read of
    # them to not return it - and "Deploys not read" beneath would say so.
    the_flag_only_argus_read = _a_change(reference="an-unrelated-feature")

    Scenario() \
        .given(
            evidence := an_evidence_bundle(changes=[the_flag_only_argus_read]).model_copy(
                update={"changes_the_walk_alone_read": [the_flag_only_argus_read],
                        "deploys_reading": ChannelReading.NOT_ASKED})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says_on_one_line("[P1]", "found only by Argus's read of the flag provider's history"),
            _does_not_say("the Investigator's read of the changes did not return it")
        ))


@pytest.mark.unit
def test_the_model_is_shown_what_each_deployment_it_looked_into_changed() -> None:
    # What tells a broken configuration from bad code is inside the diff, and a
    # write-up never shown it hedges a cause the investigation read off the
    # commit. Every line as it was read, under the deployment's label.
    the_diff = ["Deployment of revision 7c3ca00 to io-shop, compared against 1a2b3c4 - "
                "the revision deployed before it.",
                "modified deploy/values-production.yaml",
                "  -  model: v1",
                "  +  model: v2"]

    Scenario() \
        .given(
            evidence := an_evidence_bundle(deployment_changes=[
                DeploymentChangesRecord(revision="7c3ca00", said=the_diff)])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says_on_one_line("[D1]", "Deployment of revision 7c3ca00"),
            _says("modified deploy/values-production.yaml", "-  model: v1", "+  model: v2")
        ))


@pytest.mark.unit
def test_a_deployment_whose_diff_lists_every_file_leaves_the_rest_as_they_were() -> None:
    # The write-up called the scrape side Code-Fix's unverified reading three
    # times, though D1 listed every file the deploy changed and the scrape
    # configuration was not among them: under the revision before, the scrape
    # collected, so it selected what it always had. Said where the diff lists
    # every file, and only there - one cut short leaves the rest unknown.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(deployment_changes=[
                DeploymentChangesRecord(revision="7c3ca00", said=["some line"],
                                        lists_every_file=True),
                DeploymentChangesRecord(revision="1a2b3c4", said=["another line"],
                                        lists_every_file=False)])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says("A file [D1] does not list is as it was at the revision [D1] compares "
                  "against."),
            _does_not_say("A file [D2] does not list")
        ))


@pytest.mark.unit
def test_an_incident_that_looked_into_no_deployment_is_shown_no_heading_for_one() -> None:
    # A heading over nothing tells the model there is something it has failed
    # to see.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(deployment_changes=[])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _does_not_say("deployment it looked into")
        )


@pytest.mark.unit
def test_an_incident_argus_took_no_action_in_is_said_to_have_none() -> None:
    # A heading over nothing tells the model there is something it has failed
    # to see. And that nothing was done is itself what happened - left out, it
    # would be left to be guessed.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("Actions it took:\n  - none")
        )

@pytest.mark.unit
def test_no_change_listed_is_said_as_what_came_of_reading_each_kind() -> None:
    # "None" under the changes reads as asked and nothing there, and a model
    # told that writes "no change preceded the onset" of an incident whose
    # deploy history nobody asked. Said in the page's words, since two
    # spellings of one fact read as two facts.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(changes=[]).model_copy(update={
                "deploys_reading": ChannelReading.NOT_ASKED,
                "flags_reading": ChannelReading.READ})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("Changes to production it read:\n"
                  "  - Deploys not read; flags read, none came back.")
        )


@pytest.mark.unit
def test_a_kind_of_change_with_no_row_is_said_beneath_the_rows_there_are() -> None:
    # A flag row alone says nothing of the deploys, and a model told only the
    # toggle writes that no deploy preceded the onset - of an incident whose
    # deploy history nobody asked. The last line under the changes says so,
    # in the page's words.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(changes=[_a_change()]).model_copy(update={
                "deploys_reading": ChannelReading.NOT_ASKED,
                "flags_reading": ChannelReading.READ})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("  - Deploys not read.\n"
                  "\n"
                  "Log lines it read, one per message:")
        )


@pytest.mark.unit
def test_no_log_line_listed_is_said_as_what_came_of_reading_the_logs() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[]).model_copy(update={
                "logs_reading": ChannelReading.UNANSWERED})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("Log lines it read, one per message:\n"
                  "  - Asked for; no answer came back.")
        )



@pytest.mark.unit
def test_what_each_deployment_changed_is_evidence_a_step_of_the_cause_may_cite() -> None:
    # Each deployment under a label of its own, in the order it was first
    # looked into, with every line it was read with.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[], log_lines=[], candidates=[], actions=[],
                deployment_changes=[
                    DeploymentChangesRecord(revision="some-revision",
                                            said=["some line", "another line"]),
                    DeploymentChangesRecord(revision="some-other-revision",
                                            said=["a third line"])])
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("D1", "another line"), ("D2", "a third line")])
        )


@pytest.mark.unit
@pytest.mark.parametrize(("comparison", "said"), [
    (DeploymentComparison.NOTHING_BEFORE_IT,
     "4c810f2 is the earliest deployment of io-shop the deployment history holds, so there "
     "was nothing before it to compare it against, and what it changed was not read."),
    (DeploymentComparison.NOT_DEPLOYED,
     "The deployment history holds no deployment of io-shop at revision 4c810f2, so nothing "
     "was compared.")
], ids=["nothing-before-it", "not-deployed"])
def test_a_deployment_with_no_comparison_behind_it_is_said_in_the_write_up_s_own_words(
        comparison: DeploymentComparison, said: str) -> None:
    # The read tier's answer is the Investigator's: bracketed for a model, and
    # with advice to one - "what it shipped can [be read], by reading the
    # repository at that revision" - which write-ups proposed as an item in 3
    # of 5. Only a comparison is a diff; the row of anything else says what
    # the history held.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(deployment_changes=[
                DeploymentChangesRecord(revision="4c810f2", said=["dont care"],
                                        comparison=comparison, service="io-shop")])
        ) \
        .when(
            lambda: the_deployment_changes_labelled(evidence)
        ) \
        .then(
            the_answer_was([CitedEvidence(label="D1", text=said)]))


@pytest.mark.unit
def test_the_model_is_shown_what_code_fix_read_in_the_source_as_a_reading_nothing_ran() -> None:
    # The mechanism, as Code-Fix read it off the code - and said to be a
    # reading, since nothing ran it: a cause resting on it rests on that.
    some_reading = "v2's vocabulary is lowercase, and the categoriser does not lowercase"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation=some_reading)
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says_on_one_line("[F1]", some_reading),
            # Nothing ran the test or the fix either, and an explanation that
            # said its test fails was repeated as fact - so the heading says so
            # of both, not of "it". And whose words they are: its "samples stop
            # while the shop keeps serving" came back as the chain's own claim.
            _says("What Code-Fix read in the source and proposed, in Code-Fix's words - "
                  "nothing ran its test or its fix, and what it claims is not what "
                  "happened unless a row of the record shows it:")
        ))


@pytest.mark.unit
def test_what_code_fix_read_is_asked_to_be_said_no_wider_than_it_read_it() -> None:
    # Two ways a write-up said Code-Fix's reading more absolutely than it was
    # given: "nothing in main does that" became "nothing in the running code
    # works it out", and "by default it only reports" became "report-only".
    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care")
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("Say what the files Code-Fix read do, with the conditions it gives - a "
                  "default as a default, never as all it does - and no wider: 'nothing in the "
                  "files it read', never 'nothing in the code'.")
        )


@pytest.mark.unit
def test_the_candidates_are_shown_as_the_investigator_s_words_and_never_to_be_cited() -> None:
    # "The shop itself kept serving normally" was a candidate's, written before
    # anything was tried, and came back in the root cause as what happened. And
    # a header saying "cite them" had a step cite one, which the check refuses -
    # a refused answer bought for every write-up that took the header at its word.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[a_candidate("dont care")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("Candidates it considered, in the Investigator's words - name them by "
                  "their labels, but cite none; what they claim is not what happened unless a "
                  "row of the record shows it:")
        )


@pytest.mark.unit
def test_a_revision_code_fix_names_is_tied_to_the_diff_that_shows_it() -> None:
    # Code-Fix read main, and said the deployed revision was one it had not
    # read. A write-up then asked somebody to check which key that revision
    # uses, though D1 - its own diff - shows it: the model had the reading and
    # the diff, and nothing between them said they were about one revision.
    some_revision = "53f02e9a1b2c3d4e5f60718293a4b5c6d7e8f901"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                fix_explanation=f"Revision {some_revision[:7]} is not in main's history and I "
                                f"have not read it.",
                deployment_changes=[DeploymentChangesRecord(revision=some_revision,
                                                            said=["+ portName: http-metrics"])])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says_on_one_line("[F1] names revision", some_revision[:7], "[D1]",
                              "say what it shows rather than ask for it to be checked")
        )


@pytest.mark.unit
def test_a_reading_naming_no_revision_a_diff_was_read_for_is_tied_to_none() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                fix_explanation="The scrape config selects the port by its old name.",
                deployment_changes=[DeploymentChangesRecord(
                    revision="53f02e9a1b2c3d4e5f60718293a4b5c6d7e8f901",
                    said=["+ portName: http-metrics"])])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _does_not_say("[F1] names revision")
        )


@pytest.mark.unit
def test_a_revision_code_fix_names_whose_read_compared_nothing_is_tied_to_no_diff() -> None:
    # "[D1] is that revision's own diff" said of a deployment nothing was
    # compared for would ask the model to say what a diff shows that nobody
    # read.
    some_revision = "53f02e9a1b2c3d4e5f60718293a4b5c6d7e8f901"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                fix_explanation=f"Revision {some_revision[:7]} is not in main's history and I "
                                f"have not read it.",
                deployment_changes=[DeploymentChangesRecord(
                    revision=some_revision, said=["dont care"],
                    comparison=DeploymentComparison.NOTHING_BEFORE_IT, service="io-shop")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _does_not_say("[F1] names revision")
        )


@pytest.mark.unit
def test_a_reading_of_a_branch_that_does_not_hold_what_ran_says_what_merging_it_changes() -> None:
    # Production ran a revision deployed from a branch never merged into the one
    # Code-Fix read. The write-up's thinking saw it and its answer dropped it:
    # nothing it was shown said what follows - that merged, the fix changes what
    # runs only once a deploy carries it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care").model_copy(
                update={"fix_branch_read": "main", "fix_holds_what_ran": False})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("[F1] was written against main, which does not contain the revision "
                  "running when the alert fired: merged, its fix changes what runs only "
                  "once a deploy carries it.")
        )


@pytest.mark.unit
@pytest.mark.parametrize("holds_what_ran", [True, None], ids=["holds-it", "not-established"])
def test_a_reading_whose_branch_holds_what_ran_or_is_not_known_to_says_nothing(
        holds_what_ran: bool | None) -> None:
    # The ordinary case says nothing, and so does one nobody established: the
    # note would be a claim the record does not make.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care").model_copy(
                update={"fix_branch_read": "main", "fix_holds_what_ran": holds_what_ran})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _does_not_say("does not contain the revision running")
        )


@pytest.mark.unit
def test_a_file_as_it_ran_is_evidence_listed_directly_beneath_what_code_fix_read() -> None:
    # Six of six write-ups called the scrape config "Code-Fix's reading,
    # nothing ran" - right about where the text came from, since nothing in the
    # record held the file as it ran. Beneath F, where the model reaches for it
    # when it reasons about the file, and named by its path and the revision.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[], log_lines=[], candidates=[], actions=[],
                fix_explanation="some account of the code").model_copy(
                update={"files_as_they_ran": [FileAsItRan(
                    path="deploy/scrape.yaml", revision=SOME_DEPLOYED_REVISION,
                    as_read=False, content="selector:\n  port: metrics\n")]})
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("F1", "some account of the code"),
                                ("S1", "deploy/scrape.yaml at 53f02e9")])
        )


@pytest.mark.unit
def test_the_files_as_they_ran_are_labelled_in_the_order_of_their_paths() -> None:
    # Labelled in the order Code-Fix's reading named them, a reworded reading
    # swapped S1 and S2 under a write-up citing each for the other's claim. A
    # file's path holds whatever the reading says.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[], log_lines=[], candidates=[], actions=[],
                fix_explanation="some account of the code").model_copy(
                update={"files_as_they_ran": [
                    FileAsItRan(path="deploy/values-production.yaml",
                                revision=SOME_DEPLOYED_REVISION, as_read=False,
                                content="portName: http-metrics\n"),
                    FileAsItRan(path="deploy/scrape.yaml", revision=SOME_DEPLOYED_REVISION,
                                as_read=False, content="selector:\n  port: metrics\n")]})
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("F1", "some account of the code"),
                                ("S1", "deploy/scrape.yaml at 53f02e9"),
                                ("S2", "deploy/values-production.yaml at 53f02e9")])
        )


@pytest.mark.unit
def test_a_file_as_it_ran_is_shown_whole_under_a_heading_saying_what_it_is() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care").model_copy(
                update={"files_as_they_ran": [FileAsItRan(
                    path="deploy/scrape.yaml", revision=SOME_DEPLOYED_REVISION,
                    as_read=False, content="selector:\n  port: metrics\n")]})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says("What ran, read at the revision running when the alert fired:"),
            _says_on_one_line("[S1]", "deploy/scrape.yaml at 53f02e9"),
            _says("port: metrics")
        ))


@pytest.mark.unit
def test_a_file_as_it_ran_that_is_what_code_fix_read_is_said_beneath_it_and_not_shown() -> None:
    # Nothing to show: what Code-Fix read is what ran, and saying so settles
    # the reading as well as the file would. Said as the files it names, not
    # ones it read: it is told every file its reading names, and one it saw
    # only three search lines of was said to have been read.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care").model_copy(
                update={"fix_branch_read": "main",
                        "files_as_they_ran": [FileAsItRan(
                            path="deploy/scrape.yaml", revision=SOME_DEPLOYED_REVISION,
                            as_read=True, content=None)]})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says("[F1] names deploy/scrape.yaml on main as it was at 53f02e9, which ran. "
                  "What [F1] says of that file holds for what ran; what it says of the "
                  "rest of main does not."),
            _does_not_say("What ran, read at the revision")
        ))


@pytest.mark.unit
def test_what_code_fix_says_of_files_that_ran_is_said_to_hold_for_those_files_alone() -> None:
    # Told only that the reading stood for what ran, a write-up carried
    # Code-Fix's "nothing in main does that" - said of the whole branch - over
    # to the running revision: "nothing in the running code works it out".
    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care").model_copy(
                update={"fix_branch_read": "main",
                        "files_as_they_ran": [
                            FileAsItRan(path="src/io_shop/spend_summary.py",
                                        revision=SOME_DEPLOYED_REVISION, as_read=True,
                                        content=None),
                            FileAsItRan(path="src/io_shop/accounts.py",
                                        revision=SOME_DEPLOYED_REVISION, as_read=True,
                                        content=None)]})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("What [F1] says of those files holds for what ran; what it says of the "
                  "rest of main does not.")
        )


@pytest.mark.unit
def test_the_uses_outside_the_patch_are_evidence_listed_beneath_what_code_fix_read() -> None:
    # A write-up wrote "nothing derived the month from history" from a reading
    # that listed the one reader adding it up to check it among those trusting
    # it. What each of those lines does is read off the code, and beneath F the
    # model has it where it reasons about the reading.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[], log_lines=[], candidates=[], actions=[],
                fix_explanation="some account of the code").model_copy(
                update={"uses_outside": [
                    CodeUse(name="total_this_month_cents", path="src/io_shop/spend_summary.py",
                            line=47, function="average_spend_per_item_this_month",
                            does="divides with it: account.total_this_month_cents // count"),
                    CodeUse(name="total_this_month_cents",
                            path="src/io_shop/spend_reconciliation.py", line=109,
                            function="reconcile_monthly_totals",
                            does="compares it with _bought_this_month(account)")]})
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([
                ("F1", "some account of the code"),
                ("U1", "total_this_month_cents at src/io_shop/spend_summary.py:47, in "
                       "average_spend_per_item_this_month: divides with it"),
                ("U2", "total_this_month_cents at src/io_shop/spend_reconciliation.py:109, in "
                       "reconcile_monthly_totals: compares it with _bought_this_month(account)")
            ])
        )


@pytest.mark.unit
def test_the_uses_outside_the_patch_stand_where_code_fix_says_otherwise_of_them() -> None:
    # The reading is Code-Fix's words and the rows are the code's: where the two
    # disagree about one of those lines, the write-up is told which stands.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care").model_copy(
                update={"uses_outside": [
                    CodeUse(name="total_this_month_cents",
                            path="src/io_shop/spend_reconciliation.py", line=109,
                            function="reconcile_monthly_totals",
                            does="compares it with _bought_this_month(account)")]})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says("How the code outside Code-Fix's patch uses what it changes, read off the "
                  "code by Argus:"),
            _says("Where [F1] says otherwise of these lines, they stand.")
        ))


@pytest.mark.unit
def test_a_corruption_s_write_up_is_told_rewriting_what_was_written_is_left_to_a_person() -> None:
    # A write-up listed under what went wrong that only Code-Fix's repair
    # script, which nothing had run, mends the totals already written short. A
    # person running it is the design, and what is left short is still at risk.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                fix_explanation="dont care",
                candidates=[a_candidate("dont care", failure_mode="silent-data-corruption")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("Rewriting what the incident wrote wrong is left to a person by design: say "
                  "it in still_at_risk and the action items, never under went_wrong.")
        )


@pytest.mark.unit
def test_a_write_up_led_by_another_mode_is_not_told_of_rewriting_what_was_written() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                fix_explanation="dont care",
                candidates=[a_candidate("dont care", failure_mode="feature-flag-toggle"),
                            a_candidate("dont care", failure_mode="silent-data-corruption")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _does_not_say("Rewriting what the incident wrote wrong")
        )


@pytest.mark.unit
def test_a_corruption_s_write_up_is_told_of_rewriting_where_code_fix_read_nothing() -> None:
    # An incident with no reading of the code can list the same thing.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", failure_mode="silent-data-corruption")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("Rewriting what the incident wrote wrong is left to a person by design")
        )


@pytest.mark.unit
def test_the_uses_outside_the_patch_are_said_to_be_read_on_the_branch_code_fix_read() -> None:
    # They were read on main, and a write-up applied them to what ran.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care").model_copy(
                update={"fix_branch_read": "main",
                        "uses_outside": [CodeUse(name="total_this_month_cents",
                                                 path="src/io_shop/spend_reconciliation.py",
                                                 line=109, function=None, does="returns it")]})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("How the code outside Code-Fix's patch uses what it changes, read on main "
                  "by Argus:")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("ran_as_read", "said"), [
    ((True, True),
     "src/io_shop/spend_reconciliation.py and src/io_shop/spend_summary.py are on main as "
     "they were at 53f02e9, which ran: what these lines say of them holds for what ran."),
    ((True, False),
     "src/io_shop/spend_reconciliation.py is on main as it was at 53f02e9, which ran: what "
     "these lines say of it holds for what ran; what they say of src/io_shop/spend_summary.py "
     "does not."),
    ((False, False),
     "These lines were read on main, not at 53f02e9, which ran: what they say does not hold "
     "for what ran.")
], ids=["all-as-they-ran", "some", "none"])
def test_what_the_uses_outside_the_patch_say_holds_for_what_ran_where_their_files_did(
        ran_as_read: tuple[bool, bool], said: str) -> None:
    # True of the revision that ran only where a file ran as main holds it. A
    # write-up applied these lines to what ran, true that once because nothing
    # else had changed. A file is named once however many of its lines are rows.
    reconciliation, summary = "src/io_shop/spend_reconciliation.py", "src/io_shop/spend_summary.py"
    uses = [CodeUse(name="total_this_month_cents", path=path, line=line, function=None,
                    does="returns it", revision=SOME_DEPLOYED_REVISION, as_read=as_read)
            for path, line, as_read in ((reconciliation, 9, ran_as_read[0]),
                                        (reconciliation, 12, ran_as_read[0]),
                                        (summary, 47, ran_as_read[1]))]

    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care").model_copy(
                update={"fix_branch_read": "main", "uses_outside": uses})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says(said)
        )


@pytest.mark.unit
def test_uses_outside_the_patch_compared_with_no_revision_say_nothing_of_what_ran() -> None:
    # No revision known to have run is nothing to hold for, as with what
    # Code-Fix read.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation="dont care").model_copy(
                update={"fix_branch_read": "main",
                        "uses_outside": [CodeUse(name="total_this_month_cents",
                                                 path="src/io_shop/spend_reconciliation.py",
                                                 line=109, function=None, does="returns it")]})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _does_not_say("what these lines say"),
            _does_not_say("These lines were read on")
        ))


@pytest.mark.unit
def test_an_incident_code_fix_said_nothing_of_is_shown_no_heading_for_it() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(fix_explanation=None)
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _does_not_say("nothing ran it")
        )


@pytest.mark.unit
def test_what_code_fix_read_in_the_source_is_evidence_a_step_of_the_cause_may_cite() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(timeline=[], log_lines=[], candidates=[], actions=[],
                                           fix_explanation="some account of the code")
        ) \
        .when(
            lambda: the_evidence_labelled(evidence, a_measured_incident())
        ) \
        .then(
            _labelled_in_order([("F1", "some account of the code")])
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
def test_candidates_blaming_the_same_move_are_shown_once_under_both_labels() -> None:
    # One cause shown twice reads as two. Shown once, under both labels, with
    # each candidate in its own words, mode and confidence - the lead's alone
    # read as the row's - and the verdict said as the tested one's on the line
    # of the one that was not, as the page says it.
    #
    # Read as different kinds of failure, they are not one cause counted
    # twice, and the heading says so. Told only that they blamed the same move,
    # a write-up said the Investigator "gave the same flag change as two
    # separate candidates", of two readings the rest of it rested on telling
    # apart - one is why the totals already written needed repairing.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("the model was upgraded", subject="categoriser.model",
                            from_state="v1", to_state="v2", confidence=0.8,
                            failure_mode="output-quality-degradation",
                            tested=True, result=Verdict.CONFIRMED),
                a_candidate("an alternative reading", subject="categoriser.model",
                            from_state="v1", to_state="v2", confidence=0.3,
                            failure_mode="config-induced-failure")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says_on_one_line("[C1, also C2] Candidates blaming the same move of "
                              "categoriser.model, each reading it as a different kind of "
                              "failure - different accounts of what it did, not one cause "
                              "counted twice - each in its own words:"),
            _says_on_one_line("C1: the model was upgraded [output-quality-degradation, "
                              "confidence 0.8", ", confirmed]"),
            _says_on_one_line("C2: an alternative reading [config-induced-failure, "
                              "confidence 0.3", ", confirmed, as tested for C1]")
        ))


@pytest.mark.unit
def test_candidates_reading_the_same_move_alike_are_still_each_shown() -> None:
    # Agreeing on the failure is not saying the same thing: each is said in its
    # own words and confidence, and the lead's verdict credited to the test
    # that reached it when that test was another's. Nor are they different
    # accounts, so the heading does not say they are.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("the model was upgraded", subject="categoriser.model",
                            from_state="v1", to_state="v2", confidence=0.8,
                            failure_mode="output-quality-degradation"),
                a_candidate("an alternative reading", subject="categoriser.model",
                            from_state="v1", to_state="v2", confidence=0.3,
                            failure_mode="output-quality-degradation",
                            tested=True, result=Verdict.CONFIRMED)])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says_on_one_line("[C1, also C2] Candidates blaming the same move of "
                              "categoriser.model, each in its own words:"),
            _says_on_one_line("C1: the model was upgraded [output-quality-degradation, "
                              "confidence 0.8", ", confirmed, as tested for C2]"),
            _says_on_one_line("C2: an alternative reading [output-quality-degradation, "
                              "confidence 0.3", ", confirmed]")
        ))


@pytest.mark.unit
def test_candidates_some_reading_one_move_alike_are_not_said_to_all_differ() -> None:
    # Three on one move, two of them alike: "each reading it as a different
    # kind of failure" is false of the two, and "not one cause counted twice"
    # of them is what the heading would be denying for no reason. So the
    # heading says they differ only where every one does.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("the model was upgraded", subject="categoriser.model",
                            from_state="v1", to_state="v2", confidence=0.6,
                            failure_mode="output-quality-degradation"),
                a_candidate("an alternative reading", subject="categoriser.model",
                            from_state="v1", to_state="v2", confidence=0.3,
                            failure_mode="config-induced-failure"),
                a_candidate("a third reading", subject="categoriser.model",
                            from_state="v1", to_state="v2", confidence=0.1,
                            failure_mode="output-quality-degradation")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says_on_one_line("Candidates blaming the same move of categoriser.model, "
                              "each in its own words:")
        )


@pytest.mark.unit
def test_candidates_of_one_cause_none_tested_are_each_said_never_tried() -> None:
    # No test, so no test to credit: each line says what its row says.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("the model was upgraded", subject="categoriser.model",
                            from_state="v1", to_state="v2"),
                a_candidate("an alternative reading", subject="categoriser.model",
                            from_state="v1", to_state="v2")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says_on_one_line("C1: the model was upgraded [", "never tried]"),
            _says_on_one_line("C2: an alternative reading [", "never tried]"),
            _does_not_say("as tested for")
        ))


@pytest.mark.unit
def test_a_candidate_tried_without_a_verdict_is_said_to_have_none() -> None:
    # Tried and never judged is not "None": the brief says of it what its row
    # on the page says.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("the model was upgraded", tested=True, result=None)])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says_on_one_line("the model was upgraded", "no verdict recorded]"),
            _does_not_say("None]")
        ))


@pytest.mark.unit
def test_a_candidate_naming_no_cause_is_said_with_only_what_became_of_it() -> None:
    # It has no failure mode and no confidence, and said as "None" they read as
    # values the Investigator gave it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("nothing in the record points at a cause",
                            confidence=None).model_copy(update={"failure_mode": None})])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says("[C1] nothing in the record points at a cause [never tried]"),
            _does_not_say("[None"),
            _does_not_say("confidence None")
        ))


@pytest.mark.unit
def test_an_investigation_that_named_no_cause_is_told_the_document_says_so_itself() -> None:
    # The tool leaves the cause fields out, and the other fields' descriptions
    # still speak of the root cause: a model not told who writes it is left to
    # guess.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[
                a_candidate("no cause determined for HighErrorRate on io-shop",
                            confidence=None).model_copy(update={"failure_mode": None})])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("No candidate names a cause", "you are not asked for either")
        )


@pytest.mark.unit
@pytest.mark.parametrize("evidence", [
    pytest.param(an_evidence_bundle(candidates=[
        a_candidate("no cause determined", confidence=None).model_copy(
            update={"failure_mode": None}),
        a_candidate("the flag was switched on")]),
        id="one names a cause"),
    pytest.param(an_evidence_bundle(disproven=True, candidates=[
        a_candidate("the alarm was disproven", confidence=None).model_copy(
            update={"failure_mode": None})]),
        id="disproven")
])
def test_an_investigation_that_named_a_cause_or_disproved_the_alarm_is_never_told_none_was(
        evidence: IncidentEvidence) -> None:
    # Where one candidate names a cause the model is asked for it, and a
    # disproven alarm's cause sentence says why it was false.
    Scenario() \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _does_not_say("No candidate names a cause")
        )


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
def test_the_model_is_told_the_record_holds_nothing_of_the_pull_request_after_it_opened() -> None:
    # Told only "Review and merge the proposed fix", one write-up said the fix
    # "passed through review" and another that a gap "stayed open until a human
    # reviewed the PR" - neither in the record. Argus never reads the pull
    # request after opening it, so it cannot say it is unreviewed either: what it
    # knows is what it did, and that nothing after is recorded. Told that, a
    # write-up's summary told its reader so too, which the document already
    # says beside the pull request.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                pull_request=OpenedPullRequest(
                    number=7, url="https://github.invalid/ohadraz/io-shop/pull/7",
                    branch="argus/fix-abc"))
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("PR #7 is a draft Argus opened for a person to review and merge. "
                  "The record holds nothing about it after that: do not say it was "
                  "reviewed, approved or merged, or that it was not - nor that the "
                  "record holds nothing, which the document says itself.")
        )


@pytest.mark.unit
def test_the_model_is_told_nothing_ran_the_fix_it_proposed() -> None:
    # Told the pull request was a draft for a person to review, a write-up
    # praised it for correcting the scrape config - a fix nothing ran.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                pull_request=OpenedPullRequest(
                    number=7, url="https://github.invalid/ohadraz/io-shop/pull/7",
                    branch="argus/fix-abc"))
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("Nothing ran its test or its fix: say what it proposes, not that "
                  "it corrects anything.")
        )


@pytest.mark.unit
def test_the_model_is_told_which_change_the_document_states_set_it_off() -> None:
    # Told only that "the document states the trigger itself", write-ups still
    # opened the root cause with the change: nothing they were shown said which
    # change the document names, so the sentence pointed at nothing. Named, and
    # nothing more: a root cause that names the change on its way to the
    # mechanism is right, and "do not open with it" contradicted the brief.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="checkout-v2",
                                        from_state="off", to_state="on",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                     occurred_at="2026-09-02T11:59:52Z",
                                     reference="checkout-v2", summary="dont care")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            all_of(
                _says_on_one_line("already states what set it off", "[P1]"),
                _does_not_say("Do not open")
            )
        )


@pytest.mark.unit
def test_an_incident_with_no_trigger_is_told_nothing_of_one() -> None:
    # A heading over nothing tells the model there is something it has failed
    # to see.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(candidates=[], changes=[])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _does_not_say("already states what set it off")
        )


@pytest.mark.unit
def test_a_trigger_nothing_tested_is_named_as_suspected() -> None:
    # The document's Trigger section says "Suspected, not confirmed" of the
    # change an untested leading candidate blamed. Named bare in the brief, it
    # is a trigger the model is told the document states as fact.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="checkout-v2",
                                        from_state="off", to_state="on")],
                changes=[ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                     occurred_at="2026-09-02T11:59:52Z",
                                     reference="checkout-v2", summary="dont care")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says_on_one_line("already states what set it off", "[P1]",
                              "suspected, not confirmed")
        )


@pytest.mark.unit
def test_the_brief_names_the_trigger_s_own_change_where_another_shares_its_instant() -> None:
    # The decoy's row is listed first. Matched by instant, the brief told the
    # model the document's trigger was the decoy - in the one case built to
    # test that confusion.
    the_instant = "2026-09-02T11:59:52Z"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="checkout-v2",
                                        from_state="off", to_state="on",
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[ChangeEvent(kind=ChangeKind.FLAG_TOGGLE, occurred_at=the_instant,
                                     reference="some-decoy-flag", summary="dont care"),
                         ChangeEvent(kind=ChangeKind.FLAG_TOGGLE, occurred_at=the_instant,
                                     reference="checkout-v2", summary="dont care")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says_on_one_line("already states what set it off", "the change [P2]")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("from_state", "to_state", "named"), [
    ("off", "on", "checkout-v2 went from off to on"),
    (None, "on", "checkout-v2 went from unknown to on"),
    ("off", None, "checkout-v2 went from off to unknown")
], ids=["both-ends", "to-state-only", "from-state-only"])
def test_a_trigger_no_change_read_dates_is_named_by_its_move_as_the_trigger_section_says_it(
        from_state: str | None, to_state: str | None, named: str) -> None:
    # The change feed read nothing, and the Trigger section still says what
    # moved, an end nobody recorded as unknown. Said nothing of, the model is
    # not told the document states it; said otherwise, the two name one change
    # two ways.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                candidates=[a_candidate("dont care", subject="checkout-v2",
                                        from_state=from_state, to_state=to_state,
                                        tested=True, result=Verdict.CONFIRMED)],
                changes=[])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says_on_one_line("already states what set it off", named)
        )


@pytest.mark.unit
def test_an_incident_that_opened_no_pull_request_is_told_nothing_of_one() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(pull_request=None)
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _does_not_say("The record holds nothing about it after that")
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
def test_how_long_argus_held_the_incident_is_said_as_nothing_but_that() -> None:
    # Not as the end of the response - a walk that recommends or mitigates
    # goes on to Code-Fix after it - nor as an ending, since an escalated
    # incident has not ended, nor as its last change of status, since a person
    # can resolve it after.
    Scenario() \
        .when(
            lambda: opening_ask(an_evidence_bundle(), a_measured_incident())
        ) \
        .then(all_of(
            _says(f"{{{ARGUS_STOPPED_FIGURE}}}. That is not how long the fault lasted"),
            _does_not_say("how long the response took"),
            _does_not_say("the incident's ending"),
            _does_not_say("status last changed")
        ))


@pytest.mark.unit
def test_how_long_argus_held_a_disproven_alarm_is_not_set_against_a_fault() -> None:
    # There was no fault to have lasted.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None, disproven=True)
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident(onset_at=None))
        ) \
        .then(all_of(
            _says(f"{{{ARGUS_STOPPED_FIGURE}}}. That is not how long Argus went on working"),
            _does_not_say("how long the fault lasted")
        ))


@pytest.mark.unit
def test_a_disproven_alarm_is_told_as_not_broken_and_as_nothing_it_cost() -> None:
    # Told the service was broken from the alert for at least the seconds Argus
    # held it, with its error rate unmeasured, a model was told of a fault the
    # window had just ruled out. Every figure of what a fault cost goes with it,
    # measured or not: there was no fault to cost.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None, disproven=True),
            measured := a_measured_incident(onset_at=None, back_to_normal_at=None,
                                            rule_series=SOME_RULE_SERIES)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _says("Not broken: the alarm was disproven - no minute of the window Argus read "
                  "departed from the service's baseline, so there is no onset, duration or "
                  "impact to report."),
            _does_not_say("Broken from"),
            _does_not_say("Error rate:"),
            _does_not_say("paging rule"),
            _does_not_say("Customer loss:")
        ))


@pytest.mark.unit
def test_the_model_is_told_how_long_the_paging_rule_waits_before_it_fires() -> None:
    # Part of the time from the onset to the alert. Not told it, a write-up
    # called the rule's own wait slow detection.
    Scenario() \
        .given(
            an_incident_paged_by_a_waiting_rule := a_measured_incident(
                rule_waits=timedelta(minutes=5))
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_paged_by_a_waiting_rule)
        ) \
        .then(
            _says(f"waits 5 minutes {{{RULE_WAITS_FIGURE}}} with its condition holding")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("waits", "said"), [
    (timedelta(minutes=5), f"waits 5 minutes {{{RULE_WAITS_FIGURE}}} with its condition holding "
                           f"before it fires. Its condition looks back over 1 minute "
                           f"{{{RULE_LOOKS_BACK_FIGURE}}}."),
    (timedelta(0), f"fires as soon as its condition holds. Its condition looks back over "
                   f"1 minute {{{RULE_LOOKS_BACK_FIGURE}}}.")
], ids=["waits", "fires-at-once"])
def test_a_disproven_alarm_s_rule_is_told_as_the_rule_s_and_not_against_an_onset(
        waits: timedelta, said: str) -> None:
    # There was no onset, and told to count the wait and the look-back into the
    # time from it to the alert, a model was pointed at a span that never was.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None, disproven=True),
            measured := a_measured_incident(onset_at=None, rule_waits=waits,
                                            rule_looks_back=timedelta(minutes=1))
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _says(said),
            _does_not_say("detection slow")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("waits", "said"), [
    (timedelta(minutes=5), f"waits 5 minutes {{{RULE_WAITS_FIGURE}}} with its condition holding "
                           f"before it fires. Its condition looks back over 1 minute "
                           f"{{{RULE_LOOKS_BACK_FIGURE}}}."),
    (timedelta(0), f"fires as soon as its condition holds. Its condition looks back over "
                   f"1 minute {{{RULE_LOOKS_BACK_FIGURE}}}.")
], ids=["waits", "fires-at-once"])
def test_an_undated_alarm_s_rule_is_told_as_the_rule_s_and_not_against_an_onset(
        waits: timedelta, said: str) -> None:
    # Not disproven, and nothing dated it: a window with no minutes in it,
    # broken from the alert as a lower bound. No onset was measured here either,
    # and the brief that said so two lines below told the model to count the
    # wait and the look-back into the time from it to the alert.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(onset_at=None, disproven=False),
            measured := a_measured_incident(onset_at=None, rule_waits=waits,
                                            rule_looks_back=timedelta(minutes=1))
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _says(said),
            _does_not_say("detection slow")
        ))


@pytest.mark.unit
def test_a_rule_that_waits_for_nothing_is_told_as_firing_at_once() -> None:
    Scenario() \
        .given(
            an_incident_paged_at_once := a_measured_incident(rule_waits=timedelta())
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_paged_at_once)
        ) \
        .then(
            _says(A_RULE_FIRING_AT_ONCE)
        )


@pytest.mark.unit
def test_a_rule_that_waits_for_nothing_is_told_how_long_after_the_onset_its_alert_came(
) -> None:
    # Told only that the rule fires as soon as its condition holds, a write-up
    # left 5m 53s from the onset to the alert unweighed.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=5, seconds=53)),
            measured := a_measured_incident(onset_at=ONSET, rule_waits=timedelta())
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _says_on_one_line(A_RULE_FIRING_AT_ONCE, "The alert came",
                              f"{{{ALERTED_AFTER_THE_ONSET_FIGURE}}} after the onset")
        )


@pytest.mark.unit
@pytest.mark.parametrize("rule_waits", [timedelta(), timedelta(minutes=5)],
                         ids=["waits-for-nothing", "waits"])
def test_the_model_is_told_how_far_back_the_rule_s_condition_looks(
        rule_waits: timedelta) -> None:
    # Part of the time from the onset to the alert can be the condition's own
    # window filling - "5m with no sample" holds only once five minutes have
    # passed with none. Told only that it may be, a write-up was left to find
    # how much in the alert's words and subtract it.
    Scenario() \
        .given(
            measured := a_measured_incident(rule_waits=rule_waits,
                                            rule_looks_back=timedelta(minutes=5))
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), measured)
        ) \
        .then(
            _says_on_one_line("Its condition looks back over", f"{{{RULE_LOOKS_BACK_FIGURE}}}",
                              "up to that much of the time from the onset to the alert")
        )


@pytest.mark.unit
def test_a_condition_looking_back_over_nothing_is_told_no_window() -> None:
    Scenario() \
        .given(
            measured := a_measured_incident(rule_waits=timedelta(), rule_looks_back=timedelta())
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), measured)
        ) \
        .then(
            _does_not_say("looks back over")
        )


@pytest.mark.unit
def test_an_alert_under_a_minute_after_the_onset_of_a_rule_that_waits_for_nothing_names_no_lag(
) -> None:
    # A measured onset is a whole minute, so seconds after it are inside what
    # it can tell. Named, they read as a lag.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(seconds=40)),
            measured := a_measured_incident(onset_at=ONSET, rule_waits=timedelta())
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _says("The alert came as soon as its condition held"),
            _does_not_say(f"{{{ALERTED_AFTER_THE_ONSET_FIGURE}}}")
        ))


@pytest.mark.unit
def test_a_rule_whose_wait_could_not_be_read_is_told_so() -> None:
    # Unread is not "fires at once", and a model told nothing assumed one.
    Scenario() \
        .given(
            an_incident_whose_rule_was_unread := a_measured_incident(rule_wait_unread=True)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_whose_rule_was_unread)
        ) \
        .then(
            _says(A_WAIT_NOBODY_COULD_READ)
        )


@pytest.mark.unit
def test_the_model_is_told_how_long_the_alert_came_after_its_rule_s_wait() -> None:
    # Told to count the wait before calling detection slow, a write-up counted
    # it and called detection slow anyway: what was left after the wait was
    # never shown.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=6, seconds=30)),
            measured := a_measured_incident(onset_at=ONSET, rule_waits=timedelta(minutes=5))
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _says(f"The alert came 1 minute 30 seconds {{{AFTER_THE_WAIT_FIGURE}}} after that "
                  f"wait ended.")
        )


@pytest.mark.unit
def test_an_alert_under_a_minute_after_its_rule_s_wait_is_told_as_coming_when_it_allowed() -> None:
    # A measured onset is a whole minute, so seconds after the wait are inside
    # what it can tell. Named, they read as a lag.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=5, seconds=16)),
            measured := a_measured_incident(onset_at=ONSET, rule_waits=timedelta(minutes=5))
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _says("The alert came as soon as that wait allowed"),
            _does_not_say(f"{{{AFTER_THE_WAIT_FIGURE}}}")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("held", "said"), [
    (True, ", so the condition held before the measured onset"),
    (False, ", though not every minute of that wait before the measured onset met it"),
    (None, "")
], ids=["held", "did-not-hold", "unread"])
def test_an_alert_sooner_than_its_rule_s_wait_is_told_as_the_page_says_it(
        held: bool | None, said: str) -> None:
    # Told it came "as soon as that wait ended", the model would read an alert
    # sooner than the wait as one on time - when the condition held before the
    # measured onset, which the page says beside the gap.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=4, seconds=51)),
            measured := a_measured_incident(onset_at=ONSET, rule_waits=timedelta(minutes=5),
                                            rule_held_before_the_onset=held)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _says(f"The time from the onset to the alert is shorter than the 5 minutes "
                  f"{{{RULE_WAITS_FIGURE}}} its rule's condition must hold before it fires"
                  f"{said}.")
        )


@pytest.mark.unit
def test_an_alert_dated_before_the_onset_is_told_as_the_page_says_it() -> None:
    # A gap below nothing is no time "shorter than" the wait - it is an alert
    # before the measured onset, which is what the page says beside it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET - timedelta(seconds=40)),
            measured := a_measured_incident(onset_at=ONSET, rule_waits=timedelta(minutes=5))
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _says("The alert came before the measured onset."),
            _does_not_say("shorter than")
        ))


@pytest.mark.unit
def test_with_no_onset_measured_nothing_is_told_of_the_alert_against_its_wait() -> None:
    # The gap is from the onset; without one there is nothing to weigh.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(alerted_at=ONSET + timedelta(minutes=6, seconds=30)),
            measured := a_measured_incident(onset_at=None, rule_waits=timedelta(minutes=5))
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _does_not_say("after that wait ended"),
            _does_not_say("as soon as that wait allowed"),
            _does_not_say("The time from the onset to the alert")
        ))


@pytest.mark.unit
def test_an_incident_no_rule_paged_for_is_told_nothing_of_a_wait() -> None:
    Scenario() \
        .given(
            an_incident_no_rule_paged_for := a_measured_incident()
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_no_rule_paged_for)
        ) \
        .then(
            all_of(
                _does_not_say(A_RULE_S_WAIT),
                _does_not_say(A_RULE_FIRING_AT_ONCE)
            )
        )


@pytest.mark.unit
def test_a_rule_is_told_as_firing_never_as_paging() -> None:
    # "Paged" is what happens to a person. A brief that said "the paging rule"
    # had a write-up say "the alert paged" in its chain and "nobody was paged"
    # in its assumptions, of the same incident - one word, two meanings.
    Scenario() \
        .given(
            an_incident_a_waiting_rule_fired_for := a_measured_incident(
                rule_waits=timedelta(minutes=5), rule_series=SOME_RULE_SERIES)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_a_waiting_rule_fired_for)
        ) \
        .then(
            all_of(
                _says("The alert rule waits", "which its alert rule evaluates"),
                _does_not_say("paging"),
                _does_not_say("that paged")
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(("engaged", "told"), [
    (NotPaged(), "Nobody was paged: no on-call incident was linked to this one."),
    (EngagementAnswer(minutes=0, responders=0),
     "Somebody was paged: an on-call incident was linked to this one."),
    (None, "Whether anybody was paged could not be read.")
], ids=["nobody-paged", "somebody-paged", "unread"])
def test_the_model_is_told_whether_anybody_was_paged(
        engaged: EngagementAnswer | NotPaged | None, told: str) -> None:
    # Never told, a model fills the gap from habit: an alert pages somebody.
    # The document's assumptions then said nobody was, of an incident whose
    # chain said the alert paged. Told the fact, it has nothing to fill - and
    # told that a rule fires and a person is paged, one word for each.
    Scenario() \
        .given(
            some_incident := a_measured_incident().model_copy(update={"engaged": engaged})
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), some_incident)
        ) \
        .then(
            _says(told, "An alert rule fires; a person is paged.")
        )


@pytest.mark.unit
def test_a_post_where_nobody_was_paged_is_told_with_the_one_claim_it_refutes_refused() -> None:
    # Told only that nobody was paged, a write-up said no person was told at all,
    # of an incident Argus had announced in its thread. Told to say nothing of
    # who was told, the next dropped that nobody was paged as well - so the one
    # claim is refused by name, and the finding kept open beside it.
    some_post = FirstTold(channel=ReportChannel.SLACK, at=STARTED_AT + timedelta(seconds=2))

    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"first_told": some_post}),
            some_incident := a_measured_incident().model_copy(update={"engaged": NotPaged()})
        ) \
        .when(
            lambda: opening_ask(evidence, some_incident)
        ) \
        .then(
            _says("Nobody was paged: no on-call incident was linked to this one. An alert rule "
                  "fires; a person is paged. Argus first posted about the incident in Slack at "
                  f"{to_iso(some_post.at)} {{first_told}}, and the document says so already: "
                  "leave that post out, and do not say that no person was told. That nobody was "
                  "paged is a finding of its own.")
        )


@pytest.mark.unit
@pytest.mark.parametrize("engaged", [EngagementAnswer(minutes=0, responders=0), None],
                         ids=["somebody-paged", "unread"])
def test_a_post_is_not_told_where_nobody_is_known_unpaged(
        engaged: EngagementAnswer | None) -> None:
    # The claim it refutes is made only of an incident nobody was paged for.
    dont_care_post = FirstTold(channel=ReportChannel.SLACK, at=STARTED_AT)

    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"first_told": dont_care_post}),
            some_incident := a_measured_incident().model_copy(update={"engaged": engaged})
        ) \
        .when(
            lambda: opening_ask(evidence, some_incident)
        ) \
        .then(
            _does_not_say("first posted")
        )


@pytest.mark.unit
def test_the_symptom_is_asked_for_without_saying_a_metric_paged() -> None:
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[SYMPTOM_FIELD]["description"]
        ) \
        .then(
            _the_description_avoids("paged")
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
                                            back_to_normal_at=(
                                                RECOVERED_AT + some_fraction_of_a_second
                                            ))
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
                                       at_its_worst=0.34,
                                       usual_ceiling=0.03, usual_worst=0.05))
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
def test_a_rise_within_the_rate_s_own_variation_is_told_as_none_beyond_it() -> None:
    # A service that idles between one and two percent goes above its average
    # in half its quiet stretches, and a write-up told each one was a rise
    # blamed the incident for noise - its peak with it.
    Scenario() \
        .given(
            an_incident_whose_errors_wandered := a_measured_incident(
                error_rates=ErrorRates(baseline=0.010, while_broken=0.011, at_its_worst=0.015,
                                       usual_ceiling=0.012, usual_worst=0.02))
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_whose_errors_wandered)
        ) \
        .then(all_of(
            _says(THE_RISE_WITHIN_ITS_VARIATION),
            _says(A_PEAK_WITHIN_ITS_VARIATION)
        ))


@pytest.mark.unit
def test_a_rise_against_a_calm_too_short_to_vary_in_is_told_as_unknowable() -> None:
    # With too little calm to say how high the rate goes on its own, a rise is
    # one nobody can tell from noise - which is not the same as none.
    Scenario() \
        .given(
            an_incident_with_too_little_calm := a_measured_incident(
                error_rates=ErrorRates(baseline=0.02, while_broken=0.30, at_its_worst=0.34,
                                       usual_ceiling=None, usual_worst=None))
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_with_too_little_calm)
        ) \
        .then(
            _says(A_VARIATION_NOBODY_COULD_MEASURE)
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
                                       at_its_worst=the_worst_minute,
                                       usual_ceiling=0.03, usual_worst=0.05))
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
def test_a_rise_nobody_could_measure_is_said_to_be_unmeasured_rather_than_flat() -> None:
    # The prompt has to say which of the two happened. An incident whose
    # metrics could not be read, described to the model as one where nothing
    # rose, gets prose explaining why a service that was fine had an outage -
    # and the prose will be fluent, because it always is.
    #
    # And said as the metrics' gap rather than the record's. Told the error rate
    # was not known, a model that had cited the shop's own warned rate from its
    # logs wrote that no error rate existed, and asked for the logs it had
    # already read to be reviewed.
    Scenario() \
        .given(
            an_incident_whose_metrics_could_not_be_read := a_measured_incident(
                error_rates=None)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(),
                                an_incident_whose_metrics_could_not_be_read)
        ) \
        .then(all_of(
            _says("Error rate: not measured by the metrics"),
            _does_not_say("not known")))


@pytest.mark.unit
@pytest.mark.parametrize(("why", "said"), [
    (Unmeasured.NOTHING_READ, WHAT_AN_UNREAD_METRIC_IS_CALLED),
    (Unmeasured.NO_MINUTE_IN_THE_HOUR_BEFORE_THE_ONSET, "from the hour before the onset"),
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
def test_an_incident_none_of_whose_metrics_could_be_read_is_told_its_unread_deploys_are_by_design(
) -> None:
    # Where no minute of the metrics came back and the alert gave no time
    # either, there is nothing to look back from, so the walk read no deploys or
    # logs and escalated. Never told it, a write-up listed the reads it never
    # made as what went wrong - which the document already says.
    #
    # Not told to leave them unsaid: a step of the chain says what it could not
    # rule out, and these are why.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(escalated=True),
            an_incident_whose_metrics_could_not_be_read := a_measured_incident(
                error_rates=None, onset_at=None).model_copy(
                    update={"error_rates_unmeasured": Unmeasured.NOTHING_READ})
        ) \
        .when(
            lambda: opening_ask(evidence, an_incident_whose_metrics_could_not_be_read)
        ) \
        .then(all_of(
            _says("no time from the alert, there was nothing to look back from"),
            _says("do not list it as something that went wrong"),
            _says("belongs in the action items"),
            _does_not_say("do not say it again")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("why", "onset_at", "anchored_at", "escalated", "deploys", "logs"), [
    pytest.param(Unmeasured.NO_MINUTE_IN_THE_HOUR_BEFORE_THE_ONSET, None, None, True,
                 ChannelReading.NOT_ASKED, ChannelReading.NOT_ASKED,
                 id="metrics read, none before the onset"),
    pytest.param(Unmeasured.NO_MINUTE_WHILE_BROKEN, None, None, True,
                 ChannelReading.NOT_ASKED, ChannelReading.NOT_ASKED,
                 id="metrics read, none while broken"),
    pytest.param(Unmeasured.NOTHING_READ, ONSET, None, True,
                 ChannelReading.NOT_ASKED, ChannelReading.NOT_ASKED,
                 id="an onset the alert dated"),
    pytest.param(Unmeasured.NOTHING_READ, None, ONSET, True,
                 ChannelReading.NOT_ASKED, ChannelReading.NOT_ASKED,
                 id="anchored on the alarm's minute"),
    pytest.param(Unmeasured.NOTHING_READ, None, None, True,
                 ChannelReading.READ, ChannelReading.NOT_ASKED,
                 id="deploys read"),
    pytest.param(Unmeasured.NOTHING_READ, None, None, True,
                 ChannelReading.NOT_ASKED, ChannelReading.READ,
                 id="logs read"),
    pytest.param(Unmeasured.NOTHING_READ, None, None, False,
                 ChannelReading.NOT_ASKED, ChannelReading.NOT_ASKED,
                 id="ended other than escalated")
])
def test_an_incident_that_line_is_false_of_is_never_told_there_was_nothing_to_look_back_from(
        why: Unmeasured, onset_at: datetime | None, anchored_at: datetime | None,
        escalated: bool, deploys: ChannelReading, logs: ChannelReading) -> None:
    # The line says four things - no minute of metrics, nothing else to date or
    # anchor the walk, no deploys or logs read, and an escalation - and of an
    # incident where any one is untrue, it is false. A walk anchored on the
    # alarm's minute that ran out before reading anything had a minute to read
    # from.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(escalated=escalated).model_copy(
                update={"deploys_reading": deploys, "logs_reading": logs,
                        "anchored_at": anchored_at}),
            measured := a_measured_incident(error_rates=None, onset_at=onset_at).model_copy(
                update={"error_rates_unmeasured": why})
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _does_not_say("nothing to look back from")
        )


@pytest.mark.unit
@pytest.mark.parametrize("why", [Unmeasured.NO_MINUTE_IN_THE_HOUR_BEFORE_THE_ONSET,
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
@pytest.mark.parametrize("why", list(Unmeasured))
def test_no_reason_an_error_rate_went_unmeasured_says_it_is_not_known(why: Unmeasured) -> None:
    # Over every reason there is, so a reason added later cannot bring the
    # phrase back: what is missing is the metrics' figure, and the record may
    # hold the service's own word on its rate elsewhere.
    Scenario() \
        .given(
            an_incident_measured_without_error_rates := a_measured_incident(
                error_rates=None).model_copy(update={"error_rates_unmeasured": why})
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_measured_without_error_rates)
        ) \
        .then(
            _does_not_say("not known")
        )


@pytest.mark.unit
def test_an_incident_nobody_could_see_is_not_said_to_have_been_broken() -> None:
    # The line before this one says the metrics did not cover the stretch, not one
    # the service is known to have spent in trouble. A reason naming its minutes
    # as the ones "while the service was broken" contradicts that, and hands the
    # model an outage the evidence does not show.
    Scenario() \
        .given(
            an_incident_nobody_could_see := a_measured_incident(
                error_rates=None, back_to_normal_at=None, metrics_stopped_at=ONSET
            ).model_copy(update={"error_rates_unmeasured": Unmeasured.NO_MINUTE_WHILE_BROKEN})
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_nobody_could_see)
        ) \
        .then(all_of(
            _says("none were collected after the metrics stopped"),
            _does_not_say("none from while the service was broken")))


@pytest.mark.unit
@pytest.mark.parametrize(("back_to_normal_at", "said"), [
    (RECOVERED_AT, "Customer loss:"),
    (None, "Customer loss: at least")
], ids=["measured", "a-lower-bound"])
def test_the_model_is_told_the_customer_loss_and_how_it_was_measured(
        back_to_normal_at: datetime | None, said: str) -> None:
    # Argus's one direct measure of who the incident affected. Never told it,
    # a write-up over a loss of nothing said the shop only "appears to have
    # kept serving". With how it is measured, so it is weighed as a shortfall
    # in takings and not as a count of shoppers - and as a floor where the
    # service was not seen back to normal, as the page says it.
    Scenario() \
        .given(
            measured := a_measured_incident(loss=Decimal("1297.31"),
                                            back_to_normal_at=back_to_normal_at)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), measured)
        ) \
        .then(
            _says_on_one_line(said, f"{{{CUSTOMER_LOSS_FIGURE}}}",
                              "fell short of the same hours whole weeks earlier")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("back_to_normal_at", "said"), [
    (RECOVERED_AT, "Customer loss: none - "),
    (None, "Customer loss: none so far - ")
], ids=["measured", "a-lower-bound"])
def test_a_customer_loss_of_nothing_is_told_as_none(
        back_to_normal_at: datetime | None, said: str) -> None:
    # In words, as the page says it: "0.00 USD" reads as a figure nobody filled
    # in. "So far" where the takings were counted with the service not seen back
    # to normal.
    Scenario() \
        .given(
            measured := a_measured_incident(loss=Decimal(0),
                                            back_to_normal_at=back_to_normal_at)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), measured)
        ) \
        .then(
            _says_on_one_line(said, "no more than those hours vary on their own")
        )


@pytest.mark.unit
def test_a_customer_loss_nobody_estimated_is_told_as_not_estimated() -> None:
    Scenario() \
        .given(
            measured := a_measured_incident(baseline_revenue=None)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), measured)
        ) \
        .then(
            _says("Customer loss: not estimated")
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
def test_the_rules_series_is_named_by_the_alerts_own_words_where_it_sent_any() -> None:
    # A title is the rule's name, and three latency rules share one. The words
    # the alert was sent with say which series it is - which percentile, which
    # share of purchases - and that is what a write-up has to name. Its figures
    # go by the names the alert's own line gives them, being the same figures.
    some_words = "Share of purchases categorised confidently below 80% for 5m"

    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(update={"alert_finding": some_words})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident(rule_series=SOME_RULE_SERIES))
        ) \
        .then(
            _says_on_one_line("confidently below 80% {A1} for 5m {A2}",
                              f"{SOME_RULE_SERIES.baseline:g}")
        )


@pytest.mark.unit
def test_the_rules_series_is_named_by_its_query_as_written() -> None:
    # The alert's words are the rule's condition - its threshold and its wait -
    # and a series named by them is named by when it pages. The query is what
    # the series is, said as written: its numbers are none of the incident's,
    # and tagged as figures they would be offered as some. Said in words in the
    # document, since a reader does not read PromQL.
    some_query = 'max(http_request_duration_seconds{quantile="0.99"}) * 1000'

    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(
                update={"alert_finding": "p99 latency above threshold for 5m"})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident(rule_series=SOME_RULE_SERIES)
                                .model_copy(update={"rule_series_query": some_query}))
        ) \
        .then(
            _says_on_one_line(f"The series behind the alert, `{some_query}`",
                              'its alert said "p99 latency above threshold for 5m {A1}"',
                              f"{SOME_RULE_SERIES.baseline:g}",
                              "in words, not by its query")
        )


@pytest.mark.unit
def test_a_rules_series_whose_query_is_unknown_is_told_by_what_its_alert_said() -> None:
    # No query to name it by, and the alert's words still its condition: said
    # as the alert's, and nothing asked of a query the model was never shown.
    Scenario() \
        .given(
            evidence := an_evidence_bundle().model_copy(
                update={"alert_finding": "p99 latency above threshold for 5m"})
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident(rule_series=SOME_RULE_SERIES))
        ) \
        .then(all_of(
            _says_on_one_line('The series behind the alert - its alert said "p99 latency',
                              f"{SOME_RULE_SERIES.baseline:g}"),
            _does_not_say("by its query")
        ))


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
def test_where_the_errors_rose_another_series_is_still_asked_what_it_meant_for_users() -> None:
    # A rule watching something besides the failed requests - a latency, a
    # share filed with confidence - says something of its own about the people
    # using the service, and the failed requests rising does not say it for it.
    Scenario() \
        .given(
            an_incident_paged_on_another_series := a_measured_incident(
                error_rates=ERRORS_THAT_ROSE, rule_series=SOME_RULE_SERIES)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_paged_on_another_series)
        ) \
        .then(
            _says(WHAT_IT_MEANT_FOR_USERS)
        )


@pytest.mark.unit
def test_a_rule_paging_on_the_error_rate_is_not_asked_what_its_series_meant_for_users() -> None:
    # Its series is the failed requests, so what their rise meant for the
    # people using the service is the symptom the write-up has already said -
    # and asked it again, about 8 write-ups in 28 said the symptom twice.
    the_error_rate_as_the_rules_series = RuleSeriesLevels(
        baseline=ERRORS_THAT_ROSE.baseline, while_broken=ERRORS_THAT_ROSE.while_broken,
        at_its_worst=ERRORS_THAT_ROSE.at_its_worst, worse_when="above")

    Scenario() \
        .given(
            an_incident_paged_on_its_error_rate := a_measured_incident(
                error_rates=ERRORS_THAT_ROSE, rule_series=the_error_rate_as_the_rules_series,
                rule_series_is_the_error_rate=True)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_paged_on_its_error_rate)
        ) \
        .then(
            _does_not_say(WHAT_IT_MEANT_FOR_USERS)
        )


@pytest.mark.unit
@pytest.mark.parametrize("series", [
    RuleSeriesLevels(baseline=0.95, while_broken=0.95, at_its_worst=0.9, worse_when="below"),
    RuleSeriesLevels(baseline=0.95, while_broken=0.97, at_its_worst=0.93, worse_when="below"),
    RuleSeriesLevels(baseline=0.2, while_broken=0.2, at_its_worst=0.25, worse_when="above"),
    RuleSeriesLevels(baseline=0.2, while_broken=0.15, at_its_worst=0.22, worse_when="above")
], ids=["level falling-worse", "better falling-worse", "level rising-worse",
        "better rising-worse"])
@pytest.mark.parametrize("error_rates", [ERRORS_THAT_STAYED_FLAT, ERRORS_THAT_ROSE],
                         ids=["errors flat", "errors rose"])
def test_a_rules_series_that_did_not_get_worse_is_not_reported_as_the_harm(
        series: RuleSeriesLevels, error_rates: ErrorRates) -> None:
    # Asked what a series that held meant for the people using the service, a
    # model has to invent a meaning for it or report nothing as the harm.
    Scenario() \
        .given(
            an_incident_whose_series_held := a_measured_incident(
                error_rates=error_rates, rule_series=series)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_whose_series_held)
        ) \
        .then(all_of(
            _does_not_say(WHAT_IT_MEANT_FOR_USERS),
            _does_not_say(THE_SERIES_AS_THE_HARM)
        ))


@pytest.mark.unit
def test_a_rules_series_in_no_unit_anybody_named_is_said_to_be_so() -> None:
    # Left unsaid, a model writes a bare number beside an alert in percent - or
    # supplies a unit nothing measured. Told, it says the levels as numbers.
    Scenario() \
        .given(
            an_incident_whose_series_names_no_unit := a_measured_incident(
                rule_series=SOME_RULE_SERIES, rule_series_unit=None)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_whose_series_names_no_unit)
        ) \
        .then(
            _says("does not say what unit its series is in")
        )


@pytest.mark.unit
def test_a_rules_series_in_a_named_unit_is_not_said_to_be_in_none() -> None:
    Scenario() \
        .given(
            an_incident_whose_series_is_in_milliseconds := a_measured_incident(
                rule_series=SOME_RULE_SERIES, rule_series_unit="ms")
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(),
                                an_incident_whose_series_is_in_milliseconds)
        ) \
        .then(
            _does_not_say("does not say what unit its series is in")
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
def test_an_incident_never_back_to_normal_is_given_as_a_lower_bound_to_its_close() -> None:
    # A duration cut short by the incident closing and a duration measured to the
    # service back to normal carry the same kind of number and mean different
    # things. Said alike, the model reports a figure nobody measured - which is
    # the unmarked substitution this whole change exists to end.
    Scenario() \
        .given(
            an_incident_still_broken := a_measured_incident(back_to_normal_at=None)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_still_broken)
        ) \
        .then(all_of(
            _says("not back to normal by",
                  f"{{{ARGUS_STOPPED_FIGURE}}}, so it was broken for at least"),
            _says("at least"),
            _does_not_say("when the incident was closed")
        ))


@pytest.mark.unit
def test_an_incident_whose_metrics_are_still_missing_is_not_said_to_have_closed() -> None:
    # Where Argus stopped is not where the incident did. An escalated incident
    # whose blind stretch was still running was told to the model as "still
    # unobserved when the incident closed", and the write-up said the incident
    # had closed - over a period nobody could see that had not ended.
    Scenario() \
        .given(
            an_incident_nobody_could_see := a_measured_incident(
                back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_nobody_could_see)
        ) \
        .then(all_of(
            _says("the metrics had still not resumed by", f"{{{ARGUS_STOPPED_FIGURE}}}. That is"),
            _does_not_say("when the incident closed")
        ))


@pytest.mark.unit
def test_an_action_with_a_way_back_is_told_it_can_be_put_back() -> None:
    # The document's Resolution says it of every action, and the brief said
    # nothing. Left to guess, a model called a restart reversible under what went
    # well, a section away from a row calling it irreversible - and both were
    # the wrong word: those two name the autonomy tier, which a restart is on
    # the safe side of. What the record holds is whether there is anything to
    # put back.
    some_action = "restart-service on io-shop"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[an_action(some_action)])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says(f"{some_action} (can be put back)"),
            _does_not_say("irreversible")))


@pytest.mark.unit
def test_an_action_with_no_way_back_is_told_so_once_by_its_standing() -> None:
    # Its standing is "nothing to put back" whenever it has no way back, so the
    # same words in brackets beside the action said it twice on one line.
    some_action = "restart-service on io-shop"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action(some_action, standing="nothing to put back",
                          has_a_way_back=False)])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says(f"{some_action} - "),
            _does_not_say("(nothing to put back)"),
            _does_not_say("irreversible")))


@pytest.mark.unit
@pytest.mark.parametrize(("progress", "came_to"),
                         [(ActionProgress.PERFORMED, "not judged"),
                          (ActionProgress.NOT_PERFORMED, "not taken")],
                         ids=["stopped-while-watched", "stopped-before-the-write"])
def test_an_action_a_person_s_ending_stopped_is_told_in_the_page_s_words(
        progress: ActionProgress, came_to: str) -> None:
    # The Resolution says "not judged", or "not taken" where nothing was done;
    # the brief said the raw "stopped", and the write-up was written from
    # different words than the page it sits on.
    some_action = "dont care"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action(some_action, verdict=Verdict.STOPPED,
                          standing="dont care standing").model_copy(
                    update={"progress": progress})])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says(f"- {came_to}, dont care standing"),
            _does_not_say("- stopped,")))


@pytest.mark.unit
def test_an_action_never_performed_is_listed_apart_from_the_actions_taken() -> None:
    # "Actions it took:" heading a line that says "Did not" is the brief saying
    # both. Listed under its own heading, under the label the page gives it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("Did not roll back the deployment of io-shop",
                          verdict=Verdict.PLATFORM_UNREACHABLE,
                          standing="nothing was changed",
                          has_a_way_back=False).model_copy(
                    update={"progress": ActionProgress.NOT_PERFORMED}),
                an_action("Reverted the feature flag some-flag", verdict=Verdict.CONFIRMED)])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says("Actions it took:\n  - [M2] Reverted the feature flag some-flag"),
            _says("Actions it reached for and did not take:\n  - [M1] Did not roll back the "
                  "deployment of io-shop - platform-unreachable, nothing was changed")))


@pytest.mark.unit
def test_an_action_says_the_candidate_it_was_for() -> None:
    # Under the label the candidate's row goes by. Nothing else in the brief
    # says it: the move to mitigating names no candidate, and a write-up left
    # to guess credited a rollback refused for the third candidate to the
    # leading one - and said the third was never acted on.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("Did not roll back the deployment of io-shop",
                          verdict=Verdict.ESCALATED,
                          standing="nothing was changed",
                          has_a_way_back=False).model_copy(
                    update={"progress": ActionProgress.NOT_PERFORMED, "candidate": 3})])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("  - [M1] Did not roll back the deployment of io-shop for [C3] - escalated, "
                  "nothing was changed"))


@pytest.mark.unit
@pytest.mark.parametrize("progress", [ActionProgress.CLAIMED, ActionProgress.UNKNOWN],
                         ids=["claimed", "unknown"])
def test_an_action_nobody_can_account_for_is_listed_apart_from_both(
        progress: ActionProgress) -> None:
    # A claim nobody answered under "Actions it took:" is the brief saying it
    # was done, and under "did not take" that it was not. Nobody knows either.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("Reverted the feature flag some-flag", verdict=Verdict.CONFIRMED),
                an_action("Reverting other-flag",
                          standing="not known whether it was made").model_copy(
                    update={"progress": progress})])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says("Actions it took:\n  - [M1] Reverted the feature flag some-flag"),
            _says("Actions it reached for that nobody can say were taken:\n"
                  "  - [M2] Reverting other-flag (can be put back) - no verdict recorded, "
                  "not known whether it was made"),
            _does_not_say("did not take")))


@pytest.mark.unit
@pytest.mark.parametrize("progress", [ActionProgress.CLAIMED, ActionProgress.UNKNOWN],
                         ids=["claimed", "unknown"])
def test_an_incident_whose_only_action_nobody_can_account_for_is_not_said_to_have_taken_none(
        progress: ActionProgress) -> None:
    # "Actions it took: - none" above it says nothing was done, which nobody
    # knows. The heading goes rather than say it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("Reverting other-flag").model_copy(update={"progress": progress})])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _does_not_say("Actions it took:"),
            _says("Actions it reached for that nobody can say were taken:\n"
                  "  - [M1] Reverting other-flag")))


@pytest.mark.unit
def test_an_incident_whose_every_action_was_not_performed_took_none() -> None:
    # Where every action ended before its write, "none" is true and is said.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("Did not roll back the deployment of io-shop").model_copy(
                    update={"progress": ActionProgress.NOT_PERFORMED})])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("Actions it took:\n  - none")
        )


@pytest.mark.unit
def test_an_incident_whose_every_action_was_performed_has_no_list_of_actions_not_taken() -> None:
    # A heading with nothing under it reads as a section the model must fill.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[an_action("dont care")])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _does_not_say("did not take"),
            _does_not_say("nobody can say")))


@pytest.mark.unit
def test_an_incident_back_to_normal_is_given_as_back_to_normal_rather_than_recovered() -> None:
    # Where the impact ends is where the service was back inside its usual range,
    # which is not where Mitigation saw it fall off the incident's level - and
    # "recovered" is Mitigation's word for that one.
    Scenario() \
        .given(
            an_incident_that_came_back := a_measured_incident(back_to_normal_at=RECOVERED_AT)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_that_came_back)
        ) \
        .then(all_of(
            _says("when the metrics show it back to normal"),
            _does_not_say("show it recovered")
        ))


@pytest.mark.unit
def test_an_end_a_person_reported_is_given_as_their_report_under_its_line() -> None:
    # Told the end only as back to normal, a model credits it to the metrics.
    # Told nothing of how to take a report, one called it unverified and asked
    # for reports like it to be checked.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                timeline=[a_timeline_entry("dont care"),
                          a_timeline_entry("dont care either", outside_the_walk=True)],
                resolution=a_resolution(RECOVERED_AT, line=1)),
            measured := a_measured_incident(back_to_normal_at=RECOVERED_AT,
                                            reported_by="Some Person")
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _says("when Some Person reported it resolved [XW1] - their report is the end, as "
                  "given. A report is not a hypothesis: do not test it against the rest of the "
                  "record, and do not propose checking reports like it."),
            _does_not_say("back to normal")
        ))


@pytest.mark.unit
def test_where_a_person_wrote_the_brief_says_a_message_never_stops_a_running_step() -> None:
    # Not told how a message is taken in, write-ups read the steps after a
    # person's report as Argus pressing on regardless of it.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(people_wrote=True)
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _says("\nA person's message never stops a step already running: between steps, "
                  "Argus starts no new one while a message waits to be answered.\n")
        )


@pytest.mark.unit
def test_where_nobody_wrote_the_brief_says_nothing_of_messages() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(people_wrote=False)
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(
            _does_not_say("A person's message never stops")
        )


@pytest.mark.unit
def test_a_service_back_before_the_action_credited_with_it_is_given_as_back_before_it() -> None:
    # Back a whole minute before the action said to have brought it back, the
    # service was not brought back by that action. Ending the incident at the
    # action would hide that, and saying nothing leaves the model to credit it.
    # The action as the narration words it - the opening of a sentence - said
    # with Argus as its subject.
    the_action = "Reverted the feature flag monthly-spend-feature"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action(the_action, verdict=Verdict.CONFIRMED)]),
            measured := a_measured_incident(back_before_the_action=True)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(_says("when Argus reverted the feature flag monthly-spend-feature",
                    "not because of it"))


@pytest.mark.unit
def test_a_service_back_after_the_action_credited_with_it_is_not_given_as_back_before_it() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(actions=[
                an_action("dont care", verdict=Verdict.CONFIRMED)]),
            measured := a_measured_incident(back_before_the_action=False)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(_does_not_say("not because of it"))


@pytest.mark.unit
def test_an_incident_whose_metrics_stopped_at_its_onset_is_written_up_as_a_metrics_gap() -> None:
    # The lower bound above is true and not enough. Where the rows stop at the
    # onset, the stretch it bounds is not one the service spent in trouble - it is
    # one the metrics did not cover at all - and a write-up that said only "had not
    # recovered" would describe a broken shop that was never broken, and report
    # the short window before the onset as though it were the incident.
    Scenario() \
        .given(
            an_incident_nobody_could_see := a_measured_incident(
                back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_nobody_could_see)
        ) \
        .then(_says("had still not resumed", to_iso(ONSET)))


@pytest.mark.unit
def test_an_incident_its_metrics_covered_says_nothing_of_a_metrics_gap() -> None:
    Scenario() \
        .given(
            an_incident_still_broken := a_measured_incident(back_to_normal_at=None)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), an_incident_still_broken)
        ) \
        .then(_does_not_say("unobserved"))


@pytest.mark.unit
def test_a_metrics_gap_names_the_log_lines_read_that_reach_into_it() -> None:
    # The metrics stopping is not nobody seeing. Told the stretch was one
    # "nobody could see", and the service "unobserved", a model holding the
    # shop's own warned rate through it wrote that the record could not say how
    # the shop was doing. Told only which lines reached in, one wrote that
    # nothing was known after the onset - so how far they reach is said too.
    some_line_inside = f"{to_iso(ONSET + timedelta(minutes=5))} WARN io-shop: some warning"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[some_line_inside]),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _says_on_one_line("reach into it until", f"{{{LOGS_REACH_UNTIL_FIGURE}}}",
                              f"[{grouped([some_line_inside], None, ONSET.date())[0].label}]"),
            _does_not_say("nobody could see"),
            _does_not_say("unobserved")))


@pytest.mark.unit
def test_a_message_logged_both_sides_of_where_the_metrics_stopped_is_shown_in_two() -> None:
    # What the shop logged inside the stretch, apart from what it logged before
    # it - the comparison a write-up of a blind stretch has to make, and could
    # not while the two were summed.
    some_lines = [f"{to_iso(ONSET - timedelta(minutes=5))} WARN io-shop: some warning",
                  f"{to_iso(ONSET + timedelta(minutes=5))} WARN io-shop: some warning"]

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=some_lines),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _says_on_one_line(f"[{grouped(some_lines, None, ONSET.date())[0].label}]",
                              "before the metrics stopped", "After they stopped")
        )


@pytest.mark.unit
def test_every_figure_a_brief_with_a_split_log_names_is_one_the_answer_may_name() -> None:
    # The brief and the check each read the evidence, and one that split a log
    # where the other summed it would name figures the check refuses - so an
    # answer citing what the shop logged inside the stretch would be sent back.
    some_rate = "WARN io-shop: account page error rate at {}% over the last minute"
    some_lines = [f"{to_iso(ONSET - timedelta(minutes=6))} {some_rate.format('1.00')}",
                  f"{to_iso(ONSET - timedelta(minutes=5))} {some_rate.format('2.00')}",
                  f"{to_iso(ONSET + timedelta(minutes=5))} {some_rate.format('0.50')}"]

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=some_lines),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: (opening_ask(evidence, measured), figures_shown(evidence, measured))
        ) \
        .then(
            _names_only_figures_it_may_name()
        )


@pytest.mark.unit
def test_a_metrics_gap_leaves_each_rate_shown_to_say_what_it_covers() -> None:
    # The metrics' own line already says they measured nothing after they
    # stopped. Said of every rate shown below, it was false of the shop's own
    # logged rate - which covered the stretch - and a model told it wrote that
    # nothing said how the shop was doing.
    Scenario() \
        .given(
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(an_evidence_bundle(), measured)
        ) \
        .then(
            _does_not_say("cover none of it")
        )


@pytest.mark.unit
def test_a_metrics_gap_no_log_line_reaches_into_is_said_to_have_none() -> None:
    # Said rather than left out, since a list that is absent reads the same as
    # one nobody looked for.
    some_line_before = f"{to_iso(ONSET - timedelta(minutes=10))} WARN io-shop: some warning"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[some_line_before]),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _says("No log line read reaches into it")
        )


@pytest.mark.unit
def test_a_metrics_gap_of_a_walk_that_read_no_logs_is_said_to_have_read_none() -> None:
    # Told that no line read reaches into the stretch, a model is told logs were
    # looked at and said nothing of it - which a walk that read none never did.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[]),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _says("No logs were read"),
            _does_not_say("reaches into it")))


@pytest.mark.unit
def test_a_metrics_gap_of_a_walk_whose_log_read_came_back_empty_is_said_to_have_read(
) -> None:
    # A read with no lines is a finding about the service, not a read nobody
    # made: where the metrics stopped, the service gone quiet in its logs too.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[],
                                           log_reading_ended=ONSET + timedelta(minutes=20)),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(all_of(
            _says("No log line read reaches into it", "The logs were read up to"),
            _does_not_say("No logs were read")))


@pytest.mark.unit
def test_the_log_lines_reaching_into_a_metrics_gap_are_the_service_s_account_of_it(
) -> None:
    # Told which lines reach in and how far, a model still wrote that the shop's
    # health could not be seen for the whole stretch - and in the next sentence
    # quoted what those lines said of it. What they report there is what is
    # known of the service, measured by the service rather than the metrics.
    some_line_inside = f"{to_iso(ONSET + timedelta(minutes=5))} WARN io-shop: some warning"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[some_line_inside]),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _says_on_one_line("reach into it until", "the service's own account of that stretch")
        )


@pytest.mark.unit
def test_the_error_rate_line_names_the_log_rows_whose_figures_reach_into_the_stretch() -> None:
    # Told the logs reaching into the stretch were the service's own account,
    # a write-up still said no error rate existed for it - beside a row whose
    # figures inside the stretch were the shop's own logged rate. Named, and
    # not called a rate: code knows which rows carry figures there, not what
    # those figures measure. And what they show is left to the field that
    # says it: told here to say it, beside a gap paragraph telling it to say
    # it nowhere else, the brief asked both ways.
    some_lines_inside = [
        f"{to_iso(ONSET + timedelta(minutes=minute))} WARN io-shop: account page error rate "
        f"{rate}"
        for minute, rate in ((2, "0.50"), (4, "1.00"), (6, "2.00"))
    ]

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=some_lines_inside),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _says_on_one_line("Error rate: not measured by the metrics", "[G",
                              "do not say nothing was measured",
                              LOGS_SHOW_SERVING_AS_BEFORE_FIELD)
        )


@pytest.mark.unit
def test_the_service_is_said_to_be_seen_through_the_log_lines_reaching_into_a_metrics_gap(
) -> None:
    # Told the lines are the service's own account of the stretch, a write-up
    # still said the shop kept serving "while it went unobserved", citing those
    # very lines. Seen up to where they reach, and no further: where they end
    # before the reading did, the service may have stopped with its metrics.
    some_line_inside = f"{to_iso(ONSET + timedelta(minutes=5))} WARN io-shop: some warning"

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[some_line_inside]),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _says_on_one_line("reach into it until",
                              "up to then the service was seen through them")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("log_lines", "pointed_to"), [
    ([f"{to_iso(ONSET + timedelta(minutes=5))} WARN io-shop: some warning"], True),
    ([f"{to_iso(ONSET - timedelta(minutes=10))} WARN io-shop: some warning"], False)
], ids=["a-line-reaches-in", "no-line-reaches-in"])
def test_an_error_rate_the_metrics_did_not_measure_over_a_gap_points_to_the_logs_in_it(
        log_lines: list[str], pointed_to: bool) -> None:
    # "Not measured by the metrics" alone, and a model wrote that the error rate
    # over the gap could not be measured - of a gap the shop's own logged rate
    # covered. Pointed to only where a line does reach in.
    a_metrics_gap = a_measured_incident(
        error_rates=None, back_to_normal_at=None, metrics_stopped_at=ONSET
    ).model_copy(update={"error_rates_unmeasured": Unmeasured.NO_MINUTE_WHILE_BROKEN})

    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=log_lines)
        ) \
        .when(
            lambda: opening_ask(evidence, a_metrics_gap)
        ) \
        .then(
            _says_on_one_line("Error rate: not measured by the metrics",
                              "the log lines that reach into that stretch")
            if pointed_to else
            _does_not_say("the log lines that reach into that stretch")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("read_past_the_alert", "said"), [
    (timedelta(0), "when the alert was raised - nothing after that was read"),
    (timedelta(minutes=2), " - nothing after that was read")
], ids=["at-the-alert", "past-the-alert"])
def test_a_metrics_gap_says_where_the_reading_of_the_logs_ended(
        read_past_the_alert: timedelta, said: str) -> None:
    # The lines read reached 20:45, and the write-up said the shop's health was
    # not known after that point - as though the shop went quiet, where the
    # reading had ended there, at the alert.
    some_evidence = an_evidence_bundle(
        log_lines=[f"{to_iso(ONSET + timedelta(minutes=5))} WARN io-shop: some warning"])

    Scenario() \
        .given(
            evidence := some_evidence.model_copy(
                update={"log_reading_ended": some_evidence.alerted_at + read_past_the_alert}),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _says_on_one_line("The logs were read up to", f"{{{LOG_READING_ENDED_FIGURE}}}", said)
        )


@pytest.mark.unit
def test_a_metrics_gap_read_past_the_alert_is_not_said_to_end_at_it() -> None:
    some_evidence = an_evidence_bundle(
        log_lines=[f"{to_iso(ONSET + timedelta(minutes=5))} WARN io-shop: some warning"])

    Scenario() \
        .given(
            evidence := some_evidence.model_copy(
                update={"log_reading_ended": some_evidence.alerted_at + timedelta(minutes=2)}),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _does_not_say("when the alert was raised")
        )


@pytest.mark.unit
def test_a_metrics_gap_with_no_reading_recorded_says_nothing_of_where_one_ended(
) -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(
                log_lines=[f"{to_iso(ONSET + timedelta(minutes=5))} WARN io-shop: some warning"]),
            measured := a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET)
        ) \
        .when(
            lambda: opening_ask(evidence, measured)
        ) \
        .then(
            _does_not_say("were read up to")
        )


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
                onset_at=ONSET, back_to_normal_at=RECOVERED_AT)
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
    # and code works it out from the figures as shown. A row's instant among
    # them: shown only Argus's own figures worked, no recorded walk worked a
    # span out of a timeline row.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.description
        ) \
        .then(
            _the_description_mentions(f"{{{BACK_TO_NORMAL_FIGURE} - {BEGAN_FIGURE}}}",
                                      f"{{T3.1 - {ALERT_RAISED_FIGURE}}}",
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
def test_a_name_with_a_digit_in_it_is_never_said_to_be_cited() -> None:
    # "A label you cite (T2, G3fa2, C1, AI-1)" called a candidate citable, beside
    # a brief telling the model to cite none - and the check refuses a step that
    # cites one. The sentence is there to say a name is written as given, which
    # needs no word about citing.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.description
        ) \
        .then(
            all_of(
                _the_description_mentions("a label (T2, G3fa2, C1, AI-1)"),
                _the_description_avoids("you cite")
            )
        )


@pytest.mark.unit
def test_every_sentence_the_answer_would_publish_is_read() -> None:
    # The check reads only what this yields. A field left out is prose whose
    # figures nothing refuses and whose names nothing writes in.
    some_answer = SubmittedPostmortem(
        root_cause="the root cause",
        cause_in_plain_words="the cause in plain words",
        still_at_risk="what is still at risk",
        symptom="the symptom",
        assumptions=["an assumption"],
        lead_effects={"L1": "a lead's effect"},
        causal_chain=[SubmittedStep(step="a step", cites=["T1"],
                                    ruled_out=[SubmittedRuledOut(what="what it ruled out",
                                                                 cites=["T2"])])],
        contributing_factors=[SubmittedFactor(factor="a factor",
                                              had_it_been_otherwise="had it been otherwise",
                                              addressed_by=["AI-1"])],
        action_items=[SubmittedItem(item="an item", type=ActionItemType.PREVENT)],
        lessons=Lessons(went_well=["went well"], went_wrong=["went wrong"],
                        got_lucky=["got lucky"]))

    Scenario() \
        .when(
            lambda: list(some_answer.sentences())
        ) \
        .then(
            the_answer_was(["the root cause", "the cause in plain words",
                            "what is still at risk", "the symptom", "an assumption",
                            "a lead's effect", "a step", "what it ruled out", "a factor",
                            "had it been otherwise", "an item", "went well", "went wrong",
                            "got lucky"])
        )


@pytest.mark.unit
def test_every_sentence_the_answer_would_publish_is_read_with_a_place_of_its_own() -> None:
    # A fault keyed by its check alone is one the model is never told of again
    # once it moves into another item: told of it in one item, a rewrite saying
    # it in another would count as already told. So every sentence comes with a
    # place of its own, which is what a fault found in it is keyed by.
    some_answer = SubmittedPostmortem(
        root_cause="the root cause",
        cause_in_plain_words="the cause in plain words",
        still_at_risk="what is still at risk",
        symptom="the symptom",
        assumptions=["an assumption"],
        lead_effects={"L1": "a lead's effect"},
        causal_chain=[SubmittedStep(step="a step", cites=["T1"],
                                    ruled_out=[SubmittedRuledOut(what="what it ruled out",
                                                                 cites=["T2"])])],
        contributing_factors=[SubmittedFactor(factor="a factor",
                                              had_it_been_otherwise="had it been otherwise",
                                              addressed_by=["AI-1"])],
        action_items=[SubmittedItem(item="an item", type=ActionItemType.PREVENT)],
        lessons=Lessons(went_well=["went well"], went_wrong=["went wrong"],
                        got_lucky=["got lucky"]))

    Scenario() \
        .when(
            lambda: list(some_answer.placed_sentences())
        ) \
        .then(all_of(
            _read_in_the_order_sentences_reads(some_answer),
            _each_in_a_place_of_its_own()
        ))


@pytest.mark.unit
def test_what_a_step_ruled_out_is_rewritten_as_every_other_sentence_is() -> None:
    # Read by the same fields `sentences` reads: a figure named in what was
    # ruled out is written in like one named anywhere else.
    some_answer = SubmittedPostmortem(
        causal_chain=[SubmittedStep(step="a step", cites=["T1"],
                                    ruled_out=[SubmittedRuledOut(what="what it ruled out",
                                                                 cites=["T2"])])])

    Scenario() \
        .when(
            lambda: some_answer.with_each_sentence(str.upper).causal_chain
        ) \
        .then(
            the_answer_was([SubmittedStep(step="A STEP", cites=["T1"],
                                          ruled_out=[SubmittedRuledOut(
                                              what="WHAT IT RULED OUT", cites=["T2"])])])
        )


@pytest.mark.unit
def test_what_a_factor_would_have_changed_is_rewritten_as_every_other_sentence_is() -> None:
    # Read by the same fields `sentences` reads: a figure named in what a
    # factor would have changed is written in like one named anywhere else.
    some_answer = SubmittedPostmortem(
        contributing_factors=[SubmittedFactor(label="CF-1", factor="a factor",
                                              had_it_been_otherwise="had it been otherwise",
                                              addressed_by=["AI-1"])])

    Scenario() \
        .when(
            lambda: some_answer.with_each_sentence(str.upper).contributing_factors
        ) \
        .then(
            the_answer_was([SubmittedFactor(label="CF-1", factor="A FACTOR",
                                            had_it_been_otherwise="HAD IT BEEN OTHERWISE",
                                            addressed_by=["AI-1"])])
        )


@pytest.mark.unit
def test_the_factors_an_item_answers_survive_the_rewrite() -> None:
    # Labels, not prose: rewriting the item's words leaves what it answers.
    some_answer = SubmittedPostmortem(
        action_items=[SubmittedItem(item="an item", type=ActionItemType.PREVENT,
                                    answers=["CF-1"])])

    Scenario() \
        .when(
            lambda: some_answer.with_each_sentence(str.upper).action_items
        ) \
        .then(
            the_answer_was([SubmittedItem(item="AN ITEM", type=ActionItemType.PREVENT,
                                          answers=["CF-1"])])
        )


@pytest.mark.unit
def test_each_factor_is_asked_what_it_would_have_changed_with_the_root_cause_still_true(
) -> None:
    # Told in the list's description that a factor is not the root cause again
    # in other words, five write-ups' first factor said their root cause again.
    # Asked of each factor, what it would have changed with the root cause
    # still true is a question a restatement cannot answer without saying so.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CONTRIBUTING_FACTORS_FIELD]
        ) \
        .then(all_of(
            _requires_of_each_item(HAD_IT_BEEN_OTHERWISE_FIELD),
            lambda factors: _the_description_mentions(
                f"with what {ROOT_CAUSE_FIELD} says still true")(
                factors["items"]["properties"][HAD_IT_BEEN_OTHERWISE_FIELD]["description"])
        ))


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
def test_each_why_is_asked_to_answer_the_step_directly_before_it() -> None:
    # One write-up's first why was its symptom in more detail. Another's
    # incident needed two things at once - a dependency slowing and nothing
    # limiting the wait - and its third why answered the first, braiding both
    # into one line. Told which to follow - the one that reaches what set the
    # incident off, where the chain has to arrive - the other is named where
    # they meet.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSAL_CHAIN_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("not the symptom again", "directly before",
                                      "what set it off")
        )


@pytest.mark.unit
def test_the_cause_is_asked_to_say_what_else_the_record_ruled_out() -> None:
    # A write-up once said, unasked, that the earlier deploy came hours before
    # the onset and no flag had changed, so neither explained it. Asked for
    # nothing of the kind, the next three spent their steps on the mechanism
    # and dropped it - and what was ruled out is half of why the cause is the
    # cause.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSAL_CHAIN_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("ruled out")
        )


@pytest.mark.unit
def test_an_earlier_change_is_asked_to_be_ruled_out_by_the_service_healthy_with_it() -> None:
    # A write-up ruled the earlier deploy out because it "went out well before
    # the onset" - but a change can take hours to show. What rules it out is
    # the service measured healthy with it in place: in metrics read before the
    # onset, or after a confirmed action that left it there. Where the record
    # shows neither, it stands.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSAL_CHAIN_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("never by how long before",
                                      "a confirmed action that left it", "not ruled out")
        )


@pytest.mark.unit
def test_an_earlier_change_is_ruled_out_by_an_alert_dating_the_harm_at_or_after_a_later_one(
) -> None:
    # The alert dated the oldest wrong total to after the later deploy, so the
    # totals reconciled the whole time the earlier one ran alone - yet told
    # only metrics or a confirmed action rule a change out, the write-up said
    # the earlier deploy was not ruled out because no metrics were read. Told
    # "after", write-ups of an absence alert dating its first missing sample to
    # the later deploy's own instant called that instant after it: at is said
    # as at, and rules the earlier change out as surely.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSAL_CHAIN_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("an alert that dates the first harm itself at or after "
                                      "a later change", "where the two instants are the same",
                                      "none of these")
        )


@pytest.mark.unit
@pytest.mark.parametrize("field", [CONTRIBUTING_FACTORS_FIELD, LESSONS_FIELD])
def test_a_safeguard_the_record_does_not_show_is_asked_for_as_not_seen(field: str) -> None:
    # Told once, in the tool's own description, to state only what the evidence
    # shows, a write-up still gave "nothing checked output quality before it
    # reached production" as a factor and as what went wrong - in the field
    # whose description asked for "a missing safeguard". Said where the claim
    # is written, and never asked for as missing.
    what_an_unseen_check_is_written_as = "no check was seen"

    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[field]["description"]
        ) \
        .then(all_of(
            _the_description_mentions(what_an_unseen_check_is_written_as),
            _the_description_avoids("missing safeguard")
        ))


@pytest.mark.unit
def test_how_quickly_argus_acted_is_asked_for_as_a_working_of_two_rows() -> None:
    # Told how to work a span out only in the tool's description, 20 recorded
    # walks praised Argus for acting "within seconds" - one of them for 41
    # seconds. Said in the list the praise is written in.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [WENT_WELL_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("how quickly", f"{{T3.1 - {ALERT_RAISED_FIGURE}}}")
        )


@pytest.mark.unit
def test_a_span_is_asked_to_be_set_beside_what_it_times() -> None:
    # A write-up worked out how long the refusal took and set it after the
    # handover, six seconds later, in the same sentence: "and handed it to a
    # person instead (less than a second after entering MITIGATING)".
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [WENT_WELL_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("beside what it times",
                                      "not after something else in the same sentence")
        )


@pytest.mark.unit
def test_a_span_set_after_something_else_is_shown_beside_the_form_to_write() -> None:
    # Told the rule, a write-up still set the confirmation's span after "brought
    # the service back", so it read as a three-minute recovery from a service
    # back in one. Its own sentence is the form shown not to write.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [WENT_WELL_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions(
                f"Argus confirmed, {{T20.1 - {ALERT_RAISED_FIGURE}}} after the alert was "
                f"raised, that the rollback had brought the service back",
                f"not \"Argus confirmed the rollback had brought the service back from the "
                f"incident's level {{T20.1 - {ALERT_RAISED_FIGURE}}} after the alert was raised\"")
        )


@pytest.mark.unit
def test_a_reason_is_asked_to_be_set_beside_the_action_it_belongs_to() -> None:
    # A write-up praised Argus as having "declined to roll back a change that
    # was made on purpose to test the leading candidate, rather than undoing a
    # deliberate platform-wide rename": the purpose of the rollback set beside
    # the rename, so the rename read as made to test the candidate, and the
    # refusal's reason said a second time.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [WENT_WELL_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("beside the action it belongs to", "say it once")
        )


@pytest.mark.unit
def test_what_went_well_names_what_code_fix_proposed_without_saying_what_it_does() -> None:
    # Squeezed into a line about how quickly a fix was proposed, a repair
    # script that reports by default and writes with --apply became "a
    # report-only repair script" - in write-ups whose own action items said to
    # run it with --apply. The items and Code-Fix's reading say what it does.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [WENT_WELL_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("Name what Code-Fix proposed without saying what it "
                                      "does: the action items and Code-Fix's own reading "
                                      "say that, with its conditions.")
        )


@pytest.mark.unit
def test_the_brief_says_the_document_says_how_the_service_did_where_a_log_line_reaches_in(
) -> None:
    # Given the bound as a figure, steps carried it and root causes and lessons
    # still said the shop "kept serving" without it, two to four of five. Told
    # the document says it itself, from an answer of the model's, none did.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[
                f"{to_iso(ONSET + timedelta(minutes=4))} WARN io-shop: dont care"])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident(back_to_normal_at=None,
                                                              metrics_stopped_at=ONSET))
        ) \
        .then(
            _says_on_one_line("How the service did over that stretch is said by the document "
                              "itself, from your answer to logs_show_serving_as_before: say "
                              "nothing of it anywhere else.")
        )


@pytest.mark.unit
def test_the_brief_says_to_cite_the_log_lines_reaching_in_for_nobody_seeing_anything_wrong(
) -> None:
    # Told to say nothing of how the service did anywhere but the answer, a
    # chain's first step still said what the lines show, four of five: what
    # shows nobody using it saw anything wrong is those lines, and every step
    # cites its evidence. Told to cite them for it without saying what they
    # show, none did.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[
                f"{to_iso(ONSET + timedelta(minutes=4))} WARN io-shop: dont care"])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident(back_to_normal_at=None,
                                                              metrics_stopped_at=ONSET))
        ) \
        .then(
            _says_on_one_line("say nothing of it anywhere else.",
                              "Where the chain's first step says nobody using the service saw "
                              "anything wrong, cite those log lines for it without saying what "
                              "they show.")
        )


@pytest.mark.unit
def test_the_brief_never_names_an_answer_an_incident_whose_logs_reach_nowhere_is_not_asked(
) -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[
                f"{to_iso(ONSET - timedelta(minutes=4))} WARN io-shop: dont care"])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident(back_to_normal_at=None,
                                                              metrics_stopped_at=ONSET))
        ) \
        .then(
            _does_not_say("logs_show_serving_as_before")
        )


@pytest.mark.unit
@pytest.mark.parametrize("log_lines", [
    [f"{to_iso(ONSET - timedelta(minutes=4))} WARN io-shop: dont care"],
    []
], ids=["none-reaching-in", "none-read"])
def test_the_brief_says_nothing_is_known_of_the_service_where_no_log_line_reaches_in(
        log_lines: list[str]) -> None:
    # The document says how the service did there only from lines that reach
    # in. With none, a model told nothing of that stretch is free to say the
    # shop kept serving - unbounded, which is what the bound was there to stop.
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=log_lines, log_reading_ended=None)
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident(back_to_normal_at=None,
                                                              metrics_stopped_at=ONSET))
        ) \
        .then(
            _says_on_one_line("Nothing is known of how the service did over that stretch: "
                              "say nothing of it.")
        )


@pytest.mark.unit
def test_the_brief_never_says_nothing_is_known_where_a_log_line_reaches_in() -> None:
    Scenario() \
        .given(
            evidence := an_evidence_bundle(log_lines=[
                f"{to_iso(ONSET + timedelta(minutes=4))} WARN io-shop: dont care"])
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident(back_to_normal_at=None,
                                                              metrics_stopped_at=ONSET))
        ) \
        .then(
            _does_not_say("Nothing is known of how the service did")
        )


@pytest.mark.unit
def test_what_the_response_did_is_asked_for_under_what_went_wrong_rather_than_as_a_factor() -> None:
    # Asked for conditions that had to hold, a write-up listed automatic sync
    # left off by the rollback and "Argus could not act" as factors - things the
    # response did, after the incident began. Told where they go instead, a
    # failure to act is still said rather than dropped or bent into a condition.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CONTRIBUTING_FACTORS_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("before the incident began", "left behind",
                                      WENT_WRONG_FIELD)
        )


@pytest.mark.unit
def test_a_factor_is_asked_to_credit_an_alert_with_what_its_rule_watches_alone() -> None:
    # A write-up's factor said a scrape's empty target list "was found only
    # when the absence alert fired": the alert found the readings missing, and
    # nothing read the target list.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CONTRIBUTING_FACTORS_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("An alert finds what its rule watches, not the "
                                      "cause behind it")
        )


@pytest.mark.unit
def test_a_factor_is_asked_for_as_what_would_have_helped_with_the_root_cause_still_true() -> None:
    # Told only that a factor "did not cause it alone", a write-up gave the
    # root cause - no limit on the wait for an optional dependency - again as
    # its first factor. Tested against the root cause as written, rather than
    # against "the cause" - which the brief also uses of the trigger - a
    # restatement contradicts itself.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CONTRIBUTING_FACTORS_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("root cause again", ROOT_CAUSE_FIELD)
        )


@pytest.mark.unit
def test_a_change_the_response_left_on_purpose_is_asked_for_as_not_having_gone_wrong() -> None:
    # Automatic sync left off so the rollback holds is said by the resolution
    # and undone by an item the record already holds. Listed under what went
    # wrong as well, one fact was spelled four times - and called a failure
    # when it went as designed.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [WENT_WRONG_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("on purpose", "did not go wrong")
        )


@pytest.mark.unit
def test_the_lessons_are_told_how_soon_the_alert_came_is_already_weighed() -> None:
    # Asked to weigh it, three write-ups of one incident in a row weighed
    # nothing, and one counted a wait its rule did not have. Every part of it is
    # measured, so code writes that lesson (`detection_lesson`) and the model is
    # told so - in the description over all three lists, since none of them is
    # the place for it again.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("How soon the alert came is weighed by the document "
                                      "already")
        )


@pytest.mark.unit
def test_luck_is_asked_for_as_what_the_record_shows_went_the_fortunate_way() -> None:
    # Told only "a risk that went unnoticed this time", and that any list may
    # be empty, two write-ups filled the list anyway: with what kind of fault
    # it was, which the impact says, and with a limit of the evidence, which
    # is an assumption. Said in the list itself, with where each goes instead.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [GOT_LUCKY_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("by chance", "Empty where", "what kind of fault",
                                      ASSUMPTIONS_FIELD)
        )


@pytest.mark.unit
def test_luck_is_asked_not_to_say_how_the_service_did_where_its_metrics_did_not_reach() -> None:
    # Told to say how the service did over the stretch nobody watched only
    # where the document says it, a write-up's luck said it anyway: "Had it
    # actually broken during that time, nothing would have shown it".
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [GOT_LUCKY_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("Not how the service did over a stretch its metrics did "
                                      "not cover, nor what a failure there would have done")
        )


@pytest.mark.unit
def test_a_draft_fix_left_for_a_person_is_asked_for_as_having_gone_as_designed() -> None:
    # A write-up listed under what went wrong that the proposed fix was "only a
    # draft and nothing ran its test or change". A person reviewing and
    # merging it is the design, and the record's own item says so.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [WENT_WRONG_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("a draft fix to review and merge", "went as designed")
        )


@pytest.mark.unit
def test_a_limit_of_the_record_is_asked_for_as_an_assumption_rather_than_as_gone_wrong() -> None:
    # A write-up's first item under what went wrong was that a stretch was
    # unmeasured - a limit of the evidence, not something the response did.
    # Told so of luck already; not of this list, where it landed instead.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [WENT_WRONG_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("a limit of what the record shows", ASSUMPTIONS_FIELD)
        )


@pytest.mark.unit
def test_what_went_wrong_names_the_limits_of_the_record_it_is_not_for() -> None:
    # Told a limit of what the record shows belongs among the assumptions, a
    # write-up still listed under what went wrong that logs were not read and
    # that the metrics stopped short of the onset - limits it did not take for
    # limits until they were named.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [WENT_WRONG_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("logs nobody read", "metrics that stop short of the onset",
                                      "the document says what was read")
        )


@pytest.mark.unit
def test_what_went_wrong_is_asked_not_to_say_the_root_cause_or_a_factor_again() -> None:
    # A write-up's first item under what went wrong was the rename shipping
    # without the scrape config - the root cause, and its first factor, a third
    # time.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [WENT_WRONG_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("root cause or a contributing factor again")
        )


@pytest.mark.unit
@pytest.mark.parametrize("field", [SYMPTOM_FIELD, CAUSAL_CHAIN_FIELD])
def test_a_symptom_nobody_using_the_service_saw_is_asked_for_as_that(field: str) -> None:
    # Asked what someone using the service saw, and forbidden the metric the
    # alert fired on, a write-up of an incident nobody using the shop saw
    # anything of wrote the metric anyway - "Shop metrics stopped arriving" -
    # in the title, and as the chain's first step.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[field]["description"]
        ) \
        .then(
            _the_description_mentions("nobody using the service saw anything")
        )


@pytest.mark.unit
def test_a_safeguard_that_did_not_stop_it_is_asked_for_as_a_factor_rather_than_a_step() -> None:
    # Told to name it "at the step where they meet", a write-up gave it a why
    # of its own - "Why nothing stopped it" - beside the factor that already
    # said it.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSAL_CHAIN_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("never a step of its own", CONTRIBUTING_FACTORS_FIELD)
        )


@pytest.mark.unit
def test_what_was_ruled_out_is_asked_for_in_its_step_s_own_list_rather_than_as_one() -> None:
    # Told twice in words to say it "at the step that ties the incident to the
    # change", write-ups listed what they ruled out as a why of its own, which
    # the page labelled "why 4". A list on every step, which the model fills on
    # the one it chooses, leaves the chain no reason to.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSAL_CHAIN_FIELD]
        ) \
        .then(all_of(
            _requires_of_each_item(RULED_OUT_FIELD),
            lambda chain: _the_description_mentions(RULED_OUT_FIELD, "never as a step")(
                chain["description"])
        ))


@pytest.mark.unit
def test_a_change_is_asked_to_be_dated_by_its_own_row_rather_than_by_its_effect() -> None:
    # A write-up dated the rollout by the instant the metrics stopped, so "the
    # same minute the metrics stop" proved the cause by its own effect.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSAL_CHAIN_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("never by an effect it had")
        )


@pytest.mark.unit
def test_a_symptom_nobody_saw_is_given_no_example_of_an_unwatched_service() -> None:
    # Shown "Nothing users saw; the service could not be watched", every
    # write-up reads one incident's answer - and that one was false of it: the
    # shop's logs and takings saw the stretch, and only its metrics stopped.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[SYMPTOM_FIELD]["description"]
        ) \
        .then(
            _the_description_avoids("could not be watched")
        )


@pytest.mark.unit
def test_a_state_a_row_read_is_asked_for_as_of_that_read() -> None:
    # A write-up said all the replicas were on the deployed revision from the
    # minute it was deployed, on a read made minutes later that said only that
    # they ran it then.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSAL_CHAIN_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("as of the row that read it", "its first figure")
        )


@pytest.mark.unit
def test_the_branch_that_did_not_set_it_off_is_asked_for_as_a_factor_not_a_step() -> None:
    # Told to name the other branch "at the step where they meet", a write-up
    # named the missing check in its last step - which the root cause is - and
    # then the root cause carried the factor that said it again.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSAL_CHAIN_FIELD]["description"]
        ) \
        .then(all_of(
            _the_description_mentions(f"the other is one of the {CONTRIBUTING_FACTORS_FIELD}"),
            _the_description_avoids("where they meet")
        ))


@pytest.mark.unit
@pytest.mark.parametrize("field", [CAUSAL_CHAIN_FIELD, ROOT_CAUSE_FIELD])
def test_the_chain_and_the_root_cause_are_not_asked_how_to_word_a_safeguard(field: str) -> None:
    # Neither names one: the other branch is a contributing factor. Told how to
    # word a safeguard there anyway, a field that should carry none is asked
    # for one.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[field]["description"]
        ) \
        .then(
            _the_description_avoids("no check was seen")
        )


@pytest.mark.unit
def test_the_root_cause_is_asked_to_carry_no_contributing_factor() -> None:
    # A write-up's root cause ended on the missing check, and its first factor
    # said the same check again. Told any check or safeguard is a factor, an
    # incident whose fault is itself a missing protection - a wait with no
    # limit - would have its mechanism moved out of its root cause. The
    # boundary is the factors' own test: what would have stopped it with the
    # mechanism unchanged.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[ROOT_CAUSE_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions(f"Not one of the {CONTRIBUTING_FACTORS_FIELD}",
                                      "a missing protection or not",
                                      "would have stopped it with this mechanism unchanged")
        )


@pytest.mark.unit
def test_the_root_cause_is_asked_to_leave_out_what_the_document_states_itself() -> None:
    # Told only that the document states the trigger, write-ups' root causes
    # said again what confirmed it, what resolved the incident, and what was
    # ruled out - each a section of the document already.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[ROOT_CAUSE_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("Not the trigger, how it was confirmed, what resolved "
                                      "it or what was ruled out")
        )


@pytest.mark.unit
def test_the_root_cause_is_told_what_the_service_did_over_the_gap_is_not_the_mechanism() -> None:
    # Four of five root causes said the shop "kept serving" unbounded, with the
    # bound a figure away; told the stretch is the first step's to say, two;
    # told the document says it itself, from an answer of its own, none.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[ROOT_CAUSE_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions(
                "What the service did over the stretch the metrics did not watch is not the "
                "mechanism: the document says it itself.")
        )


@pytest.mark.unit
def test_an_action_item_is_asked_for_as_one_thing_to_do() -> None:
    # One item asked for the draft's test to be updated to the deployed key and
    # for the scrape change to land on the branch the revision was deployed
    # from: two things to do, for whoever takes either, under one number. Said
    # once, where "one thing a person could take on" already asked for it.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[ACTION_ITEMS_FIELD]["description"]
        ) \
        .then(all_of(
            _the_description_mentions("one thing a person could take on: two things to do "
                                      "are two items"),
            _the_description_avoids("Each item is one thing to do")
        ))


@pytest.mark.unit
def test_each_factor_is_asked_for_under_a_label_of_its_own() -> None:
    # What an item that answers it names it by. Never in the prose: the reader
    # never sees a factor's label, and one written there leads nowhere.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CONTRIBUTING_FACTORS_FIELD][
                "items"]["properties"][LABEL_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("CF-1 for the first factor, CF-2 for the next, and so on",
                                      "never in your prose")
        )


@pytest.mark.unit
def test_a_factor_is_asked_to_name_only_the_record_s_own_items() -> None:
    # The record's items are numbered before the model is asked, and the brief
    # gives each its number; the model's own are not. Asked to cite those too,
    # by numbers it had to work out, a write-up cited each one off. Empty is
    # said to be an answer, or the number comes back out of habit.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CONTRIBUTING_FACTORS_FIELD][
                "items"]["properties"][ADDRESSED_BY_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("The record's own action items that answer it",
                                      "Empty where none of them does",
                                      "Never an item you propose")
        )


@pytest.mark.unit
def test_a_proposed_item_is_asked_for_the_factors_it_answers() -> None:
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[ACTION_ITEMS_FIELD][
                "items"]["properties"][ANSWERS_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("The labels of the contributing factors it answers")
        )


@pytest.mark.unit
def test_a_factor_s_label_and_an_item_s_answers_are_both_required() -> None:
    Scenario() \
        .when(
            lambda: [field in SUBMIT_POSTMORTEM.properties[listed]["items"]["required"]
                     for listed, field in [(CONTRIBUTING_FACTORS_FIELD, LABEL_FIELD),
                                           (ACTION_ITEMS_FIELD, ANSWERS_FIELD)]]
        ) \
        .then(
            the_answer_was([True, True])
        )


@pytest.mark.unit
def test_a_factor_is_asked_to_be_answered_by_an_item_of_the_record_s_or_one_proposed() -> None:
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CONTRIBUTING_FACTORS_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("named in its addressed_by",
                                      "or one you propose, whose answers name it")
        )


@pytest.mark.unit
def test_the_brief_says_which_way_each_link_runs() -> None:
    # Told the model's own items are "numbered after these", a write-up cited
    # them by numbers it worked out, each one off.
    Scenario() \
        .given(
            evidence := an_evidence_bundle()
        ) \
        .when(
            lambda: opening_ask(evidence, a_measured_incident())
        ) \
        .then(all_of(
            _says("In a contributing factor's addressed_by, name the record's own action "
                  "items that answer it, by their number",
                  "an item you propose names the factors it answers in its answers, by their "
                  "labels"),
            _does_not_say("numbered after these")
        ))


@pytest.mark.unit
def test_the_label_given_as_an_example_is_one_the_record_numbers() -> None:
    # The example was AI-3 - with two items on the record, the model's own
    # first proposal, which it is now told never to name by number.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.description
        ) \
        .then(all_of(
            _the_description_mentions("(T2, G3fa2, C1, AI-1)"),
            _the_description_avoids("AI-3")
        ))


@pytest.mark.unit
def test_what_an_f_row_says_to_check_is_answered_from_a_diff_that_shows_it() -> None:
    # An F row said to check which key the deployed revision used before
    # merging; the deployed diff showed it, and a write-up passed the check on
    # as an item rather than saying what followed from the answer. Called an F
    # row as the tool calls it everywhere else.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[ACTION_ITEMS_FIELD]["description"]
        ) \
        .then(all_of(
            _the_description_mentions("an F row says to check", "what the D row shows"),
            _the_description_avoids("finding")
        ))


@pytest.mark.unit
def test_the_cause_in_plain_words_is_asked_for_in_one_sentence_of_what_the_record_says() -> None:
    # The one sentence of the summary code cannot write. Asked for the whole
    # summary, write-ups left out how long, told the reader what the brief told
    # them, and called a deploy "routine", which nothing in the record said -
    # so it is told what the document says itself, and to say none of it. And
    # asked for what caused the incident, not why it broke: where only the
    # metrics stopped, the service is not known to have broken at all.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSE_IN_PLAIN_WORDS_FIELD]["description"]
        ) \
        .then(all_of(
            _the_description_mentions("What caused the incident", "one sentence",
                                      "does not work on the service",
                                      "the document says itself", "only what the record says"),
            _the_description_avoids("broke")
        ))


@pytest.mark.unit
def test_the_cause_in_plain_words_says_what_rests_on_an_unrun_reading_as_likely() -> None:
    # Told only to say what the record says, a write-up that knew who was hit
    # from a reading of the code alone carried the reading into the sentence:
    # "a reading of the code that nothing has tested says this happens for...".
    # The summary's reader needs who, said as likely, not where it came from.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSE_IN_PLAIN_WORDS_FIELD]["description"]
        ) \
        .then(_the_description_mentions("a reading nothing ran", "as likely",
                                        "without mentioning the reading"))


@pytest.mark.unit
def test_what_is_still_at_risk_is_asked_for_in_one_sentence_or_none() -> None:
    # Nothing at risk is an answer; and what Argus left to a person - a draft
    # fix, automatic sync left off, a recommended action - the summary says
    # itself, and said here as well it is said twice. So is whether the
    # service or its metrics were back, and why: asked for "the fault still in
    # place", a write-up said again what the summary had just said. As of the
    # end of the time Argus held it, not now: nobody read the service again, and a fault "still in
    # place now" says the draft that would remove it was not merged.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[STILL_AT_RISK_FIELD]["description"]
        ) \
        .then(all_of(
            _the_description_mentions("one sentence", "Empty where", "left to a person",
                                      "automatic sync left off", "could yet do",
                                      "Not whether the service or its metrics were back",
                                      "at the end of the time Argus held the incident",
                                      "only what the record says"),
            _the_description_avoids(" now")
        ))


@pytest.mark.unit
def test_what_went_wrong_no_longer_asks_for_detection_to_be_weighed() -> None:
    # The lesson code writes says it; asked here as well, a write-up would say
    # it a second time, in words that need not agree.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[LESSONS_FIELD]["properties"]
                                                [WENT_WRONG_FIELD]["description"]
        ) \
        .then(
            _the_description_avoids("detection")
        )


@pytest.mark.unit
def test_the_symptom_is_asked_for_in_one_sentence() -> None:
    # The symptom is the document's title. A write-up of an incident nobody
    # using the service saw gave two sentences - that, then what was seen
    # instead - as the clause asking for both read.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[SYMPTOM_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("one sentence")
        )


@pytest.mark.unit
def test_the_symptom_is_asked_for_as_short_as_it_can_be_and_told_its_limit() -> None:
    # Asked for "a few words", a title ran to twenty, half of it how the fault
    # was found. Told the limit the check holds it to, it is never sent back
    # for one it was not shown.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[SYMPTOM_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("as short as it can be",
                                      f"never over {SYMPTOM_WORDS_AT_MOST} words",
                                      "not how it was found")
        )


@pytest.mark.unit
def test_the_symptom_is_asked_to_end_on_what_went_wrong() -> None:
    # The title adds " while <the change>" after the symptom, and it binds to
    # whatever the symptom ends on: "..., while requests kept succeeding while
    # categoriser.model was v2" read as though they succeeded only while it was.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[SYMPTOM_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("after your sentence and a 'while', so end on what went "
                                      "wrong, with no clause after it")
        )


@pytest.mark.unit
def test_an_action_item_is_asked_not_to_check_what_the_evidence_already_shows() -> None:
    # A write-up asked somebody to check which key layout the deployed revision
    # used - which the deployed diff it was shown already said.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[ACTION_ITEMS_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("already shows", "a diff")
        )


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
def test_an_incident_whose_investigation_named_no_cause_is_not_asked_what_the_cause_was(
) -> None:
    # The document says the cause was not determined itself. Asked for it
    # anyway, a write-up filled the root cause with what was checked - a flag
    # provider's hour said as though it covered more.
    the_cause_fields = (ROOT_CAUSE_FIELD, CAUSE_IN_PLAIN_WORDS_FIELD, REACHES_A_CAUSE_FIELD,
                        CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD)

    Scenario() \
        .when(
            lambda: submit_postmortem_for([], cause_asked=False)
        ) \
        .then(
            all_of(
                _asks_only_for(*(field for field in EVERY_FIELD_ASKED
                                 if field not in the_cause_fields)),
                _requires(*(field for field in REQUIRED_FIELDS
                            if field not in the_cause_fields))
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
def test_an_incident_whose_logs_reach_where_the_metrics_stopped_is_asked_how_they_show_it(
) -> None:
    # Required where it is offered, as a lead is: the document's sentence on
    # that stretch is written from it, and an optional field is one a model
    # leaves out whenever its prose reads well without it.
    Scenario() \
        .when(
            lambda: submit_postmortem_for([], LogsInTheGap(
                read=True, labels=["G46bc"], reach_until=ONSET, read_until=None,
                read_until_the_alert=False))
        ) \
        .then(
            all_of(
                _asks_only_for(*EVERY_FIELD_ASKED, LOGS_SHOW_SERVING_AS_BEFORE_FIELD),
                _requires(*REQUIRED_FIELDS, LOGS_SHOW_SERVING_AS_BEFORE_FIELD)
            )
        )


@pytest.mark.unit
def test_an_incident_whose_logs_reach_nowhere_the_metrics_stopped_is_not_asked_how_they_show_it(
) -> None:
    # Nothing reaches in for an answer to be a reading of.
    Scenario() \
        .when(
            lambda: submit_postmortem_for([], LogsInTheGap(
                read=True, labels=[], reach_until=None, read_until=None,
                read_until_the_alert=False))
        ) \
        .then(
            all_of(
                _asks_only_for(*EVERY_FIELD_ASKED),
                _requires(*REQUIRED_FIELDS)
            )
        )


@pytest.mark.unit
def test_how_the_logs_show_the_service_is_asked_knowing_the_document_says_it_itself() -> None:
    Scenario() \
        .when(
            lambda: submit_postmortem_for([], LogsInTheGap(
                read=True, labels=["G46bc"], reach_until=ONSET, read_until=None,
                read_until_the_alert=False)
            ).properties[LOGS_SHOW_SERVING_AS_BEFORE_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions(
                "Whether the log lines that reach into the stretch the metrics did not watch "
                "show the service serving as it had before the metrics stopped. The document "
                "writes that sentence itself, bounded to when the logs were read.")
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
def test_what_a_step_ruled_out_is_read_with_what_it_cites() -> None:
    Scenario() \
        .given(
            a_submission_ruling_something_out := {
                CAUSAL_CHAIN_FIELD: [
                    {STEP_FIELD: "the deploy renamed the port", CITES_FIELD: ["D1"],
                     RULED_OUT_FIELD: [{WHAT_FIELD: "the earlier deploy, healthy since",
                                        CITES_FIELD: ["T5"]}]}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_ruling_something_out).causal_chain
        ) \
        .then(
            the_answer_was([SubmittedStep(
                step="the deploy renamed the port", cites=["D1"],
                ruled_out=[SubmittedRuledOut(what="the earlier deploy, healthy since",
                                             cites=["T5"])])])
        )


@pytest.mark.unit
def test_what_a_step_ruled_out_not_in_its_declared_shape_costs_only_itself() -> None:
    # As a step does: one with no words is dropped, one citing in the wrong
    # shape is kept citing nothing, and a list that is not one rules out
    # nothing - the step itself stands either way.
    Scenario() \
        .given(
            a_submission_ruling_out_badly := {
                CAUSAL_CHAIN_FIELD: [
                    {STEP_FIELD: "the deploy renamed the port", CITES_FIELD: ["D1"],
                     RULED_OUT_FIELD: [{WHAT_FIELD: "the earlier deploy", CITES_FIELD: "T5"},
                                       {CITES_FIELD: ["T5"]},
                                       "not a ruling"]},
                    {STEP_FIELD: "the scrape lost its target", CITES_FIELD: ["F1"],
                     RULED_OUT_FIELD: "not a list"}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(a_submission_ruling_out_badly).causal_chain
        ) \
        .then(
            the_answer_was([
                SubmittedStep(step="the deploy renamed the port", cites=["D1"],
                              ruled_out=[SubmittedRuledOut(what="the earlier deploy",
                                                           cites=[])]),
                SubmittedStep(step="the scrape lost its target", cites=["F1"])])
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
def test_a_contributing_factor_is_read_with_its_label_and_the_record_s_items_that_answer_it(
) -> None:
    Scenario() \
        .given(
            a_submission_with_a_factor := {
                CONTRIBUTING_FACTORS_FIELD: [
                    {LABEL_FIELD: "CF-1",
                     FACTOR_FIELD: "the canary started at 40%",
                     HAD_IT_BEEN_OTHERWISE_FIELD: "a smaller canary would have failed fewer",
                     ADDRESSED_BY_FIELD: ["AI-2"]}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_with_a_factor).contributing_factors
        ) \
        .then(
            the_answer_was([SubmittedFactor(
                label="CF-1",
                factor="the canary started at 40%",
                had_it_been_otherwise="a smaller canary would have failed fewer",
                addressed_by=["AI-2"])])
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
def test_a_proposed_item_is_read_with_the_factors_it_answers() -> None:
    # The item names the factors, by the labels they were written under, rather
    # than a factor naming the item: told to cite items it had not yet written,
    # by numbers it had to work out, a write-up cited each one number off.
    Scenario() \
        .given(
            a_submission_proposing_one := {
                ACTION_ITEMS_FIELD: [
                    {ITEM_FIELD: "add a test for an empty month",
                     ITEM_TYPE_FIELD: "prevent",
                     ANSWERS_FIELD: ["CF-1", "CF-3"]}
                ]
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_proposing_one).action_items
        ) \
        .then(
            the_answer_was([SubmittedItem(item="add a test for an empty month",
                                          type=ActionItemType.PREVENT,
                                          answers=["CF-1", "CF-3"])])
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
            a_submission_whose_cause_is_not_prose := {
                ROOT_CAUSE_FIELD: some_root_cause,
                CAUSE_IN_PLAIN_WORDS_FIELD: {"nested": "in the wrong shape"}
            }
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission_whose_cause_is_not_prose)
        ) \
        .then(
            all_of(
                _answered(ROOT_CAUSE_FIELD, some_root_cause),
                _left_unanswered(CAUSE_IN_PLAIN_WORDS_FIELD)
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
                _left_unanswered(CAUSE_IN_PLAIN_WORDS_FIELD),
                _left_unanswered(STILL_AT_RISK_FIELD),
                _left_unanswered(CAUSAL_CHAIN_FIELD),
                _left_unanswered(CONTRIBUTING_FACTORS_FIELD),
                _left_unanswered(ACTION_ITEMS_FIELD),
                _left_unanswered(LESSONS_FIELD),
                _disclosed([])
            )
        )

@pytest.mark.unit
def test_the_model_is_asked_whether_its_chain_reaches_past_the_change_as_a_yes_or_no() -> None:
    # A rollback confirms which change set an incident off and says nothing of
    # why that change broke the service. Only the model knows whether its chain
    # went further, and a yes or no is the one answer no prose can blur.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[REACHES_A_CAUSE_FIELD]["type"]
        ) \
        .then(
            the_answer_was("boolean")
        )


@pytest.mark.unit
def test_a_chain_that_does_not_show_why_is_answered_as_reaching_no_cause() -> None:
    # A recorded answer said the evidence did not show why the new model scored
    # lower, and still answered that its chain reached a cause - taking the
    # swap and the drop it caused for the mechanism. That is what the change
    # did, not why it broke the service.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[REACHES_A_CAUSE_FIELD]["description"]
        ) \
        .then(
            _the_description_mentions("what the change did", "does not show why")
        )


@pytest.mark.unit
@pytest.mark.parametrize(("answered", "read_as"), [
    (True, True),
    (False, False),
    ("yes", False),
    (1, False),
    (None, False)
], ids=["yes", "no", "a word", "a number", "null"])
def test_only_a_plain_yes_reads_as_a_chain_that_reaches_a_cause(answered: object,
                                                                read_as: bool) -> None:
    # The box it ticks is one a person signs off on, so anything short of a
    # plain yes reads as no - and costs that box alone, never the answer.
    Scenario() \
        .given(
            a_submission := {REACHES_A_CAUSE_FIELD: answered}
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(a_submission).reaches_a_cause
        ) \
        .then(
            the_answer_was(read_as)
        )


@pytest.mark.unit
def test_an_answer_that_never_said_whether_its_chain_reaches_a_cause_reads_as_no() -> None:
    # Every answer recorded before the question existed carries no such field.
    # Read as a chain that stopped at the change, it unticks one box; refused,
    # it would cost a document that was otherwise whole.
    Scenario() \
        .given(
            an_answer_from_before_the_question := an_answer_without(REACHES_A_CAUSE_FIELD)
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                an_answer_from_before_the_question).reaches_a_cause
        ) \
        .then(
            the_answer_was(False)
        )


@pytest.mark.unit
@pytest.mark.parametrize(("answered", "read_as"), [
    (True, True),
    (False, False),
    ("yes", None),
    (1, None),
    (None, None)
], ids=["yes", "no", "a word", "a number", "null"])
def test_only_a_plain_yes_or_no_reads_as_how_the_logs_show_the_service(
        answered: object, read_as: bool | None) -> None:
    # Anything else is unanswered, and asked for again where it was asked -
    # never a guess the document then says, and never the whole answer refused.
    Scenario() \
        .given(
            a_submission := {LOGS_SHOW_SERVING_AS_BEFORE_FIELD: answered}
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(a_submission).logs_show_serving_as_before
        ) \
        .then(
            the_answer_was(read_as)
        )


@pytest.mark.unit
def test_whether_the_cause_rests_on_an_unrun_reading_is_asked_knowing_the_document_says_it(
) -> None:
    # Told to say so once in the root cause, eight write-ups called the cause
    # unverified there while the review ticked it as complete. Answered as a
    # yes or no, the document says it and sets the box from the same answer.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD][
                "description"]
        ) \
        .then(
            _the_description_mentions("F row", "nothing ran", "no S or D row",
                                      "the document says itself", "say neither in root_cause")
        )


@pytest.mark.unit
def test_whether_the_cause_rests_on_an_unrun_reading_is_asked_right_after_whether_it_has_one(
) -> None:
    # The two answers are about the same chain, and were measured asked in
    # this order.
    Scenario() \
        .when(
            lambda: list(SUBMIT_POSTMORTEM.properties)
        ) \
        .then(
            _comes_right_after(REACHES_A_CAUSE_FIELD, CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD)
        )


@pytest.mark.unit
def test_the_root_cause_leaves_whether_it_was_verified_to_the_document() -> None:
    # Said by the document from the answer, so a root cause that says it too
    # says it twice - or contradicts the box beside it.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[ROOT_CAUSE_FIELD]["description"]
        ) \
        .then(all_of(
            _the_description_mentions("the document says itself",
                                      CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD),
            _the_description_avoids("say so once")
        ))


@pytest.mark.unit
def test_whether_a_chain_reaches_a_cause_leaves_unverified_to_the_other_answer() -> None:
    # It counted an F-only step only where the chain called it unverified -
    # words the root cause no longer writes, so the step would stop counting.
    Scenario() \
        .when(
            lambda: SUBMIT_POSTMORTEM.properties[REACHES_A_CAUSE_FIELD]["description"]
        ) \
        .then(all_of(
            _the_description_mentions(CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD),
            _the_description_avoids("counts only where it says the reading is unverified")
        ))


@pytest.mark.unit
@pytest.mark.parametrize(("answered", "read_as"), [
    (True, True),
    (False, False),
    ("yes", None),
    (1, None),
    (None, None)
], ids=["yes", "no", "a word", "a number", "null"])
def test_only_a_plain_yes_or_no_reads_as_whether_the_cause_rests_on_an_unrun_reading(
        answered: object, read_as: bool | None) -> None:
    # Anything else is unanswered - never a guess the document then says.
    Scenario() \
        .given(
            a_submission := {CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD: answered}
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                a_submission).cause_rests_on_an_unrun_reading
        ) \
        .then(
            the_answer_was(read_as)
        )


@pytest.mark.unit
def test_an_answer_from_before_the_question_leaves_whether_it_rests_on_a_reading_unanswered(
) -> None:
    # Every answer recorded before the question existed carries no such field,
    # and its root cause already says whether the cause is unverified.
    Scenario() \
        .given(
            an_answer_from_before_the_question := an_answer_without(
                CAUSE_RESTS_ON_AN_UNRUN_READING_FIELD)
        ) \
        .when(
            lambda: SubmittedPostmortem.model_validate(
                an_answer_from_before_the_question).cause_rests_on_an_unrun_reading
        ) \
        .then(
            the_answer_was(None)
        )


def _comes_right_after(earlier: str, later: str) -> Assertion[list[str]]:
    def assertion(fields: list[str]) -> bool:
        if later not in fields or earlier not in fields \
                or fields.index(later) != fields.index(earlier) + 1:
            raise AssertionError(
                f"Expected [{later}] right after [{earlier}], got the fields in the "
                f"order {fields}.")

        return True

    return assertion


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


def _read_in_the_order_sentences_reads(
        answer: SubmittedPostmortem) -> Assertion[list[tuple[str, str]]]:
    """The same sentences `sentences` yields, in its order."""
    def assertion(placed: list[tuple[str, str]]) -> bool:
        read = [prose for _, prose in placed]

        if read != list(answer.sentences()):
            raise AssertionError(
                f"Expected the sentences {list(answer.sentences())}, each with its place, "
                f"got {read}.")

        return True

    return assertion


def _each_in_a_place_of_its_own() -> Assertion[list[tuple[str, str]]]:
    def assertion(placed: list[tuple[str, str]]) -> bool:
        places = [place for place, _ in placed]

        if len(set(places)) != len(places):
            raise AssertionError(f"Expected every sentence in a place of its own, got {places}.")

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


def _names_no_figure_starting(prefix: str) -> Assertion[dict[str, Figure]]:
    def assertion(figures: dict[str, Figure]) -> bool:
        named_so = sorted(name for name in figures if name.startswith(prefix))

        if named_so:
            raise AssertionError(
                f"Expected no figure named after [{prefix}], got {named_so}.")

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


def _requires_of_each_item(field: str) -> Assertion[dict[str, Any]]:
    def assertion(listed: dict[str, Any]) -> bool:
        required = listed["items"]["required"]

        if field not in required:
            raise AssertionError(
                f"Expected each item to require [{field}], it requires {required}.")

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


def _names_only_figures_it_may_name() -> Assertion[tuple[Transcript, dict[str, Figure]]]:
    def assertion(asked: tuple[Transcript, dict[str, Figure]]) -> bool:
        transcript, may_name = asked
        refused = sorted(set(names_in(_what_was_said(transcript))) - set(may_name))

        if refused:
            raise AssertionError(
                f"Expected every figure the brief names to be one an answer may name, "
                f"and it names {refused}, which the check refuses.")

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
