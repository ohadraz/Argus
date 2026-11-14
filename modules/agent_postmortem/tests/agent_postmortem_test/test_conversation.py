"""The one second chance, and the two things that earn it.

A field the model left out, and a figure it made up. They are answered
together: one further call naming what was wrong with the first, and then
whatever comes back is what the document is written from. There is no third
attempt - an incident that is over is not improved by an agent that will not
stop, and the faults are handed back so the caller can mark the document
partial.

The invented figure is the subtler of the two. Columns are safe from the model
by construction, but the model's prose is published as written, so a
sentence claiming a number Argus never computed reaches the one reader least
able to check it. A figure the incident gives is named instead, and the answer
kept has each name written in as this run measured it.

The shape of the second ask is the other half of this file, and it is not a
detail of wording. A submission is refused through the result of the call that
made it, because a provider that has seen a tool call expects its result next -
but a model that made no call submitted nothing there is anything to refuse, so
that one is asked again from the start. Getting it wrong produces a
conversation a provider will not accept, or one the model cannot make sense of.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from decimal import Decimal

import pytest
from agent_postmortem import DeploymentChangesRecord
from agent_postmortem.conversation import answer_worth_writing
from agent_postmortem.grounding import FLAGS_FIELD, QUOTE_FIELD, ROWS_FIELD, WHY_FIELD
from agent_postmortem.log_groups import grouped
from agent_postmortem.ordering import ORDER_FIELD
from agent_postmortem.prompting import (
    CAUSAL_CHAIN_FIELD,
    CAUSE_IN_PLAIN_WORDS_FIELD,
    CITES_FIELD,
    ITEM_FIELD,
    LEAD_EFFECTS_FIELD,
    LOGS_SHOW_SERVING_AS_BEFORE_FIELD,
    REACHES_A_CAUSE_FIELD,
    ROOT_CAUSE_FIELD,
    RULED_OUT_FIELD,
    STEP_FIELD,
    STILL_AT_RISK_FIELD,
    STOPS_THE_HARM_FIELD,
    TIMED_BY_FIELD,
    WENT_WELL_FIELD,
    WENT_WRONG_FIELD,
    WHAT_FIELD,
    WHY_IT_DID_NOT_HELP_FIELD,
    SubmittedPostmortem,
)
from argus_core import parse_iso, said_as_a_span, short_form, to_iso
from argus_core.events import PATCH_LINE_INDENT, a_changed_file_line
from argus_core.models import (
    Ask,
    ChangeEvent,
    ChangeKind,
    CodeUse,
    FileAsItRan,
    OpenedPullRequest,
    RevisionSource,
    ToolDefinition,
    ToolResults,
    Transcript,
    Turn,
    Verdict,
)
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    all_of,
    one_record_was_logged,
    the_answer_was,
)

from agent_postmortem_test.framework.builders import (
    ONSET,
    a_candidate,
    a_lead,
    a_measured_incident,
    a_model_answering_in_prose_then,
    a_model_answering_in_turn,
    a_model_calling,
    a_model_submitting_two_answers_at_once,
    a_timeline_entry,
    an_action,
    an_answer,
    an_answer_without,
    an_evidence_bundle,
)

# The figure this file's incident was measured at. The prose may not restate
# it in digits, which is what the cases below hold it to.
SOME_COMPUTED_LOSS = Decimal("500")

SOME_INVENTED_FIGURE = "$1,200,000"
SOME_CAUSE_WITHOUT_A_FIGURE = "checkout failed for several minutes"

# A log line inside the stretch the metrics did not watch, which begins at ONSET.
A_LINE_INSIDE_THE_GAP = f"{to_iso(ONSET + timedelta(minutes=4))} WARN io-shop: dont care"

# What a shop's integrity check reports, in its own words: one figure, which
# the incident then gives the name A1.
SOME_FINDING = "The widest total is short by 1,297.31."

# A claim no row of the record supports, in a root cause that is otherwise
# fine, the root cause corrected, and why the judge says the claim is not.
SOME_UNGROUNDED_CLAIM = "the flag was switched by hand"
A_ROOT_CAUSE_CLAIMING_IT = f"The cause was that {SOME_UNGROUNDED_CLAIM}."
A_GROUNDED_ROOT_CAUSE = "The cause was the flag change the record holds."
SOME_REASON_IT_IS_NOT = "no row says who switched it"
THE_CONVERSATION_S_LOGGER = "agent_postmortem.conversation"

DONT_CARE_STEP = "dont care which step"
DONT_CARE_WORDS = "dont care what the model wrote for it"

# A read of Argus's own that ruled something out, as the timeline carries it:
# its kind mirroring the event's, and its lead mirroring narration's.
THE_FIRST_ROW = "T1"
# When the read was made, which nothing here reads.
DONT_CARE_READ_AT = ONSET + timedelta(minutes=5)
CHANGES_RETRIEVED = "changes-retrieved"
FLAG_CHANGES_RETRIEVED = "flag-changes-retrieved"
NO_CHANGE_OF_ANY_KIND = "A deploy, release or flag change on the service"
NO_FLAG_CHANGE_BY_ANYONE_ELSE = "A flag change by anyone but Argus"
READ_NO_CHANGES = "Read back 0 production changes"
READ_NO_FLAG_CHANGES = "Read the flag provider's history - 0 flag changes"
INVESTIGATOR = "Investigator Agent"
ARGUS = "Argus"
# Rows that rule nothing out, and one the model's own words rest on: kinds
# mirroring the events' own.
METRICS_RETRIEVED = "metrics-retrieved"
ACTION_TAKEN = "action-taken"
READ_THE_METRICS = "Read the service's per-minute metrics"
RESTARTED_THE_REPLICAS = "Restarted the replicas"
MITIGATION = "Mitigation Agent"
CODE_FIX = "Code-Fix Agent"
# A figure written in digits and a size said in words: each sent back wherever
# a reader would see it.
A_FIGURE_IN_DIGITS = "541"
A_SIZE_IN_WORDS = "an hour"
# The start of the line a proposal is timed by, as the narration says it -
# the line itself goes on with the pull request after a dash.
PROPOSED_A_DRAFT = "Proposed a fix as a draft pull request"
# A line of the Investigator's, and an item the model timed by it: its words
# the model's, which code replaces with the line's.
FORMED_C1 = "Formed C1"
SOME_ITEM_TIMED_BY_IT = f"The {INVESTIGATOR} formed C1."
# How long after the alert a timed row came, and that span as the reading
# says it ahead of the row.
SOME_WAIT = timedelta(seconds=45)
AFTER_SOME_WAIT = f"{said_as_a_span(SOME_WAIT)} after the alert was raised"

type Reading = tuple[SubmittedPostmortem, list[str]]


@pytest.mark.unit
def test_an_answer_missing_a_field_is_asked_for_again_naming_what_was_missing() -> None:
    # Naming it matters as much as asking again. A model told only that its
    # answer was wrong will rewrite the part it liked least, which is rarely
    # the part that was missing.
    some_root_cause = "the checkout fallback was disabled"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_forgot_the_root_cause := a_model_answering_in_turn(
                an_answer_without(ROOT_CAUSE_FIELD),
                an_answer(root_cause=some_root_cause),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_forgot_the_root_cause,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, ROOT_CAUSE_FIELD),
                _the_correction_answered_the_call_it_rejected(asks),
                _answered_with(ROOT_CAUSE_FIELD, some_root_cause),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_second_answer_that_is_still_missing_a_field_is_handed_back_anyway() -> None:
    # The terminating case. Whatever came back is the postmortem, and the
    # faults come back with it: a document that says it is partial is worth
    # more than an agent still trying while the incident is over.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_forgets_twice := a_model_answering_in_turn(
                an_answer_without(ROOT_CAUSE_FIELD),
                an_answer_without(ROOT_CAUSE_FIELD),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_forgets_twice,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _found_a_fault()
            )
        )


@pytest.mark.unit
def test_a_second_answer_wrong_in_a_way_it_was_not_told_of_is_asked_for_once_more() -> None:
    # The first answer was refused for one thing and its rewrite got another
    # wrong. Told nothing of the second, the model never had an attempt at it.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_wrong_anew_in_its_rewrite := a_model_answering_in_turn(
                an_answer_without(ROOT_CAUSE_FIELD),
                an_answer(cause_in_plain_words=f"the outage cost {SOME_INVENTED_FIGURE}"),
                an_answer(cause_in_plain_words=SOME_CAUSE_WITHOUT_A_FIGURE),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_wrong_anew_in_its_rewrite,
                                         an_evidence_bundle(),
                                         a_measured_incident(loss=SOME_COMPUTED_LOSS))
        ) \
        .then(
            all_of(
                _was_asked(asks, times=3),
                _the_last_correction_named(asks, SOME_INVENTED_FIGURE),
                _answered_with(CAUSE_IN_PLAIN_WORDS_FIELD, SOME_CAUSE_WITHOUT_A_FIGURE),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_third_answer_is_handed_back_whatever_is_wrong_with_it() -> None:
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_wrong_three_times := a_model_answering_in_turn(
                an_answer_without(ROOT_CAUSE_FIELD),
                an_answer(cause_in_plain_words=f"the outage cost {SOME_INVENTED_FIGURE}"),
                an_answer_without(ROOT_CAUSE_FIELD),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_wrong_three_times,
                                         an_evidence_bundle(),
                                         a_measured_incident(loss=SOME_COMPUTED_LOSS))
        ) \
        .then(
            all_of(
                _was_asked(asks, times=3),
                _found_a_fault()
            )
        )


@pytest.mark.unit
def test_a_fault_it_was_told_of_said_again_in_other_words_is_not_asked_for_again() -> None:
    # Told its still_at_risk ran to two sentences, a rewrite still running to
    # two, reworded, was told already: its fault quotes the new words, but the
    # check that found it is the same one.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_repeating_itself := a_model_answering_in_turn(
                an_answer(still_at_risk="The totals stay short. Nobody has repaired them."),
                an_answer(still_at_risk="The totals are still short. Nothing repaired them."),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_repeating_itself,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _found_a_fault()
            )
        )


@pytest.mark.unit
def test_a_rewrite_that_made_no_call_is_asked_once_more_from_the_beginning() -> None:
    # Nothing in the second turn to attach a refusal to, so the third ask goes
    # from the opening: one following the first refusal would ask about an
    # answer the model can no longer see.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_wrote_prose_second := a_model_answering_in_turn(
                an_answer(cause_in_plain_words=f"the outage cost {SOME_INVENTED_FIGURE}"),
                None,
                an_answer(cause_in_plain_words=SOME_CAUSE_WITHOUT_A_FIGURE),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_wrote_prose_second,
                                         an_evidence_bundle(),
                                         a_measured_incident(loss=SOME_COMPUTED_LOSS))
        ) \
        .then(
            all_of(
                _was_asked(asks, times=3),
                _the_last_ask_was_a_fresh_one(asks),
                _the_last_correction_named(asks, SOME_INVENTED_FIGURE),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_cause_naming_a_figure_argus_never_computed_is_asked_for_again() -> None:
    # The whole reason this check exists. Nothing downstream can tell that
    # "$1.2M" was invented: it is a fluent sentence in a document whose every
    # other number is measured.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_invented_a_figure := a_model_answering_in_turn(
                an_answer(cause_in_plain_words=f"the outage cost {SOME_INVENTED_FIGURE}"),
                an_answer(cause_in_plain_words=SOME_CAUSE_WITHOUT_A_FIGURE),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_invented_a_figure,
                                         an_evidence_bundle(),
                                         a_measured_incident(loss=SOME_COMPUTED_LOSS))
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, SOME_INVENTED_FIGURE),
                _answered_with(CAUSE_IN_PLAIN_WORDS_FIELD, SOME_CAUSE_WITHOUT_A_FIGURE)
            )
        )


@pytest.mark.unit
def test_a_cause_saying_its_magnitudes_in_words_is_accepted() -> None:
    # The answer the rule asks for, accepted the first time - otherwise there
    # is no cause the model could write that would pass.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_answering_in_words := a_model_answering_in_turn(
                an_answer(cause_in_plain_words=SOME_CAUSE_WITHOUT_A_FIGURE),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_answering_in_words,
                                         an_evidence_bundle(),
                                         a_measured_incident(loss=SOME_COMPUTED_LOSS))
        ) \
        .then(
            all_of(
                _was_asked(asks),
                _answered_with(CAUSE_IN_PLAIN_WORDS_FIELD, SOME_CAUSE_WITHOUT_A_FIGURE),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_figure_the_answer_names_is_written_in_as_the_incident_gave_it() -> None:
    # In digits, exactly as measured - and the run's own figure, so an answer
    # recorded in one run and replayed in another states the second run's.
    Scenario() \
        .given(
            a_model_naming_a_figure := a_model_answering_in_turn(
                an_answer(cause_in_plain_words="The widest was short by {A1}."))
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_naming_a_figure,
                an_evidence_bundle().model_copy(update={"alert_finding": SOME_FINDING}),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _answered_with(CAUSE_IN_PLAIN_WORDS_FIELD, "The widest was short by 1,297.31."),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_figure_the_evidence_states_is_written_in_as_the_evidence_gave_it() -> None:
    # The model may say what its evidence said - when a change landed, how
    # often a log line came - by the name the figure is shown with there.
    Scenario() \
        .given(
            a_model_quoting_the_evidence := a_model_answering_in_turn(
                an_answer(cause_in_plain_words="The deploy landed at {P1.1}."))
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_quoting_the_evidence,
                an_evidence_bundle(changes=[ChangeEvent(kind=ChangeKind.DEPLOY,
                                                        occurred_at="2026-09-02T11:59:00Z",
                                                        reference="dont-care",
                                                        summary="dont care")]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _answered_with(CAUSE_IN_PLAIN_WORDS_FIELD,
                               "The deploy landed at 11:59 UTC."),
                _found_no_fault()
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize(("ended", "written"), [
    (timedelta(minutes=30), "The deploy landed at 11:59 UTC."),
    (timedelta(days=1), "The deploy landed at Sep 02, 11:59 UTC.")
], ids=["on-the-day-it-began", "on-another-day"])
def test_a_figure_in_the_cause_is_written_as_the_summary_says_its_own(ended: timedelta,
                                                                     written: str) -> None:
    # The summary carries the cause, and is posted where no head dates the
    # incident: in one Argus stopped on another day, a time in it written as
    # the page writes it read as a time of the day it was read.
    Scenario() \
        .given(
            a_model_quoting_the_evidence := a_model_answering_in_turn(
                an_answer(cause_in_plain_words="The deploy landed at {P1.1}."))
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_quoting_the_evidence,
                an_evidence_bundle(ended_at=ONSET + ended,
                                   changes=[ChangeEvent(kind=ChangeKind.DEPLOY,
                                                        occurred_at="2026-09-02T11:59:00Z",
                                                        reference="dont-care",
                                                        summary="dont care")]),
                a_measured_incident())
        ) \
        .then(
            _answered_with(CAUSE_IN_PLAIN_WORDS_FIELD, written)
        )


@pytest.mark.unit
def test_a_time_the_narration_said_in_what_is_still_at_risk_is_dated_off_the_page() -> None:
    # Not only a wire instant: a time a line of the narration said is on its
    # line's day, and the summary carrying this sentence says that day.
    Scenario() \
        .given(
            a_model_quoting_the_narration := a_model_answering_in_turn(
                an_answer(still_at_risk="The fault anchored at {T1.2} is still in place."))
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_quoting_the_narration,
                an_evidence_bundle(ended_at=ONSET + timedelta(days=1),
                                   timeline=[a_timeline_entry("anchored on 07:44:29",
                                                              at=ONSET)]),
                a_measured_incident())
        ) \
        .then(
            _answered_with(STILL_AT_RISK_FIELD,
                           "The fault anchored at Sep 02, 07:44:29 UTC is still in place.")
        )


@pytest.mark.unit
def test_a_minute_a_log_group_said_in_what_is_still_at_risk_is_dated_off_the_page() -> None:
    # A group's minute on the onset's day is said bare on its row, and is a
    # time of that day: off the page, in an incident Argus stopped the day
    # after, it read as a time of the day it was read.
    some_line = f"{to_iso(ONSET + timedelta(minutes=4))} ERROR checkout failed"
    its_label = grouped([some_line], None, ONSET.date())[0].label

    Scenario() \
        .given(
            a_model_quoting_the_logs := a_model_answering_in_turn(
                an_answer(still_at_risk=f"Checkout last failed at {{{its_label}.3}}."))
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_quoting_the_logs,
                an_evidence_bundle(ended_at=ONSET + timedelta(days=1), log_lines=[some_line]),
                a_measured_incident())
        ) \
        .then(
            _answered_with(STILL_AT_RISK_FIELD, "Checkout last failed at Sep 02, 12:04 UTC.")
        )


@pytest.mark.unit
def test_a_figure_the_incident_never_gave_is_asked_for_again_naming_it() -> None:
    # Nothing in code can know which figure a name for nothing meant, so the
    # model is asked - and what it names the second time is written in.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_naming_a_ghost_figure := a_model_answering_in_turn(
                an_answer(cause_in_plain_words="The widest was short by {A9}."),
                an_answer(cause_in_plain_words="The widest was short by {A1}."),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_naming_a_ghost_figure,
                an_evidence_bundle().model_copy(update={"alert_finding": SOME_FINDING}),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, "{A9}"),
                _answered_with(CAUSE_IN_PLAIN_WORDS_FIELD, "The widest was short by 1,297.31."),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_model_that_ignored_the_tool_is_asked_again_from_the_beginning() -> None:
    # There is no call to answer, so the correction cannot be a tool result: a
    # rejection has to be attached to something the model submitted, and this
    # model submitted a paragraph. The whole incident goes again.
    some_root_cause = "the checkout fallback was disabled"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_wrote_prose_first := a_model_answering_in_prose_then(
                an_answer(root_cause=some_root_cause), recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_wrote_prose_first,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_was_a_fresh_ask(asks),
                _answered_with(ROOT_CAUSE_FIELD, some_root_cause),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_model_that_ignores_the_tool_twice_answers_nothing() -> None:
    # The terminating case for the other shape of bad answer. Two paragraphs is
    # not one attempt away from a document, and nothing in a paragraph can be
    # read into a field.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_only_writes_prose := a_model_answering_in_prose_then(
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_only_writes_prose,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _answered_nothing(),
                _found_a_fault()
            )
        )


@pytest.mark.unit
def test_an_answer_calling_some_other_tool_is_read_as_no_answer() -> None:
    # Not the same failure as answering in prose, though it lands in the same
    # place: this model did reach for a tool, and reached for the wrong one.
    # Reading its arguments anyway would fill the document from a call that was
    # never the postmortem - fields with the right names, about something else
    # entirely.
    some_other_tool = "get_log_lines"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_calling_the_wrong_tool := a_model_calling(some_other_tool,
                                                              recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_calling_the_wrong_tool,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _answered_nothing(),
                _found_a_fault()
            )
        )


@pytest.mark.unit
def test_an_answer_submitted_twice_in_one_turn_is_asked_for_again() -> None:
    # Two calls do not say which is the answer, so the turn is refused through
    # both. Asked again and calling twice again, the first is read - the fault
    # on record, as any fault left after the second attempt is.
    some_root_cause = "the checkout fallback was disabled"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_submitting_twice := a_model_submitting_two_answers_at_once(
                an_answer(root_cause=some_root_cause),
                an_answer(root_cause="placeholder"),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_submitting_twice,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, "2 times"),
                _answered_with(ROOT_CAUSE_FIELD, some_root_cause),
                _found_a_fault()
            )
        )


@pytest.mark.unit
def test_a_model_that_answers_completely_is_asked_once() -> None:
    # The second call belongs to the checklist and to nothing else. An agent
    # that asked twice as a matter of course would double the cost of every
    # postmortem to improve none of them.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_answering_completely := a_model_answering_in_turn(
                an_answer(), recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_answering_completely,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_an_investigation_that_named_no_cause_is_written_up_with_the_cause_said_not_determined(
) -> None:
    # The model is offered no place for the cause and is not sent back for one;
    # the answer kept says it was not determined, in the document's words, and
    # claims no chain reaching a cause - even where an answer said one.
    asks: Kept[Transcript] = Kept()
    offered: Kept[list[ToolDefinition]] = Kept()

    Scenario() \
        .given(
            a_model_writing_a_cause_anyway := a_model_answering_in_turn(
                an_answer(root_cause="the flags had not been changed by anyone",
                          reaches_a_cause=True),
                recording_into=asks, offered_tools=offered)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_writing_a_cause_anyway,
                an_evidence_bundle(candidates=[
                    a_candidate("no cause determined for HighErrorRate on io-shop",
                                confidence=None).model_copy(update={"failure_mode": None})]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks),
                _was_offered_no_place_for(offered, ROOT_CAUSE_FIELD),
                _was_offered_no_place_for(offered, REACHES_A_CAUSE_FIELD),
                _answered_with(ROOT_CAUSE_FIELD,
                               "Not determined: the investigation named no cause."),
                _answered_with(CAUSE_IN_PLAIN_WORDS_FIELD, "The cause is not known."),
                _claims_no_cause_reached(),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_an_incident_people_wrote_about_is_asked_what_each_lead_changed() -> None:
    # The tool the model is offered is the one for this incident: asked with
    # the tool every incident gets, a model would have nowhere to say what a
    # lead changed and the check would refuse it for not saying.
    offered: Kept[list[ToolDefinition]] = Kept()

    Scenario() \
        .given(
            a_model_noting_its_tools := a_model_answering_in_turn(
                an_answer(lead_effects={"L1": "it named the flag reverted"}),
                offered_tools=offered)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_noting_its_tools,
                an_evidence_bundle(leads=[a_lead("the kuki flag was flipped at noon")]),
                a_measured_incident())
        ) \
        .then(
            _was_offered_a_place_for(offered, LEAD_EFFECTS_FIELD)
        )


@pytest.mark.unit
def test_an_incident_whose_logs_reach_where_the_metrics_stopped_is_asked_how_they_show_it(
) -> None:
    # The document says how the service did over that stretch from this
    # answer, so the tool for this incident has to offer a place for it.
    offered: Kept[list[ToolDefinition]] = Kept()

    Scenario() \
        .given(
            a_model_noting_its_tools := a_model_answering_in_turn(
                an_answer() | {LOGS_SHOW_SERVING_AS_BEFORE_FIELD: True},
                offered_tools=offered)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_noting_its_tools,
                an_evidence_bundle(log_lines=[A_LINE_INSIDE_THE_GAP]),
                a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET))
        ) \
        .then(
            _was_offered_a_place_for(offered, LOGS_SHOW_SERVING_AS_BEFORE_FIELD)
        )


@pytest.mark.unit
def test_an_answer_silent_on_how_the_logs_show_the_service_is_asked_for_again_naming_it() -> None:
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_left_it_out := a_model_answering_in_turn(
                an_answer(),
                an_answer() | {LOGS_SHOW_SERVING_AS_BEFORE_FIELD: True},
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_that_left_it_out,
                an_evidence_bundle(log_lines=[A_LINE_INSIDE_THE_GAP]),
                a_measured_incident(back_to_normal_at=None, metrics_stopped_at=ONSET))
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, LOGS_SHOW_SERVING_AS_BEFORE_FIELD),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_an_incident_a_change_put_back_left_standing_is_asked_what_stops_the_harm() -> None:
    # The tool for this incident offers a place for the item, and which tool
    # that is turns on what the record holds of the change and the service.
    offered: Kept[list[ToolDefinition]] = Kept()

    Scenario() \
        .given(
            a_model_noting_its_tools := a_model_answering_in_turn(
                an_answer() | {STOPS_THE_HARM_FIELD: "dont care",
                               WHY_IT_DID_NOT_HELP_FIELD: "dont care"},
                offered_tools=offered)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_noting_its_tools,
                an_evidence_bundle(
                    actions=[an_action("dont care", verdict=Verdict.REFUTED, put_back=True)]),
                a_measured_incident(back_to_normal_at=None))
        ) \
        .then(
            all_of(
                _was_offered_a_place_for(offered, STOPS_THE_HARM_FIELD),
                _was_offered_a_place_for(offered, WHY_IT_DID_NOT_HELP_FIELD)
            )
        )


@pytest.mark.unit
def test_an_answer_silent_on_what_stops_the_harm_is_asked_for_again_naming_it() -> None:
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_left_it_out := a_model_answering_in_turn(
                an_answer() | {WHY_IT_DID_NOT_HELP_FIELD: "dont care"},
                an_answer() | {STOPS_THE_HARM_FIELD: "dont care",
                               WHY_IT_DID_NOT_HELP_FIELD: "dont care"},
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_that_left_it_out,
                an_evidence_bundle(
                    actions=[an_action("dont care", verdict=Verdict.REFUTED, put_back=True)]),
                a_measured_incident(back_to_normal_at=None))
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, STOPS_THE_HARM_FIELD),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_an_answer_silent_on_why_it_did_not_help_is_asked_for_again_naming_it() -> None:
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_that_left_it_out := a_model_answering_in_turn(
                an_answer() | {STOPS_THE_HARM_FIELD: "dont care"},
                an_answer() | {STOPS_THE_HARM_FIELD: "dont care",
                               WHY_IT_DID_NOT_HELP_FIELD: "dont care"},
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_that_left_it_out,
                an_evidence_bundle(
                    actions=[an_action("dont care", verdict=Verdict.REFUTED, put_back=True)]),
                a_measured_incident(back_to_normal_at=None))
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, WHY_IT_DID_NOT_HELP_FIELD),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_an_answer_silent_about_a_lead_is_asked_for_again_naming_it() -> None:
    # As a missing field is: the person who wrote it is owed the line, and a
    # model told which lead it skipped has one thing to put right.
    asks: Kept[Transcript] = Kept()
    some_leads = [a_lead("the kuki flag was flipped at noon", ts="1760000100.000200"),
                  a_lead("it is the database again", ts="1760000200.000300")]

    Scenario() \
        .given(
            a_model_that_skipped_a_lead := a_model_answering_in_turn(
                an_answer(lead_effects={"L1": "it named the flag reverted"}),
                an_answer(lead_effects={"L1": "it named the flag reverted",
                                        "L2": "it changed nothing"}),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_skipped_a_lead,
                                         an_evidence_bundle(leads=some_leads),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, "[L2]"),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_revision_the_model_misremembered_is_written_as_the_one_it_meant() -> None:
    # Corrected by code rather than refused: the revision meant is the one the
    # incident read that it starts like, and a second call to put back one
    # character would pay twice for what code can do.
    some_revision_read = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
    some_revision_a_character_off = some_revision_read[:7] + "3"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_a_character_off := a_model_answering_in_turn(
                an_answer(root_cause=f"revision {some_revision_a_character_off} broke it"),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_a_character_off,
                an_evidence_bundle(changes=[ChangeEvent(kind=ChangeKind.DEPLOY,
                                                        occurred_at="2026-09-02T11:59:00Z",
                                                        reference=some_revision_read,
                                                        summary="dont care")]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks),
                _answered_with(ROOT_CAUSE_FIELD, f"revision {some_revision_read[:7]} broke it"),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_pull_request_another_run_opened_is_written_as_the_one_the_record_holds() -> None:
    # A replayed answer names the pull request its recording run opened. Written
    # by code, as a misremembered revision is: the record holds one.
    some_pull_request = OpenedPullRequest(number=1,
                                          url="https://github.invalid/acme/shop/pull/1",
                                          branch="argus/fix-abc")
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_naming_another := a_model_answering_in_turn(
                an_answer(root_cause="PR #356 holds the fix"), recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_naming_another,
                                         an_evidence_bundle(pull_request=some_pull_request),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks),
                _answered_with(ROOT_CAUSE_FIELD, "PR #1 holds the fix"),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_revision_the_incident_never_read_is_asked_for_again_naming_it() -> None:
    # Nothing in code can know what a revision starting like none of them
    # meant, so the model is asked - naming it, as every other fault is named.
    some_revision_read = "26f1d7e2c82ce2abff8f9b6424dc226f4f37fed2"
    some_revision_nobody_read = "9999abcd"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_naming_a_stranger := a_model_answering_in_turn(
                an_answer(root_cause=f"revision {some_revision_nobody_read} broke it"),
                an_answer(root_cause=f"revision {some_revision_read[:8]} broke it"),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_naming_a_stranger,
                an_evidence_bundle(changes=[ChangeEvent(kind=ChangeKind.DEPLOY,
                                                        occurred_at="2026-09-02T11:59:00Z",
                                                        reference=some_revision_read,
                                                        summary="dont care")]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, some_revision_nobody_read),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_root_cause_naming_the_deploy_that_set_it_off_is_asked_for_again() -> None:
    # What the answer is held to includes the trigger the document states: a
    # root cause opening with that deploy's revision is sent back, naming it.
    the_trigger = "53f02e9a1b2c3d4e5f60718293a4b5c6d7e8f901"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_naming_the_trigger := a_model_answering_in_turn(
                an_answer(root_cause=f"Revision {the_trigger[:7]} renamed the port."),
                an_answer(root_cause="The scrape still asks for a port nothing has."),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_naming_the_trigger,
                an_evidence_bundle(
                    candidates=[a_candidate("dont care", subject="io-shop",
                                            to_state=the_trigger, tested=True,
                                            result=Verdict.CONFIRMED,
                                            failure_mode="bad-deployment")],
                    changes=[ChangeEvent(kind=ChangeKind.DEPLOY,
                                         occurred_at="2026-09-02T11:59:00Z",
                                         reference=the_trigger, summary="dont care")]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, the_trigger[:7]),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_root_cause_naming_the_deploy_that_carried_it_is_asked_for_again() -> None:
    # c2's own shape: the leading candidate blames a file and names no states,
    # and the deploy whose diff changed that file is what the document states
    # set it off. Its revision in the root cause is the trigger said again.
    the_trigger = "53f02e9a1b2c3d4e5f60718293a4b5c6d7e8f901"
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_naming_the_carrier := a_model_answering_in_turn(
                an_answer(root_cause=f"Revision {the_trigger[:7]} renamed the port."),
                an_answer(root_cause="The scrape still asks for a port nothing has."),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_naming_the_carrier,
                an_evidence_bundle(
                    candidates=[a_candidate("dont care",
                                            subject="deploy/values-production.yaml")],
                    changes=[ChangeEvent(kind=ChangeKind.DEPLOY,
                                         occurred_at="2026-09-02T11:58:00Z",
                                         reference=the_trigger, summary="dont care")],
                    deployment_changes=[DeploymentChangesRecord(revision=the_trigger, said=[
                        a_changed_file_line("modified", "deploy/values-production.yaml"),
                        f"{PATCH_LINE_INDENT}-  portName: metrics",
                        f"{PATCH_LINE_INDENT}+  portName: http-metrics"])]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, the_trigger[:7]),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_fault_it_was_told_of_in_one_place_made_in_another_is_asked_for_once_more() -> None:
    # Told of it in a step of the chain, a rewrite said it in the root cause,
    # which the first answer had right: the same check, somewhere it was never
    # told of.
    asks: Kept[Transcript] = Kept()
    lumped = "The statement and the reconciliation read it as the month's figure."
    some_uses = [
        CodeUse(name="month", path="src/shop/monthly_statement.py", line=12,
                function="render_statement", does="reads it: total = account.month"),
        CodeUse(name="month", path="src/shop/spend_reconciliation.py", line=20,
                function="reconcile",
                does="compares it with bought(account), where bought(account) returns "
                     "sum(account.purchases)", set_against_a_call=True)
    ]

    Scenario() \
        .given(
            a_model_moving_its_mistake := a_model_answering_in_turn(
                an_answer(causal_chain=[{STEP_FIELD: lumped, CITES_FIELD: ["T1"]}]),
                an_answer(root_cause=lumped),
                an_answer(root_cause="The statement still shows the stored figure."),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_moving_its_mistake,
                an_evidence_bundle(fix_explanation="dont care").model_copy(
                    update={"uses_outside": some_uses}),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=3),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_root_cause_saying_one_role_of_lines_whose_rows_differ_is_asked_for_again() -> None:
    # What the answer is held to includes the lines outside Code-Fix's patch,
    # each under the label the model was shown it by.
    asks: Kept[Transcript] = Kept()
    some_uses = [
        CodeUse(name="month", path="src/shop/monthly_statement.py", line=12,
                function="render_statement", does="reads it: total = account.month"),
        CodeUse(name="month", path="src/shop/spend_reconciliation.py", line=20,
                function="reconcile",
                does="compares it with bought(account), where bought(account) returns "
                     "sum(account.purchases)", set_against_a_call=True)
    ]

    Scenario() \
        .given(
            a_model_lumping_them := a_model_answering_in_turn(
                an_answer(root_cause="The statement and the reconciliation read it as the "
                                     "month's figure."),
                an_answer(root_cause="The statement still shows the stored figure."),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_lumping_them,
                an_evidence_bundle(fix_explanation="dont care").model_copy(
                    update={"uses_outside": some_uses}),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, "[U2]"),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_an_answer_crediting_the_investigator_with_a_flag_only_argus_read_is_asked_again(
) -> None:
    # What the answer is held to includes each change only Argus's own read of
    # the flag history found, under the label the model was shown it by.
    asks: Kept[Transcript] = Kept()
    the_flag_both_read = ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                     occurred_at="2026-09-02T11:59:00Z",
                                     reference="monthly-spend-feature",
                                     summary="dont care")
    the_flag_only_argus_read = ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                           occurred_at="2026-09-02T12:04:00Z",
                                           reference="an-unrelated-feature",
                                           summary="dont care")

    Scenario() \
        .given(
            a_model_crediting_the_investigator := a_model_answering_in_turn(
                an_answer(root_cause="The Investigator tied the onset to the "
                                     "monthly-spend-feature flag change. It set aside the "
                                     "other flag change because that change came after the "
                                     "onset."),
                an_answer(),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_crediting_the_investigator,
                an_evidence_bundle(
                    changes=[the_flag_both_read, the_flag_only_argus_read]
                ).model_copy(update={"changes_the_walk_alone_read": [the_flag_only_argus_read]}),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, "[P2]"),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_flag_only_argus_read_that_a_candidate_names_is_one_the_investigator_weighed() -> None:
    # The walk turns back the flag a candidate blamed, so a causing flag
    # switched just past the Investigator's own window is one only the walk's
    # read found and one the Investigator named. Crediting it with that flag is
    # true, and asked again for it the model would be told to give the
    # diagnosis to the flag read.
    asks: Kept[Transcript] = Kept()
    the_flag_only_argus_read = ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                           occurred_at="2026-09-02T12:04:00Z",
                                           reference="an-unrelated-feature",
                                           summary="dont care")

    Scenario() \
        .given(
            a_model_crediting_the_investigator := a_model_answering_in_turn(
                an_answer(root_cause="The Investigator tied the errors to an-unrelated-feature."),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_crediting_the_investigator,
                an_evidence_bundle(
                    changes=[the_flag_only_argus_read],
                    candidates=[a_candidate("The feature flag an-unrelated-feature was switched "
                                            "on, and the errors began with it.")]
                ).model_copy(update={"changes_the_walk_alone_read": [the_flag_only_argus_read]}),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_flag_only_argus_read_that_a_candidate_blamed_in_other_words_is_one_it_weighed(
) -> None:
    # What the walk turns back is the flag a candidate blamed - its subject -
    # whatever words the candidate said it in.
    asks: Kept[Transcript] = Kept()
    the_flag_only_argus_read = ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                           occurred_at="2026-09-02T12:04:00Z",
                                           reference="an-unrelated-feature",
                                           summary="dont care")

    Scenario() \
        .given(
            a_model_crediting_the_investigator := a_model_answering_in_turn(
                an_answer(root_cause="The Investigator tied the errors to an-unrelated-feature."),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_crediting_the_investigator,
                an_evidence_bundle(
                    changes=[the_flag_only_argus_read],
                    candidates=[a_candidate("The legacy checkout fallback was switched on, and "
                                            "the errors began with it.",
                                            subject="an-unrelated-feature")]
                ).model_copy(update={"changes_the_walk_alone_read": [the_flag_only_argus_read]}),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_an_item_of_what_went_well_timed_by_a_row_is_read_after_its_span_from_the_alert(
) -> None:
    # The model names the row and writes no span; the reading says the span
    # first, worked out from the row's instant as the brief showed it.
    the_alert = parse_iso("2026-09-02T12:00:00Z")

    Scenario() \
        .given(
            a_model_timing_an_item := a_model_answering_in_turn(
                an_answer(lessons={WENT_WELL_FIELD: [
                    {ITEM_FIELD: SOME_ITEM_TIMED_BY_IT, TIMED_BY_FIELD: "T1"}]}))
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_timing_an_item,
                an_evidence_bundle(
                    alerted_at=the_alert,
                    timeline=[a_timeline_entry(FORMED_C1, at=the_alert + SOME_WAIT,
                                               who=INVESTIGATOR)]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _found_no_fault(),
                _what_went_well_read([f"{AFTER_SOME_WAIT}, the {INVESTIGATOR} "
                                      f"{_lowered(FORMED_C1)}."])
            )
        )


@pytest.mark.unit
def test_an_item_timed_by_a_row_says_the_row_as_the_timeline_shows_it() -> None:
    # A row is written for the model, which is told each revision and the fix
    # whole and each name in brackets. Said in the list of what went well it
    # reads as the timeline beside it shows the same row - the revision short,
    # the fix by its name, a name as code - or forty characters, a bare
    # address and brackets stand where the timeline shows none of them.
    the_alert = parse_iso("2026-09-02T12:00:00Z")
    some_wait = timedelta(seconds=45)
    # How long before the alert the deploy went out.
    some_lead = timedelta(minutes=1)
    some_revision_read = "7c3ca00c7528df68d533f6e87acd4f23a55ab342"
    some_repository = "acme/shop"
    its_address = f"https://github.invalid/{some_repository}"
    dont_care_summary = "dont care"
    some_pull_request = OpenedPullRequest(number=1, url=f"{its_address}/pull/1",
                                          branch="argus/fix-abc")
    some_count, some_service = 90, "io-shop"
    after_the_wait = f"{said_as_a_span(some_wait)} after the alert was raised"

    Scenario() \
        .given(
            a_model_timing_three_items := a_model_answering_in_turn(
                an_answer(lessons={WENT_WELL_FIELD: [
                    # Opening with whoever did it, as an item timed by a row
                    # must; its words go, so the rest is anything.
                    {ITEM_FIELD: "The Investigator Agent read it.", TIMED_BY_FIELD: "T1"},
                    {ITEM_FIELD: "The Code-Fix Agent proposed it.", TIMED_BY_FIELD: "T2"},
                    {ITEM_FIELD: "Argus moved it.", TIMED_BY_FIELD: "T3"}]}))
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_timing_three_items,
                an_evidence_bundle(
                    alerted_at=the_alert,
                    changes=[ChangeEvent(kind=ChangeKind.DEPLOY,
                                         occurred_at=to_iso(the_alert - some_lead),
                                         reference=some_revision_read,
                                         summary=dont_care_summary,
                                         revision_source=RevisionSource(
                                             repository=some_repository,
                                             repository_address=its_address,
                                             revision_address=f"{its_address}/commit/"
                                                              f"{some_revision_read}"))],
                    pull_request=some_pull_request,
                    timeline=[
                        a_timeline_entry(f"Read what the deployment of {some_revision_read} "
                                         "changed", at=the_alert + some_wait,
                                         who="Investigator Agent"),
                        a_timeline_entry("Proposed a fix as a draft pull request - "
                                         f"{some_pull_request.url}", at=the_alert + some_wait,
                                         who="Code-Fix Agent"),
                        a_timeline_entry(f"Moved the incident to MITIGATED - discarded "
                                         f"[{some_count}] of [{some_service}]'s stale cached "
                                         "figures", at=the_alert + some_wait, who="Argus")]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _found_no_fault(),
                _what_went_well_read([
                    f"{after_the_wait}, the Investigator Agent read what the deployment of "
                    f"{short_form(some_revision_read, frozenset({some_revision_read}))} "
                    "changed.",
                    f"{after_the_wait}, the Code-Fix Agent proposed a fix as a draft pull "
                    f"request - {some_pull_request.name}.",
                    f"{after_the_wait}, Argus moved the incident to MITIGATED - discarded "
                    f"`{some_count}` of `{some_service}`'s stale cached figures."])
            )
        )


@pytest.mark.unit
def test_an_item_timed_by_a_row_may_open_with_whoever_the_timeline_says_did_it() -> None:
    # Who did it is whoever the record's lines are said by - an agent, or a
    # person writing in the thread - so what an item may open with comes off
    # the timeline, not a list of names.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_timing_an_item := a_model_answering_in_turn(
                an_answer(lessons={WENT_WELL_FIELD: [
                    {ITEM_FIELD: "Code-Fix proposed PR #7.", TIMED_BY_FIELD: "T1"}]}),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_timing_an_item,
                an_evidence_bundle(timeline=[a_timeline_entry("dont care",
                                                              who="Code-Fix Agent")]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_an_item_timed_by_a_row_that_is_not_the_timeline_s_is_asked_for_once_more() -> None:
    # A candidate's first figure is no instant anything was done at - here a
    # share of requests, which timed as one failed the whole write-up. Sent
    # back instead, and the item timed by the row the model names next.
    asks: Kept[Transcript] = Kept()
    the_alert = parse_iso("2026-09-02T12:00:00Z")

    Scenario() \
        .given(
            a_model_timing_by_a_candidate := a_model_answering_in_turn(
                an_answer(lessons={WENT_WELL_FIELD: [
                    {ITEM_FIELD: SOME_ITEM_TIMED_BY_IT, TIMED_BY_FIELD: "C1"}]}),
                an_answer(lessons={WENT_WELL_FIELD: [
                    {ITEM_FIELD: SOME_ITEM_TIMED_BY_IT, TIMED_BY_FIELD: "T1"}]}),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_timing_by_a_candidate,
                an_evidence_bundle(
                    alerted_at=the_alert,
                    timeline=[a_timeline_entry(FORMED_C1, at=the_alert + SOME_WAIT,
                                               who=INVESTIGATOR)],
                    candidates=[a_candidate("The error rate rose to 33% of requests.")]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_last_correction_named(asks, "timed by [C1], which is no row of the "
                                                 "timeline"),
                _found_no_fault(),
                _what_went_well_read([f"{AFTER_SOME_WAIT}, the {INVESTIGATOR} "
                                      f"{_lowered(FORMED_C1)}."])
            )
        )


@pytest.mark.unit
def test_a_credit_moved_into_another_item_is_asked_for_once_more() -> None:
    # Told of it in a lesson, a rewrite that says it in what a step ruled out
    # makes a fault it was never told of there.
    asks: Kept[Transcript] = Kept()
    the_flag_only_argus_read = ChangeEvent(kind=ChangeKind.FLAG_TOGGLE,
                                           occurred_at="2026-09-02T12:04:00Z",
                                           reference="an-unrelated-feature",
                                           summary="dont care")
    the_slip = ("The Investigator tied the onset to the monthly-spend-feature flag change. "
                "It set aside the other flag change because that change came after the onset.")

    Scenario() \
        .given(
            a_model_moving_the_credit := a_model_answering_in_turn(
                an_answer(lessons={WENT_WELL_FIELD: [the_slip]}),
                an_answer(causal_chain=[{STEP_FIELD: "dont care", CITES_FIELD: ["T1"],
                                          RULED_OUT_FIELD: [{WHAT_FIELD: the_slip,
                                                              CITES_FIELD: ["T1"]}]}]),
                an_answer(),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_moving_the_credit,
                an_evidence_bundle(changes=[the_flag_only_argus_read]).model_copy(
                    update={"changes_the_walk_alone_read": [the_flag_only_argus_read]}),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=3),
                _the_correction_on_ask_named(asks, 3, "[P1]"),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_an_accepted_chain_is_put_in_the_order_its_whys_answer_each_other() -> None:
    # Asked for the five whys, a write-up gave the step saying why the symptom
    # happened after the one it explains. Asked once more, by number, the model
    # puts them in order without a word of them changing.
    some_chain = [{STEP_FIELD: f"step {letter}", CITES_FIELD: ["T1"]}
                  for letter in "abcd"]

    Scenario() \
        .given(
            a_model_answering_then_ordering := a_model_answering_in_turn(
                an_answer(causal_chain=some_chain), {ORDER_FIELD: [1, 3, 2, 4]})
        ) \
        .when(
            lambda: [step.step for step in answer_worth_writing(
                a_model_answering_then_ordering, an_evidence_bundle(),
                a_measured_incident())[0].causal_chain or []]
        ) \
        .then(
            the_answer_was(["step a", "step c", "step b", "step d"])
        )


@pytest.mark.unit
def test_a_chain_asked_for_again_is_put_in_order_once_the_second_answer_is_read() -> None:
    # The second answer is the one the document carries, whatever faults it
    # still has, so it is the one whose chain is ordered.
    some_chain = [{STEP_FIELD: f"step {letter}", CITES_FIELD: ["T1"]}
                  for letter in "abcd"]

    Scenario() \
        .given(
            a_model_answering_twice_then_ordering := a_model_answering_in_turn(
                an_answer_without(ROOT_CAUSE_FIELD),
                an_answer(causal_chain=some_chain),
                {ORDER_FIELD: [1, 3, 2, 4]})
        ) \
        .when(
            lambda: [step.step for step in answer_worth_writing(
                a_model_answering_twice_then_ordering, an_evidence_bundle(),
                a_measured_incident())[0].causal_chain or []]
        ) \
        .then(
            the_answer_was(["step a", "step c", "step b", "step d"])
        )


@pytest.mark.unit
def test_a_step_resting_on_a_candidate_cause_is_asked_for_again_naming_it() -> None:
    # The candidates are shown under labels of their own, beside the evidence,
    # so a step can cite one - and the check has to know which labels they are.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_citing_a_guess := a_model_answering_in_turn(
                an_answer(causal_chain=[{STEP_FIELD: "dont care", CITES_FIELD: ["T1", "C1"]}]),
                an_answer(causal_chain=[{STEP_FIELD: "dont care", CITES_FIELD: ["T1"]}]),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(a_model_citing_a_guess,
                                         an_evidence_bundle(candidates=[a_candidate("dont care")]),
                                         a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, "[C1]"),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_step_resting_on_code_fix_s_reading_alone_is_asked_for_again_naming_what_ran() -> None:
    # The files as they ran are shown beneath the reading, so the check has to
    # know which labels they are and what each names.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_resting_on_the_reading := a_model_answering_in_turn(
                an_answer(causal_chain=[{STEP_FIELD: "dont care", CITES_FIELD: ["T1", "F1"]}]),
                an_answer(causal_chain=[{STEP_FIELD: "dont care",
                                         CITES_FIELD: ["T1", "F1", "S1"]}]),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_resting_on_the_reading,
                an_evidence_bundle(fix_explanation="dont care").model_copy(update={
                    "files_as_they_ran": [FileAsItRan(
                        path="deploy/scrape.yaml",
                        revision="53f02e9f6cb774f7f5869637bcc879941dcbc82d",
                        as_read=False, content="selector:\n  port: metrics\n")]}),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, "[S1] deploy/scrape.yaml at 53f02e9"),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_step_resting_on_a_candidate_shown_under_another_s_label_is_asked_for_again() -> None:
    # Shown on the line of the candidate it is one cause with, C2 is still a
    # candidate - and still no evidence for a step.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model_citing_a_guess := a_model_answering_in_turn(
                an_answer(causal_chain=[{STEP_FIELD: "dont care", CITES_FIELD: ["T1", "C2"]}]),
                an_answer(causal_chain=[{STEP_FIELD: "dont care", CITES_FIELD: ["T1"]}]),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_citing_a_guess,
                an_evidence_bundle(candidates=[
                    a_candidate("dont care", subject="categoriser.model",
                                from_state="v1", to_state="v2"),
                    a_candidate("dont care either", subject="categoriser.model",
                                from_state="v1", to_state="v2")]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, "cites [C2], a candidate cause"),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_braces_the_evidence_itself_quotes_are_kept_as_written() -> None:
    # A candidate quoting a format string holds braces that name no figure.
    # Quoted back they are the evidence's own text, and asking again for a
    # figure by that name asks for one nobody has.
    asks: Kept[Transcript] = Kept()
    some_format = "'{amount_cents}/{items_counted}'"

    Scenario() \
        .given(
            a_model_quoting_the_evidence := a_model_answering_in_turn(
                an_answer(cause_in_plain_words=f"The new revision writes {some_format}."),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model_quoting_the_evidence,
                an_evidence_bundle(candidates=[
                    a_candidate(f"The cache entry became the text {some_format}.")]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=1),
                _answered_with(CAUSE_IN_PLAIN_WORDS_FIELD,
                               f"The new revision writes {some_format}."),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_an_answer_asked_for_again_is_logged_as_a_warning(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Usually corrected on the second attempt, so a second call paid for shows
    # nowhere but here.
    Scenario() \
        .given(
            a_model_that_forgot_the_root_cause := a_model_answering_in_turn(
                an_answer_without(ROOT_CAUSE_FIELD),
                an_answer(root_cause="the checkout fallback was disabled"))
        ) \
        .when(
            lambda: answer_worth_writing(a_model_that_forgot_the_root_cause,
                                         an_evidence_bundle(),
                                         a_measured_incident())
        ) \
        .then(
            one_record_was_logged(caplog, "agent_postmortem.conversation", logging.WARNING,
                                  "postmortem answer rejected")
        )


def _was_asked(asks: Kept[Transcript], times: int = 1) -> Assertion[Reading]:
    """How many times the model was put the question.

    Once by default, because once is what a good answer costs and every extra
    call is a postmortem paying twice to improve nothing.
    """
    def assertion(dont_care_reading: Reading) -> bool:
        if len(asks.taken) != times:
            raise AssertionError(
                f"Expected the model to be asked [{times}] time(s), got "
                f"[{len(asks.taken)}].")

        return True

    return assertion


def _was_offered_a_place_for(offered: Kept[list[ToolDefinition]],
                             field: str) -> Assertion[Reading]:
    def assertion(dont_care_reading: Reading) -> bool:
        fields = [sorted(tool.properties) for tools in offered.taken for tool in tools]

        if not fields or any(field not in properties for properties in fields):
            raise AssertionError(
                f"Expected every tool the model was offered to ask for [{field}], "
                f"and they asked for {fields}.")

        return True

    return assertion


def _was_offered_no_place_for(offered: Kept[list[ToolDefinition]],
                              field: str) -> Assertion[Reading]:
    def assertion(dont_care_reading: Reading) -> bool:
        fields = [sorted(tool.properties) for tools in offered.taken for tool in tools]

        if not fields or any(field in properties for properties in fields):
            raise AssertionError(
                f"Expected no tool the model was offered to ask for [{field}], and "
                f"they asked for {fields}.")

        return True

    return assertion


def _claims_no_cause_reached() -> Assertion[Reading]:
    """Neither a chain that reaches a cause nor one resting on a reading nothing
    ran - so nothing on the page claims a cause the root cause denies."""
    def assertion(reading: Reading) -> bool:
        answer, _ = reading

        if answer.reaches_a_cause or answer.cause_rests_on_an_unrun_reading is not False:
            raise AssertionError(
                f"Expected an answer the investigation named no cause for to claim no "
                f"chain reaching one and none resting on a reading, got "
                f"[{answer.reaches_a_cause}] and [{answer.cause_rests_on_an_unrun_reading}].")

        return True

    return assertion


def _answered_with(field: str, expected: str) -> Assertion[Reading]:
    def assertion(reading: Reading) -> bool:
        answer, _ = reading

        if getattr(answer, field) != expected:
            raise AssertionError(
                f"Expected [{field}] to be [{expected}], got [{getattr(answer, field)}].")

        return True

    return assertion


def _what_went_well_read(expected: list[str]) -> Assertion[Reading]:
    def assertion(reading: Reading) -> bool:
        answer, _ = reading
        read = answer.lessons.went_well if answer.lessons is not None else None

        if read != expected:
            raise AssertionError(f"Expected what went well to read {expected}, got {read}.")

        return True

    return assertion


def _answered_nothing() -> Assertion[Reading]:
    """An answer in a shape nothing can be read out of.

    Empty rather than absent: the caller writes a document either way, and what
    it writes is a document that says on its face that it is partial.
    """
    def assertion(reading: Reading) -> bool:
        answer, _ = reading

        if answer != SubmittedPostmortem():
            raise AssertionError(
                f"Expected nothing to be read out of an answer in the wrong shape, "
                f"got {answer}.")

        return True

    return assertion


def _found_no_fault() -> Assertion[Reading]:
    def assertion(reading: Reading) -> bool:
        _, faults = reading

        if faults:
            raise AssertionError(
                f"Expected an answer nothing was wrong with, got {faults}.")

        return True

    return assertion


def _found_a_fault() -> Assertion[Reading]:
    def assertion(reading: Reading) -> bool:
        _, faults = reading

        if not faults:
            raise AssertionError(
                "Expected the faults to come back with the answer, so the caller "
                "can mark the document partial, and none did.")

        return True

    return assertion


def _the_last_correction_named(asks: Kept[Transcript], expected: str) -> Assertion[Reading]:
    def assertion(dont_care_reading: Reading) -> bool:
        said = _what_was_said_to_the_model(asks.taken[-1])

        if expected not in said:
            raise AssertionError(
                f"Expected the last correction to name [{expected}], and it did not: {said}.")

        return True

    return assertion


def _the_correction_named(asks: Kept[Transcript], expected: str) -> Assertion[Reading]:
    def assertion(dont_care_reading: Reading) -> bool:
        said = _what_was_said_to_the_model(asks.taken[1])

        if expected not in said:
            raise AssertionError(
                f"Expected the correction to name [{expected}], and it did not: {said}.")

        return True

    return assertion


def _the_correction_on_ask_named(asks: Kept[Transcript],
                                 ask: int,
                                 expected: str) -> Assertion[Reading]:
    """What the model was told on its `ask`th time of asking, counted from 1 -
    only what that ask added, since its transcript still carries every
    correction before it."""
    def assertion(dont_care_reading: Reading) -> bool:
        said = _what_was_said_to_the_model(asks.taken[ask - 1][-1:])

        if expected not in said:
            raise AssertionError(
                f"Expected ask [{ask}] to name [{expected}], and it did not: {said}.")

        return True

    return assertion


def _the_correction_answered_the_call_it_rejected(
        asks: Kept[Transcript]) -> Assertion[Reading]:
    """The correction is the tool call's result, not a second conversation.

    A provider that has seen a tool call expects its result next, and the result
    is where a rejection belongs: the model sees what it submitted, is told what
    was wrong with it, and answers in the same exchange - rather than being
    handed the whole incident again as though it had never answered at all.
    """
    def assertion(dont_care_reading: Reading) -> bool:
        submitted = [entry for entry in asks.taken[1] if isinstance(entry, Turn)]
        answered = [entry for entry in asks.taken[1] if isinstance(entry, ToolResults)]

        if not submitted or not answered:
            raise AssertionError(
                "Expected the correction to carry the model's own turn and the "
                "result of the call it made, and it carried "
                f"{len(submitted)} turn(s) and {len(answered)} result(s).")

        expected_call_id = submitted[0].tool_calls[0].id
        answering = [result.call_id for result in answered[0].results]

        if answering != [expected_call_id]:
            raise AssertionError(
                f"Expected the result to answer call [{expected_call_id}], "
                f"got {answering}.")

        if not answered[0].results[0].failed:
            raise AssertionError(
                "Expected the rejected submission to be marked failed, so the model "
                "reads it as something to fix rather than as evidence.")

        return True

    return assertion


def _the_last_ask_was_a_fresh_one(asks: Kept[Transcript]) -> Assertion[Reading]:
    """The last ask put from the start, carrying no turn and no tool result."""
    def assertion(dont_care_reading: Reading) -> bool:
        carried = [entry for entry in asks.taken[-1]
                   if isinstance(entry, Turn | ToolResults)]

        if carried:
            raise AssertionError(
                f"Expected the last ask to be a fresh one, and it carried {carried}.")

        return True

    return assertion


def _the_correction_was_a_fresh_ask(asks: Kept[Transcript]) -> Assertion[Reading]:
    """Asked again from the start, with nothing to answer.

    The counterpart to `_the_correction_answered_the_call_it_rejected`: where
    there was a submission the correction rides on it, and where there was none
    it cannot.
    """
    def assertion(dont_care_reading: Reading) -> bool:
        carried = [entry for entry in asks.taken[1]
                   if isinstance(entry, Turn | ToolResults)]

        if carried:
            raise AssertionError(
                f"Expected the correction to be a fresh ask, and it carried {carried}.")

        return True

    return assertion


def _what_was_said_to_the_model(transcript: Transcript) -> str:
    """Everything Argus put in front of the model, in whichever shape.

    A fault can arrive as prose in an ask or as the result of the tool call it
    rejects. Which one it is is the code's business; this file asserts that
    choice separately, and here only cares that the model was told.
    """
    said: list[str] = []

    for entry in transcript:
        if isinstance(entry, Ask):
            said.append(entry.text)
        elif isinstance(entry, ToolResults):
            said.extend(result.content for result in entry.results)

    return "\n".join(said)


@pytest.mark.unit
def test_a_claim_the_judge_flags_is_sent_back_naming_it() -> None:
    # Sent back like any fault the checks find: once, quoting the claim. How
    # the fault is worded is the judge's own suite's subject.
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(an_answer(root_cause=A_ROOT_CAUSE_CLAIMING_IT),
                                                 an_answer(root_cause=A_GROUNDED_ROOT_CAUSE),
                                                 recording_into=asks),
            a_judge := a_model_answering_in_turn(_flagging(SOME_UNGROUNDED_CLAIM), _flagging())
        ) \
        .when(
            lambda: answer_worth_writing(a_model, an_evidence_bundle(), a_measured_incident(),
                                         judge=a_judge)
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_correction_named(asks, SOME_UNGROUNDED_CLAIM),
                _answered_with(ROOT_CAUSE_FIELD, A_GROUNDED_ROOT_CAUSE),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_the_judge_reads_no_answer_the_checks_sent_back() -> None:
    # The checks' faults are cheaper and certain; an answer they refuse is
    # rewritten before anyone reads its meaning.
    judged: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(an_answer_without(ROOT_CAUSE_FIELD),
                                                 an_answer(root_cause=A_GROUNDED_ROOT_CAUSE)),
            a_judge := a_model_answering_in_turn(_flagging(), recording_into=judged)
        ) \
        .when(
            lambda: answer_worth_writing(a_model, an_evidence_bundle(), a_measured_incident(),
                                         judge=a_judge)
        ) \
        .then(
            _the_judge_read_once(judged, [A_GROUNDED_ROOT_CAUSE])
        )


@pytest.mark.unit
def test_a_claim_flagged_again_after_it_was_sent_back_is_kept_and_logged(
    caplog: pytest.LogCaptureFixture
) -> None:
    # Told once, written again: the answer is kept, as one twice wrong in a way
    # it was told of is. The page has no line for meaning, so the flag is said
    # where whoever watches the model reads.
    caplog.set_level(logging.WARNING, logger=THE_CONVERSATION_S_LOGGER)
    some_evidence = an_evidence_bundle()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(an_answer(root_cause=A_ROOT_CAUSE_CLAIMING_IT),
                                                 an_answer(root_cause=A_ROOT_CAUSE_CLAIMING_IT)),
            a_judge := a_model_answering_in_turn(_flagging(SOME_UNGROUNDED_CLAIM),
                                                 _flagging(SOME_UNGROUNDED_CLAIM))
        ) \
        .when(
            lambda: answer_worth_writing(a_model, some_evidence, a_measured_incident(),
                                         judge=a_judge)
        ) \
        .then(
            all_of(
                _answered_with(ROOT_CAUSE_FIELD, A_ROOT_CAUSE_CLAIMING_IT),
                _found_no_fault(),
                _the_claim_was_logged(caplog, some_evidence.incident_id)
            )
        )


@pytest.mark.unit
def test_a_third_answer_flagged_again_is_kept_and_logged(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The checks refused the first answer, the judge the second: each told
    # once, the third is the last, and a flag on it is logged rather than sent.
    caplog.set_level(logging.WARNING, logger=THE_CONVERSATION_S_LOGGER)
    some_evidence = an_evidence_bundle()
    asks: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(an_answer_without(ROOT_CAUSE_FIELD),
                                                 an_answer(root_cause=A_ROOT_CAUSE_CLAIMING_IT),
                                                 an_answer(root_cause=A_ROOT_CAUSE_CLAIMING_IT),
                                                 recording_into=asks),
            a_judge := a_model_answering_in_turn(_flagging(SOME_UNGROUNDED_CLAIM),
                                                 _flagging(SOME_UNGROUNDED_CLAIM))
        ) \
        .when(
            lambda: answer_worth_writing(a_model, some_evidence, a_measured_incident(),
                                         judge=a_judge)
        ) \
        .then(
            all_of(
                _was_asked(asks, times=3),
                _the_correction_on_ask_named(asks, 3, SOME_UNGROUNDED_CLAIM),
                _answered_with(ROOT_CAUSE_FIELD, A_ROOT_CAUSE_CLAIMING_IT),
                _found_no_fault(),
                _the_claim_was_logged(caplog, some_evidence.incident_id)
            )
        )


@pytest.mark.unit
def test_the_judge_is_not_shown_what_code_says_in_the_record_s_words() -> None:
    # A rule-out resting on Argus's own read, and an item timed by a row, are
    # said by code from the record: the model's words for them are gone from
    # the page, and judged they would be sent back for nothing. The step they
    # sit beside is shown, so an answer shown not at all would not pass.
    judged: Kept[Transcript] = Kept()
    some_item_code_replaces = "The Investigator Agent read the flags and much else besides."
    the_flags_read = a_timeline_entry(READ_NO_FLAG_CHANGES, at=DONT_CARE_READ_AT,
                                      who=ARGUS, kind=FLAG_CHANGES_RETRIEVED,
                                      rules_out=NO_FLAG_CHANGE_BY_ANYONE_ELSE)

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(an_answer(
                causal_chain=[{STEP_FIELD: DONT_CARE_STEP, CITES_FIELD: [THE_FIRST_ROW],
                               RULED_OUT_FIELD: [{WHAT_FIELD: DONT_CARE_WORDS,
                                                  CITES_FIELD: [THE_FIRST_ROW]}]}],
                lessons={WENT_WELL_FIELD: [{ITEM_FIELD: some_item_code_replaces,
                                            TIMED_BY_FIELD: THE_FIRST_ROW}]})),
            a_judge := a_model_answering_in_turn(_flagging(), recording_into=judged)
        ) \
        .when(
            lambda: answer_worth_writing(a_model, an_evidence_bundle(timeline=[the_flags_read]),
                                         a_measured_incident(), judge=a_judge)
        ) \
        .then(
            _the_judge_read_places(judged,
                                   shown=[f"{CAUSAL_CHAIN_FIELD} 1: {DONT_CARE_STEP}"],
                                   not_shown=[f"{CAUSAL_CHAIN_FIELD} 1 {RULED_OUT_FIELD} 1",
                                              some_item_code_replaces])
        )


@pytest.mark.unit
def test_the_judge_is_told_where_a_went_wrong_item_sits_is_judged() -> None:
    # Told a lesson's verdict is not judged and nothing more - and given one
    # job in its opening - the judge let a factor said again under went_wrong
    # stand in 3 draws of 5. Told this and the job together, in none.
    judged: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(an_answer()),
            a_judge := a_model_answering_in_turn(_flagging(), recording_into=judged)
        ) \
        .when(
            lambda: answer_worth_writing(a_model, an_evidence_bundle(), a_measured_incident(),
                                         judge=a_judge)
        ) \
        .then(
            _the_judge_read_places(judged,
                                   shown=[f"whether a {WENT_WRONG_FIELD} item is one its field "
                                          "excludes"],
                                   not_shown=[])
        )


@pytest.mark.unit
def test_the_judge_is_shown_a_root_cause_resting_on_an_unrun_reading_as_the_page_says_it() -> None:
    # The page says beside the model's root cause that it rests on a reading
    # nothing ran. Shown the model's words alone, the judge flagged as said
    # flat a cause the page calls unverified.
    judged: Kept[Transcript] = Kept()
    some_root_cause = "The average divides by this month's purchases, which can be none."
    its_label = "F1"

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(an_answer(
                root_cause=some_root_cause, cause_rests_on_an_unrun_reading=True,
                causal_chain=[{STEP_FIELD: DONT_CARE_STEP,
                               CITES_FIELD: [THE_FIRST_ROW, its_label]}])),
            a_judge := a_model_answering_in_turn(_flagging(), recording_into=judged)
        ) \
        .when(
            lambda: answer_worth_writing(a_model,
                                         an_evidence_bundle(fix_explanation=DONT_CARE_WORDS),
                                         a_measured_incident(), judge=a_judge)
        ) \
        .then(
            _the_judge_read_places(judged,
                                   shown=[f"{ROOT_CAUSE_FIELD}: {some_root_cause} It rests on "
                                          f"{its_label}, a reading of the source nothing ran, "
                                          f"so it is unverified."],
                                   not_shown=[])
        )


@pytest.mark.unit
def test_the_judge_is_shown_each_step_with_what_it_cites() -> None:
    # The page shows each step beside its citations, each as its row says it,
    # and a reading of the source under the heading saying it is Code-Fix's
    # and nothing ran it. Shown the step alone, or beside bare labels, the
    # judge flagged it as said flat. The heading only, not what the writer is
    # told beneath it: beside a claim, that argues the flag it answers.
    judged: Kept[Transcript] = Kept()
    some_step = "The average divides by this month's purchases."
    its_label = "F1"
    # What the headings the record lists the two beneath say they are, with
    # no pull request opened. MIRRORED FROM THE RECORD'S HEADINGS - NOT
    # ARBITRARY VALUES.
    the_narration_s_heading = "What Argus did, in order"
    the_reading_s_heading = ("What Code-Fix read in the source, in Code-Fix's words - nothing "
                             "ran to check it")

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(an_answer(
                cause_rests_on_an_unrun_reading=True,
                causal_chain=[{STEP_FIELD: some_step, CITES_FIELD: [THE_FIRST_ROW, its_label]}])),
            a_judge := a_model_answering_in_turn(_flagging(), recording_into=judged)
        ) \
        .when(
            lambda: answer_worth_writing(a_model,
                                         an_evidence_bundle(fix_explanation=DONT_CARE_WORDS),
                                         a_measured_incident(), judge=a_judge)
        ) \
        .then(
            _the_judge_read_places(judged,
                                   shown=[f'{CAUSAL_CHAIN_FIELD} 1: {some_step} (cites '
                                          f'{THE_FIRST_ROW}, under "{the_narration_s_heading}"; '
                                          f'{its_label}, under "{the_reading_s_heading}")'],
                                   not_shown=[])
        )


@pytest.mark.unit
def test_the_judge_is_shown_each_rule_out_the_model_says_with_what_it_cites() -> None:
    # A rule-out the record does not say is the model's, and the page shows
    # it beside its citations as it does a step.
    judged: Kept[Transcript] = Kept()
    some_rule_out = "Nothing else changed in the window."
    # MIRRORED FROM THE RECORD'S HEADINGS - NOT AN ARBITRARY VALUE.
    the_narration_s_heading = "What Argus did, in order"

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(an_answer(
                causal_chain=[{STEP_FIELD: DONT_CARE_STEP, CITES_FIELD: [THE_FIRST_ROW],
                               RULED_OUT_FIELD: [{WHAT_FIELD: some_rule_out,
                                                  CITES_FIELD: [THE_FIRST_ROW]}]}])),
            a_judge := a_model_answering_in_turn(_flagging(), recording_into=judged)
        ) \
        .when(
            lambda: answer_worth_writing(a_model, an_evidence_bundle(), a_measured_incident(),
                                         judge=a_judge)
        ) \
        .then(
            _the_judge_read_places(judged,
                                   shown=[f"{CAUSAL_CHAIN_FIELD} 1 {RULED_OUT_FIELD} 1: "
                                          f'{some_rule_out} (cites {THE_FIRST_ROW}, under '
                                          f'"{the_narration_s_heading}")'],
                                   not_shown=[])
        )


@pytest.mark.unit
def test_a_rule_out_resting_on_argus_s_read_arrives_said_by_the_record() -> None:
    # Said by code and then written in with the figures: marked all the way to
    # the answer kept, so the page cites its rows by label alone.
    the_changes_read = a_timeline_entry(READ_NO_CHANGES, at=DONT_CARE_READ_AT,
                                        who=INVESTIGATOR, kind=CHANGES_RETRIEVED,
                                        rules_out=NO_CHANGE_OF_ANY_KIND)

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(an_answer(
                causal_chain=[{STEP_FIELD: DONT_CARE_STEP, CITES_FIELD: [THE_FIRST_ROW],
                               RULED_OUT_FIELD: [{WHAT_FIELD: DONT_CARE_WORDS,
                                                  CITES_FIELD: [THE_FIRST_ROW]}]}]))
        ) \
        .when(
            lambda: answer_worth_writing(a_model,
                                         an_evidence_bundle(timeline=[the_changes_read]),
                                         a_measured_incident())
        ) \
        .then(
            _its_rule_out_said_by_the_record()
        )


@pytest.mark.unit
def test_a_figure_in_digits_in_an_item_said_as_its_row_is_not_sent_back() -> None:
    # Code says the item as its row, so the model's words in it reach no
    # reader: sent back for a pull request's number in digits there, a
    # write-up spent a turn on a sentence the document never printed.
    asks: Kept[Transcript] = Kept()
    the_alert = parse_iso("2026-09-02T12:00:00Z")
    the_proposal = a_timeline_entry(PROPOSED_A_DRAFT, at=the_alert + SOME_WAIT, who=CODE_FIX)

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(
                an_answer(lessons={WENT_WELL_FIELD: [
                    {ITEM_FIELD: f"The Code-Fix Agent proposed draft pull request "
                                 f"{A_FIGURE_IN_DIGITS}.",
                     TIMED_BY_FIELD: THE_FIRST_ROW}]}),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model, an_evidence_bundle(alerted_at=the_alert, timeline=[the_proposal]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks),
                _found_no_fault()
            )
        )


@pytest.mark.unit
def test_a_rule_out_after_one_code_drops_is_still_held_to_the_rules() -> None:
    # Code drops the first rule-out, resting on the metrics alone, and says
    # the third by the record; the second is the model's own and reaches the
    # page as written. Counted on the answer after the drop, the third's place
    # is the second's - and a size said in words there went unrefused.
    asks: Kept[Transcript] = Kept()
    the_metrics_read = a_timeline_entry(READ_THE_METRICS, at=DONT_CARE_READ_AT,
                                        who=INVESTIGATOR, kind=METRICS_RETRIEVED)
    the_restart = a_timeline_entry(RESTARTED_THE_REPLICAS, at=DONT_CARE_READ_AT,
                                   who=MITIGATION, kind=ACTION_TAKEN)
    the_changes_read = a_timeline_entry(READ_NO_CHANGES, at=DONT_CARE_READ_AT,
                                        who=INVESTIGATOR, kind=CHANGES_RETRIEVED,
                                        rules_out=NO_CHANGE_OF_ANY_KIND)
    the_metrics, the_action, the_read = "T1", "T2", "T3"

    def rule_outs_saying(own_words: str) -> dict[str, object]:
        return {STEP_FIELD: DONT_CARE_STEP, CITES_FIELD: [the_read],
                RULED_OUT_FIELD: [{WHAT_FIELD: DONT_CARE_WORDS, CITES_FIELD: [the_metrics]},
                                  {WHAT_FIELD: own_words, CITES_FIELD: [the_action]},
                                  {WHAT_FIELD: DONT_CARE_WORDS, CITES_FIELD: [the_read]}]}

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(
                an_answer(causal_chain=[rule_outs_saying(
                    f"A second restart: none in {A_SIZE_IN_WORDS} after it.")]),
                an_answer(causal_chain=[rule_outs_saying(
                    "A second restart: none came after it.")]),
                recording_into=asks)
        ) \
        .when(
            lambda: answer_worth_writing(
                a_model,
                an_evidence_bundle(timeline=[the_metrics_read, the_restart, the_changes_read]),
                a_measured_incident())
        ) \
        .then(
            all_of(
                _was_asked(asks, times=2),
                _the_last_correction_named(asks, f"[{A_SIZE_IN_WORDS}]")
            )
        )


def _flagging(*quotes: str) -> dict[str, list[dict[str, object]]]:
    """A judge's answer flagging each of `quotes`, against no row."""
    return {FLAGS_FIELD: [{QUOTE_FIELD: quote, ROWS_FIELD: [], WHY_FIELD: SOME_REASON_IT_IS_NOT}
                          for quote in quotes]}


