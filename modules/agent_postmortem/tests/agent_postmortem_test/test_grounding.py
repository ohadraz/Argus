"""A second model reading an answer against the record it was written from.

No code check can tell a claim the record holds from one it does not: "the
flag was never read" is a sentence about meaning. So a judge is asked, and
what it says is held to what code can check - a flag quoting words the answer
does not hold, or citing a row the record does not have, is the judge being
wrong, and is dropped.

The judge says of every claim either where the record supports it or that it
does not: made to look for the support, it stops flagging what it skimmed
past. Only the flags are kept; the support is the judge's working.

A judge that does not answer judges nothing, and says so in the log: the
answer it was to judge is kept either way.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from agent_postmortem.grounding import (
    FLAGS_FIELD,
    JUDGE_BRIEF,
    JUDGE_TOOL_NAME,
    NO_REASON_GIVEN,
    QUOTE_FIELD,
    ROWS_FIELD,
    SUPPORTED_FIELD,
    WHY_FIELD,
    Flag,
    faults_of,
    flags_on,
    judge_policy,
)
from agent_postmortem.prompting import WENT_WRONG_DESCRIPTION, WENT_WRONG_FIELD
from argus_core.llm import LLMClient, ModelRefused, ModelUnavailable, RequestRejected
from argus_core.models import Ask, Effort, ModelPolicy, ToolDefinition, Transcript, Turn
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    all_of,
    one_record_was_logged,
    the_answer_was,
)

from agent_postmortem_test.framework.builders import a_model_answering_in_turn

SOME_ROW = "T8"
SOME_OTHER_ROW = "T9"
# A log group's label, as `log_groups` mints one: G and four lower-case hex.
SOME_LOG_GROUP = "G7e5d"
SOME_ROWS = frozenset({SOME_ROW, SOME_OTHER_ROW, SOME_LOG_GROUP})
A_ROW_THE_RECORD_DOES_NOT_HAVE = "T99"
# A figure's name, as the record prints it after the figure: a row's first
# figure is named by the row's label and a 1.
SOME_FIGURE = f"{SOME_ROW}.1"
A_FIGURE_THE_RECORD_DOES_NOT_HAVE = "A4"
# A line with no label, named as the brief tells the judge to: in its words.
SOME_LINE_IN_ITS_OWN_WORDS = "Actions it took: none"

SOME_FIELD = "root_cause"
SOME_OTHER_FIELD = "still_at_risk"
SOME_CLAIM = "older flag changes were not read"
SOME_OTHER_CLAIM = "Nothing else is at risk"
SOME_ANSWER = {SOME_FIELD: f"The cause is settled, and {SOME_CLAIM}.",
               SOME_OTHER_FIELD: f"{SOME_OTHER_CLAIM}."}
SOME_RECORD = (f"[{SOME_ROW}] Read the flag provider's history - 0 {{{SOME_FIGURE}}} flag "
               f"changes, the day before.")
SOME_REASON = "the flag provider's history was read for the whole day before"
# Reasons a judge has given that say nothing a writer can act on - the last as
# a pilot judge wrote one.
AN_EMPTY_REASON = ""
A_REASON_OF_ONLY_SPACING = " \n "
A_ONE_WORD_REASON = "x"
SOME_SCOPE = ("Placeholders in braces are filled in by code and are not judged.",
              "Words said to be another agent's are grounded if that agent said them.")

DONT_CARE_REASON = "dont care"
THE_JUDGE_S_LOGGER = "agent_postmortem.grounding"
DID_NOT_ANSWER = "grounding judge did not answer"


@pytest.mark.unit
@pytest.mark.parametrize("row_as_cited", [SOME_ROW, f"[{SOME_ROW}]", SOME_ROW.lower()],
                         ids=["as-labelled", "as-the-brief-prints-it", "lower-case"])
def test_a_flag_quoting_the_answer_against_rows_the_record_holds_is_kept(
        row_as_cited: str) -> None:
    # The brief prints a row as "[T8]", and a judge copying it so cited the
    # row all the same.
    Scenario() \
        .given(
            a_judge := _a_judge_flagging(_a_flag(SOME_CLAIM, [row_as_cited]))
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _flagged([Flag(quote=SOME_CLAIM, rows=(SOME_ROW,), why=SOME_REASON,
                           fields=(SOME_FIELD,))])
        )


@pytest.mark.unit
@pytest.mark.parametrize("row_as_cited", [SOME_LOG_GROUP, f"[{SOME_LOG_GROUP}]",
                                          SOME_LOG_GROUP.upper()],
                         ids=["as-labelled", "as-the-brief-prints-it", "upper-case"])
def test_a_flag_citing_a_label_with_lower_case_letters_is_kept_as_the_record_spells_it(
        row_as_cited: str) -> None:
    # A log group's label carries lower-case letters, and a judge writing it
    # in capitals cited the row all the same. Kept as the record spells it, so
    # the flag names a row the record has.
    Scenario() \
        .given(
            a_judge := _a_judge_flagging(_a_flag(SOME_CLAIM, [row_as_cited]))
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _flagged([Flag(quote=SOME_CLAIM, rows=(SOME_LOG_GROUP,), why=SOME_REASON,
                           fields=(SOME_FIELD,))])
        )


@pytest.mark.unit
def test_a_flag_citing_no_row_is_kept() -> None:
    # A claim no row holds at all is the commonest ungrounded claim there is,
    # and has nothing to cite.
    Scenario() \
        .given(
            a_judge := _a_judge_flagging(_a_flag(SOME_CLAIM, []))
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _flagged([Flag(quote=SOME_CLAIM, rows=(), why=SOME_REASON, fields=(SOME_FIELD,))])
        )


@pytest.mark.unit
def test_a_flag_quoting_words_the_answer_does_not_hold_is_dropped() -> None:
    # Sent back, it would ask the writer to correct a sentence it never wrote.
    Scenario() \
        .given(
            a_judge := _a_judge_flagging(_a_flag("the flag was switched by hand", [SOME_ROW]))
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _flagged([])
        )


@pytest.mark.unit
@pytest.mark.parametrize("nothing", ["", " \n "], ids=["empty", "whitespace"])
def test_a_flag_quoting_nothing_is_dropped(nothing: str) -> None:
    # Every field holds the empty string, so a flag quoting it would be sent
    # back against the whole answer.
    Scenario() \
        .given(
            a_judge := _a_judge_flagging(_a_flag(nothing, [SOME_ROW]))
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _flagged([])
        )


@pytest.mark.unit
@pytest.mark.parametrize("figure_as_cited", [SOME_FIGURE, f"{{{SOME_FIGURE}}}",
                                             SOME_FIGURE.lower()],
                         ids=["as-named", "as-the-brief-prints-it", "lower-case"])
def test_a_flag_citing_a_figure_the_record_names_is_kept(figure_as_cited: str) -> None:
    # A wrong figure is the flag most worth sending back, and it cites the
    # figure's name, which is no row.
    Scenario() \
        .given(
            a_judge := _a_judge_flagging(_a_flag(SOME_CLAIM, [figure_as_cited]))
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _flagged([Flag(quote=SOME_CLAIM, rows=(SOME_FIGURE,), why=SOME_REASON,
                           fields=(SOME_FIELD,))])
        )


@pytest.mark.unit
def test_a_flag_citing_a_line_in_its_own_words_is_kept_without_it() -> None:
    # The brief tells the judge to name a line with no label by its words, so
    # such a citation is no invention; it names no row, and is not one.
    Scenario() \
        .given(
            a_judge := _a_judge_flagging(
                _a_flag(SOME_CLAIM, [SOME_ROW, SOME_LINE_IN_ITS_OWN_WORDS]))
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _flagged([Flag(quote=SOME_CLAIM, rows=(SOME_ROW,), why=SOME_REASON,
                           fields=(SOME_FIELD,))])
        )


@pytest.mark.unit
@pytest.mark.parametrize("nobody_s", [A_ROW_THE_RECORD_DOES_NOT_HAVE,
                                      A_FIGURE_THE_RECORD_DOES_NOT_HAVE],
                         ids=["a-row", "a-figure"])
def test_a_flag_citing_a_label_the_record_does_not_have_is_dropped(nobody_s: str) -> None:
    # A contradiction resting on a row or a figure nobody recorded is the
    # judge's own ungrounded claim.
    Scenario() \
        .given(
            a_judge := _a_judge_flagging(_a_flag(SOME_CLAIM, [SOME_ROW, nobody_s]))
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _flagged([])
        )


@pytest.mark.unit
@pytest.mark.parametrize("quoted", [
    SOME_CLAIM.upper(),
    SOME_CLAIM.replace(" ", "  \n "),
    "older flag changes were ‘not’ read",
    "older flag changes — were not read"
], ids=["case", "spacing", "curly-quotes", "dash"])
def test_a_quote_differing_only_in_case_spacing_quotes_or_dashes_is_the_answer_s(
        quoted: str) -> None:
    # A judge that copied a quote with its own typography quoted the answer
    # all the same, and a true flag lost over a curly quote is a claim nobody
    # corrects. Quote marks and dashes are left out of the match altogether,
    # not only made alike: a judge drops them as often as it changes them.
    an_answer_quoting_and_dashing = {
        SOME_FIELD: "The cause is settled, and older flag changes were 'not' read.",
        SOME_OTHER_FIELD: "Older flag changes - were not read."}

    Scenario() \
        .given(
            a_judge := _a_judge_flagging(_a_flag(quoted, [SOME_ROW]))
        ) \
        .when(
            lambda: _flags_from(a_judge, answer=an_answer_quoting_and_dashing)
        ) \
        .then(
            _flagged_once_quoting(quoted)
        )


@pytest.mark.unit
def test_a_quote_more_than_one_field_holds_names_every_one_of_them() -> None:
    # Which field a claim is in is worked out by code: asked of the judge, it
    # is one more thing for the judge to get wrong.
    an_answer_saying_it_twice = {SOME_FIELD: f"The cause is settled, and {SOME_CLAIM}.",
                                 SOME_OTHER_FIELD: f"Still at risk, since {SOME_CLAIM}."}

    Scenario() \
        .given(
            a_judge := _a_judge_flagging(_a_flag(SOME_CLAIM, [SOME_ROW]))
        ) \
        .when(
            lambda: _flags_from(a_judge, answer=an_answer_saying_it_twice)
        ) \
        .then(
            _flagged([Flag(quote=SOME_CLAIM, rows=(SOME_ROW,), why=SOME_REASON,
                           fields=(SOME_FIELD, SOME_OTHER_FIELD))])
        )


@pytest.mark.unit
def test_an_answer_the_judge_finds_nothing_in_has_no_flags() -> None:
    Scenario() \
        .given(
            a_judge := _a_judge_flagging()
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _flagged([])
        )


@pytest.mark.unit
def test_a_claim_the_judge_found_support_for_is_not_flagged() -> None:
    # The support is the judge's working, said so that it looks for it: what
    # it found supported is not a fault, whatever rows it names.
    Scenario() \
        .given(
            a_judge := a_model_answering_in_turn({
                SUPPORTED_FIELD: [_supported(SOME_CLAIM, [SOME_ROW]),
                                  _supported(SOME_OTHER_CLAIM, [A_ROW_THE_RECORD_DOES_NOT_HAVE])],
                FLAGS_FIELD: []})
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _flagged([])
        )


@pytest.mark.unit
def test_the_judge_is_asked_with_the_record_the_answer_and_what_is_not_judged() -> None:
    # The record verbatim, because a judge reading a summary of it would be
    # judging against something nobody wrote. Each field by name, because
    # the flag is matched back to the field that holds it.
    asked: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_judge := a_model_answering_in_turn(_judged(), recording_into=asked)
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _asked_with(asked, [SOME_RECORD, *SOME_ANSWER, *SOME_ANSWER.values(), *SOME_SCOPE,
                                JUDGE_TOOL_NAME])
        )


@pytest.mark.unit
def test_the_judge_is_offered_its_one_tool() -> None:
    offered: Kept[list[ToolDefinition]] = Kept()

    Scenario() \
        .given(
            a_judge := a_model_answering_in_turn(_judged(), offered_tools=offered)
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _offered_only(offered, JUDGE_TOOL_NAME)
        )


@pytest.mark.unit
def test_the_judge_must_say_of_every_claim_where_it_is_supported_or_flag_it() -> None:
    # A judge free to name only what it doubts flags what it skimmed past:
    # asked for the support of every claim, it looks for it first.
    offered: Kept[list[ToolDefinition]] = Kept()

    Scenario() \
        .given(
            a_judge := a_model_answering_in_turn(_judged(), offered_tools=offered)
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _offered_requiring(offered, [SUPPORTED_FIELD, FLAGS_FIELD])
        )


@pytest.mark.unit
def test_the_judge_is_told_its_second_job_is_what_went_wrong_excludes() -> None:
    # Handed went_wrong's exclusions as one paragraph more and nothing else,
    # the judge flagged a factor said again under went_wrong in 2 draws of 5:
    # its opening named one job, and the ask said a lesson's verdict is not
    # judged. Named as a job, it flagged it in every draw.
    Scenario() \
        .when(
            lambda: JUDGE_BRIEF
        ) \
        .then(
            _says(f"and each {WENT_WRONG_FIELD} item that its field excludes")
        )


@pytest.mark.unit
def test_the_judge_holds_what_went_wrong_to_the_field_s_own_description() -> None:
    # The writer and the judge read one text, so neither can be told a rule
    # the other was not.
    Scenario() \
        .when(
            lambda: JUDGE_BRIEF
        ) \
        .then(
            _says(f"\"{WENT_WRONG_DESCRIPTION}\"")
        )


@pytest.mark.unit
def test_the_judge_is_told_a_repeat_is_the_same_point_not_a_lesson_from_the_same_facts() -> None:
    # Told only that a factor said again does not belong, a judge flagged a
    # mitigation that left the cache free to go stale as the root cause again.
    Scenario() \
        .when(
            lambda: JUDGE_BRIEF
        ) \
        .then(
            _says("Repeating is saying the same point again, not drawing a different lesson "
                  "from the same facts.")
        )


@pytest.mark.unit
def test_the_judge_flags_two_things_said_to_be_the_same_that_differ_however_little() -> None:
    # Told only to flag a count or an all the record contradicts, a judge read
    # "the same stretch" said of errors logged a minute before the flag was on
    # for every request, saw the minute, and passed it as close enough. Told
    # this, it flagged the sentence in 5 draws of 5, and nothing else new in
    # five other write-ups.
    Scenario() \
        .when(
            lambda: JUDGE_BRIEF
        ) \
        .then(
            _says("two things said to be the same - the same stretch, the same minutes, the "
                  "same count - where the record shows them differ, however little")
        )


@pytest.mark.unit
def test_the_judge_flags_nobody_paged_said_as_nobody_knowing_or_taking_part() -> None:
    # A write-up said "no person was engaged" of an incident Argus had posted
    # about in Slack, where the record held only that nobody was paged. The
    # judge passed it in 1 call of 2.
    Scenario() \
        .when(
            lambda: JUDGE_BRIEF
        ) \
        .then(
            _says("that no person knew of the incident or took part in it, where the record "
                  "shows only that nobody was paged")
        )


@pytest.mark.unit
def test_the_judge_gives_a_flag_s_reason_before_its_rows() -> None:
    # A model writes a tool's fields in the order the schema gives them, and a
    # reason left until after the rows came back empty: written first, it is
    # what the rows are then chosen to show.
    offered: Kept[list[ToolDefinition]] = Kept()

    Scenario() \
        .given(
            a_judge := a_model_answering_in_turn(_judged(), offered_tools=offered)
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            _a_flag_asked_for_in_order(offered, [QUOTE_FIELD, WHY_FIELD, ROWS_FIELD])
        )


@pytest.mark.unit
def test_a_judge_answering_in_prose_judges_nothing_and_says_so(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The API will not force the call on these models, so a paragraph can
    # come back - and in a replay, a missing recording looks the same. Logged,
    # so a suite can fail a case whose judge never judged.
    caplog.set_level(logging.WARNING, logger=THE_JUDGE_S_LOGGER)

    Scenario() \
        .given(
            a_judge := a_model_answering_in_turn(None)
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            all_of(
                _flagged([]),
                one_record_was_logged(caplog, THE_JUDGE_S_LOGGER, logging.WARNING,
                                      DID_NOT_ANSWER)
            )
        )


@pytest.mark.unit
@pytest.mark.parametrize("failure", [ModelRefused(DONT_CARE_REASON),
                                     ModelUnavailable(DONT_CARE_REASON),
                                     RequestRejected(DONT_CARE_REASON)],
                         ids=["refused", "unavailable", "rejected"])
def test_a_judge_that_cannot_be_had_judges_nothing_and_says_so(
    failure: Exception,
    caplog: pytest.LogCaptureFixture
) -> None:
    # The answer is the writer's; the judge only ever sends one back. A judge
    # nobody could reach is no reason to lose the answer, or the walk.
    caplog.set_level(logging.WARNING, logger=THE_JUDGE_S_LOGGER)

    Scenario() \
        .given(
            a_judge := _a_judge_failing_with(failure)
        ) \
        .when(
            lambda: _flags_from(a_judge)
        ) \
        .then(
            all_of(
                _flagged([]),
                one_record_was_logged(caplog, THE_JUDGE_S_LOGGER, logging.WARNING,
                                      DID_NOT_ANSWER)
            )
        )


@pytest.mark.unit
def test_a_flag_sent_back_asks_for_that_claim_corrected_and_nothing_else_moved() -> None:
    # A rewrite told to fix one thing has got another wrong that it had
    # right, so the fault says to keep the rest.
    Scenario() \
        .given(
            a_flag := Flag(quote=SOME_CLAIM, rows=(SOME_ROW, SOME_OTHER_ROW), why=SOME_REASON,
                           fields=(SOME_FIELD,))
        ) \
        .when(
            lambda: faults_of([a_flag])
        ) \
        .then(
            _one_fault_saying(["correct or hedge this claim", "keep everything else",
                               SOME_CLAIM, SOME_REASON, SOME_ROW, SOME_OTHER_ROW])
        )


@pytest.mark.unit
@pytest.mark.parametrize("no_reason", [AN_EMPTY_REASON, A_REASON_OF_ONLY_SPACING,
                                       A_ONE_WORD_REASON],
                         ids=["empty", "whitespace", "one-word"])
def test_a_flag_with_no_reason_to_speak_of_is_sent_back_saying_the_record_does_not_hold_it(
        no_reason: str) -> None:
    # The writer is told why its claim came back; a fault with no reason
    # gives it nothing to correct, so it is told what every flag means.
    Scenario() \
        .given(
            a_flag := Flag(quote=SOME_CLAIM, rows=(SOME_ROW,), why=no_reason,
                           fields=(SOME_FIELD,))
        ) \
        .when(
            lambda: faults_of([a_flag])
        ) \
        .then(
            _one_fault_saying([SOME_CLAIM, NO_REASON_GIVEN, SOME_ROW])
        )


@pytest.mark.unit
def test_a_flag_citing_no_row_is_sent_back_saying_no_row_holds_it() -> None:
    Scenario() \
        .given(
            a_flag := Flag(quote=SOME_CLAIM, rows=(), why=SOME_REASON, fields=(SOME_FIELD,))
        ) \
        .when(
            lambda: faults_of([a_flag])
        ) \
        .then(
            _one_fault_saying([SOME_CLAIM, SOME_REASON, "no row"])
        )


@pytest.mark.unit
def test_the_judge_is_asked_under_its_own_brief_one_call_a_turn() -> None:
    # What a claim must have to be supported, and what is not judged at all,
    # is the same for every answer, so it is the judge's standing brief; its
    # one answer is a call.
    some_model = "some-model"
    some_effort: Effort = "medium"

    Scenario() \
        .when(
            lambda: judge_policy(some_model, some_effort)
        ) \
        .then(
            the_answer_was(ModelPolicy(model=some_model, effort=some_effort, brief=JUDGE_BRIEF,
                                       one_tool_call_per_turn=True))
        )


def _flags_from(judge: LLMClient, answer: dict[str, str] = SOME_ANSWER) -> list[Flag]:
    return flags_on(judge, record=SOME_RECORD, answer=answer, rows=SOME_ROWS, scope=SOME_SCOPE)


def _a_flag(quote: str, rows: list[str]) -> dict[str, Any]:
    return {QUOTE_FIELD: quote, ROWS_FIELD: rows, WHY_FIELD: SOME_REASON}


def _supported(quote: str, rows: list[str]) -> dict[str, Any]:
    return {QUOTE_FIELD: quote, ROWS_FIELD: rows}


def _judged(*flags: dict[str, Any]) -> dict[str, Any]:
    return {SUPPORTED_FIELD: [], FLAGS_FIELD: list(flags)}


def _a_judge_flagging(*flags: dict[str, Any]) -> LLMClient:
    return a_model_answering_in_turn(_judged(*flags))


def _a_judge_failing_with(failure: Exception) -> LLMClient:
    class Failing:
        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int | None = None) -> Turn:
            raise failure

    return Failing()


def _flagged(expected: list[Flag]) -> Assertion[list[Flag]]:
    def assertion(flags: list[Flag]) -> bool:
        if flags != expected:
            raise AssertionError(f"Expected the flags {expected}, got {flags}.")

        return True

    return assertion


def _flagged_once_quoting(quote: str) -> Assertion[list[Flag]]:
    def assertion(flags: list[Flag]) -> bool:
        if [flag.quote for flag in flags] != [quote]:
            raise AssertionError(
                f"Expected one flag kept, quoting [{quote}], got {flags}.")

        return True

    return assertion


def _asked_with(asked: Kept[Transcript], expected: list[str]) -> Assertion[list[Flag]]:
    def assertion(_: list[Flag]) -> bool:
        said = "\n".join(exchange.text for exchange in asked.taken[0]
                         if isinstance(exchange, Ask))
        missing = [text for text in expected if text not in said]
        if missing:
            raise AssertionError(
                f"Expected the judge asked with each of {expected}, and {missing} "
                f"were not in [{said}].")

        return True

    return assertion


def _offered_only(offered: Kept[list[ToolDefinition]], name: str) -> Assertion[list[Flag]]:
    def assertion(_: list[Flag]) -> bool:
        names = [tool.name for tool in offered.taken[0]]
        if names != [name]:
            raise AssertionError(f"Expected the judge offered only [{name}], got {names}.")

        return True

    return assertion


def _offered_requiring(offered: Kept[list[ToolDefinition]],
                       fields: list[str]) -> Assertion[list[Flag]]:
    def assertion(_: list[Flag]) -> bool:
        required = [list(tool.required) for tool in offered.taken[0]]
        if required != [fields]:
            raise AssertionError(
                f"Expected the judge's one tool to require {fields}, got {required}.")

        return True

    return assertion


def _a_flag_asked_for_in_order(offered: Kept[list[ToolDefinition]],
                               fields: list[str]) -> Assertion[list[Flag]]:
    def assertion(_: list[Flag]) -> bool:
        asked_for = [list(tool.properties[FLAGS_FIELD]["items"]["properties"])
                     for tool in offered.taken[0]]
        if asked_for != [fields]:
            raise AssertionError(
                f"Expected a flag asked for as {fields}, in that order, got {asked_for}.")

        return True

    return assertion


def _says(expected: str) -> Assertion[str]:
    def assertion(brief: str) -> bool:
        if expected not in " ".join(brief.split()):
            raise AssertionError(f"Expected the judge's brief to say [{expected}], and it "
                                 f"did not.")

        return True

    return assertion


def _one_fault_saying(expected: list[str]) -> Assertion[list[str]]:
    def assertion(faults: list[str]) -> bool:
        missing = [text for text in expected if len(faults) != 1 or text not in faults[0]]
        if missing:
            raise AssertionError(
                f"Expected one fault saying each of {expected}, and {missing} were "
                f"not in {faults}.")

        return True

    return assertion