def _the_claim_was_logged(caplog: pytest.LogCaptureFixture,
                          incident_id: str) -> Assertion[Reading]:
    """One warning for the one flag on the answer kept, saying where it is."""
    return one_record_was_logged(caplog, THE_CONVERSATION_S_LOGGER, logging.WARNING,
                                 "postmortem claim not grounded",
                                 values={"incident_id": incident_id,
                                         "fields": [ROOT_CAUSE_FIELD],
                                         "quote": SOME_UNGROUNDED_CLAIM,
                                         "rows": [],
                                         "why": SOME_REASON_IT_IS_NOT})


def _the_judge_read_once(judged: Kept[Transcript], expected: list[str]) -> Assertion[Reading]:
    """That the judge was asked once, and of an answer saying each of these."""
    def assertion(dont_care_reading: Reading) -> bool:
        said = [_what_was_said_to_the_model(transcript) for transcript in judged.taken]
        if len(said) != 1 or any(text not in said[0] for text in expected):
            raise AssertionError(
                f"Expected the judge asked once, of an answer saying {expected}; it was "
                f"asked {len(said)} times: {said}.")

        return True

    return assertion


def _the_judge_read_places(judged: Kept[Transcript], *, shown: list[str],
                           not_shown: list[str]) -> Assertion[Reading]:
    def assertion(dont_care_reading: Reading) -> bool:
        said = "\n".join(_what_was_said_to_the_model(transcript) for transcript in judged.taken)
        missing = [text for text in shown if text not in said]
        present = [text for text in not_shown if text in said]
        if not judged.taken or missing or present:
            raise AssertionError(
                f"Expected the judge shown {shown} and not {not_shown}; {missing} were "
                f"missing and {present} were shown, in {judged.taken}.")

        return True

    return assertion


def _its_rule_out_said_by_the_record() -> Assertion[Reading]:
    def assertion(reading: Reading) -> bool:
        answer, _ = reading
        ruled_out = answer.causal_chain[0].ruled_out if answer.causal_chain else []

        if [entry.by_the_record for entry in ruled_out] != [True]:
            raise AssertionError(
                f"Expected one rule-out, said by the record, got {ruled_out}.")

        return True

    return assertion


def _lowered(line: str) -> str:
    """A line as it goes on mid-sentence: its opening lowered, the rest as written."""
    return line[:1].lower() + line[1:]
