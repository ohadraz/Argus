"""The one exchange with the model for the executive synopsis's overview.

Asked once, sent back once with what was wrong, and given up after that or
after the model fails to answer: an overview that is not right is not sent, so
there is nothing to keep but the reason.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from argus_testkit import (
    Assertion,
    Kept,
    Scenario,
    all_of,
    attempting,
    the_same_error_reached_the_caller,
)
from core.llm import (
    AnswerTruncated,
    LLMClient,
    ModelRefused,
    ModelUnavailable,
    RequestRejected,
    TurnPaused,
)
from core.models import ToolDefinition, ToolResults, Transcript, Turn
from executive_synopsis.synopsis_conversation import OVERVIEW_SCOPE, Overview, the_overview
from executive_synopsis.synopsis_prompting import OVERVIEW_FIELD, Paging
from postmortem_writing import Flag, Grounding, GroundingFor

from executive_synopsis_test.framework.assertions import built_with
from executive_synopsis_test.framework.builders import (
    AGrounding,
    a_grounding_flagging,
    a_model_answering_in_turn,
)

SOME_MINUTES = 7
SOME_SECONDS = 12
SOME_FIGURES = {"duration": f"{SOME_MINUTES}m {SOME_SECONDS}s",
                "customer_loss": "1,840.01 USD",
                "responder_cost": "31.50 USD"}
# The same figures as prose says them.
SOME_FIGURES_SAID = {**SOME_FIGURES,
                     "duration": f"{SOME_MINUTES} minutes {SOME_SECONDS} seconds"}
DONT_CARE_RESOLUTION = ("Argus: turned monthly-spend-feature off - recovered",)
DONT_CARE_REASON = "dont care"
# Why a model did not answer, as the reason the overview was given up says it.
SOME_REASON = "the model declined to answer"

# A number the model wrote in by itself, which no figure stands for.
SOME_NUMBER_OF_ITS_OWN = 7
# The word that speaks for Argus as though it were people.
WE = "We"

A_GOOD_OVERVIEW = ("Checkout failed for {duration}, costing the shop {customer_loss}; "
                   "the response cost {responder_cost}.")
A_GOOD_OVERVIEW_WRITTEN = A_GOOD_OVERVIEW.format(**SOME_FIGURES_SAID)
AN_OVERVIEW_IN_DIGITS = A_GOOD_OVERVIEW.replace("{duration}",
                                                f"{SOME_NUMBER_OF_ITS_OWN} minutes")
AN_OVERVIEW_AS_WE = f"{A_GOOD_OVERVIEW} {WE} turned the flag off."

# What prose puts around a figure that is a floor: before a stretch still going,
# and after a loss still adding up.
AT_LEAST = "at least"
SO_FAR = "so far"
# The same floor, said after an "at" of the overview's own.
NO_LESS_THAN = "no less than"

# The postmortem an overview is judged against, as its text says it, every
# label its rows go by, and the incident it is of.
SOME_LABEL = "T1"
SOME_DOCUMENT = f"Timeline\n{SOME_LABEL} 10:02 The flag was turned off."
SOME_LABELS = frozenset({SOME_LABEL})
SOME_INCIDENT_ID = "some-incident"
# A claim no line of the postmortem supports, said in an overview otherwise
# fine, and why the judge says the postmortem does not.
SOME_UNGROUNDED_CLAIM = "The flag was switched by hand."
AN_OVERVIEW_CLAIMING_IT = f"{A_GOOD_OVERVIEW} {SOME_UNGROUNDED_CLAIM}"
AN_OVERVIEW_CLAIMING_IT_WRITTEN = f"{A_GOOD_OVERVIEW_WRITTEN} {SOME_UNGROUNDED_CLAIM}"
SOME_REASON_IT_IS_NOT = "the postmortem says nothing of who switched it"
THE_OVERVIEW_S_LOGGER = "executive_synopsis.synopsis_conversation"


@pytest.mark.unit
def test_an_overview_accepted_first_time_has_its_figures_written_in_as_prose_says_them() -> None:
    # "For 7m 12s" is how a tile says it; a person writing would not.
    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: A_GOOD_OVERVIEW})
        ) \
        .when(
            lambda: _the_overview_from(a_model)
        ) \
        .then(
            _kept(A_GOOD_OVERVIEW_WRITTEN)
        )


@pytest.mark.unit
@pytest.mark.parametrize("at_least_as_written", [AT_LEAST, AT_LEAST.capitalize()],
                         ids=["within-a-sentence", "opening-one"])
def test_a_floor_the_overview_already_qualifies_is_written_in_qualified_once(
        at_least_as_written: str) -> None:
    # Asked with the tile's "at least", a model wrote "at least {duration}" -
    # and the duration as prose says it carries its own, so the overview read
    # "at least at least 7 days". The same of a loss "so far". The overview's
    # own word is the one kept, capital and all.
    some_floors_said = {**SOME_FIGURES_SAID,
                        "duration": f"{AT_LEAST} {SOME_FIGURES_SAID['duration']}",
                        "customer_loss": f"{SOME_FIGURES_SAID['customer_loss']} {SO_FAR}"}
    an_overview_qualifying_them = A_GOOD_OVERVIEW \
        .replace("{duration}", f"{at_least_as_written} {{duration}}") \
        .replace("{customer_loss}", f"{{customer_loss}} {SO_FAR}")

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: an_overview_qualifying_them})
        ) \
        .when(
            lambda: _the_overview_from(a_model, said=some_floors_said)
        ) \
        .then(
            _kept(an_overview_qualifying_them.format(**SOME_FIGURES_SAID))
        )


@pytest.mark.unit
def test_a_floor_after_an_at_of_the_overview_s_own_is_said_no_less_than() -> None:
    # "the lost takings at {customer_loss}", the loss a floor, lost its "at" to
    # the figure's own "at least" and read "the lost takings at least" - and
    # with the "at" kept, it would read "at at least". The overview's "at"
    # stays, and the floor is said the other way.
    some_amount = SOME_FIGURES_SAID["customer_loss"]
    some_floor_said = {**SOME_FIGURES_SAID, "customer_loss": f"{AT_LEAST} {some_amount}"}
    an_overview_with_its_own_at = A_GOOD_OVERVIEW.replace(
        "costing the shop {customer_loss}", "putting the lost takings at {customer_loss}")

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: an_overview_with_its_own_at})
        ) \
        .when(
            lambda: _the_overview_from(a_model, said=some_floor_said)
        ) \
        .then(
            _kept(an_overview_with_its_own_at.format(
                **{**some_floor_said, "customer_loss": f"{NO_LESS_THAN} {some_amount}"}))
        )


@pytest.mark.unit
def test_a_floor_the_overview_qualifies_after_its_own_at_is_said_no_less_than() -> None:
    # "the lost takings at at least {customer_loss}": the overview's own "at
    # least" between its own "at" and a floor that carries one too, which the
    # figure's qualifier dropped as said already left reading "at at least".
    # The overview's "at least" is read as the figure's, and the floor said the
    # way one after an "at" is.
    some_amount = SOME_FIGURES_SAID["customer_loss"]
    some_floor_said = {**SOME_FIGURES_SAID, "customer_loss": f"{AT_LEAST} {some_amount}"}
    an_overview_qualifying_after_its_at = A_GOOD_OVERVIEW.replace(
        "costing the shop {customer_loss}",
        f"putting the lost takings at {AT_LEAST} {{customer_loss}}")
    the_same_overview_with_its_at_alone = A_GOOD_OVERVIEW.replace(
        "costing the shop {customer_loss}", "putting the lost takings at {customer_loss}")

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(
                {OVERVIEW_FIELD: an_overview_qualifying_after_its_at})
        ) \
        .when(
            lambda: _the_overview_from(a_model, said=some_floor_said)
        ) \
        .then(
            _kept(the_same_overview_with_its_at_alone.format(
                **{**some_floor_said, "customer_loss": f"{NO_LESS_THAN} {some_amount}"}))
        )


@pytest.mark.unit
def test_a_loss_its_clause_already_says_so_far_of_is_not_said_so_far_again() -> None:
    # "the lost takings so far at {customer_loss}": the overview's "so far" two
    # words before the name rather than just after it, and the loss as prose
    # says it carrying its own, so the clause said it twice.
    some_amount = SOME_FIGURES_SAID["customer_loss"]
    some_loss_said = {**SOME_FIGURES_SAID, "customer_loss": f"{some_amount} {SO_FAR}"}
    an_overview_saying_so_far_first = A_GOOD_OVERVIEW.replace(
        "costing the shop {customer_loss}",
        f"putting the lost takings {SO_FAR} at {{customer_loss}}")

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(
                {OVERVIEW_FIELD: an_overview_saying_so_far_first})
        ) \
        .when(
            lambda: _the_overview_from(a_model, said=some_loss_said)
        ) \
        .then(
            _kept(an_overview_saying_so_far_first.format(**SOME_FIGURES_SAID))
        )


@pytest.mark.unit
def test_a_so_far_in_another_clause_leaves_the_loss_its_own() -> None:
    # Only the figure's own clause speaks for it: a "so far" a sentence earlier
    # is about something else, and the loss still adding up says so itself.
    some_amount = SOME_FIGURES_SAID["customer_loss"]
    some_loss_said = {**SOME_FIGURES_SAID, "customer_loss": f"{some_amount} {SO_FAR}"}
    an_overview_with_so_far_elsewhere = f"Nothing has failed again {SO_FAR}. {A_GOOD_OVERVIEW}"

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(
                {OVERVIEW_FIELD: an_overview_with_so_far_elsewhere})
        ) \
        .when(
            lambda: _the_overview_from(a_model, said=some_loss_said)
        ) \
        .then(
            _kept(an_overview_with_so_far_elsewhere.format(**some_loss_said))
        )


@pytest.mark.unit
def test_a_refused_overview_is_sent_back_through_its_own_call_and_the_correction_kept() -> None:
    # Refused through the call's own result, so the model sees what it wrote
    # and what was wrong, and corrects that rather than starting over.
    asked: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: AN_OVERVIEW_IN_DIGITS},
                                                 {OVERVIEW_FIELD: A_GOOD_OVERVIEW},
                                                 recording_into=asked)
        ) \
        .when(
            lambda: _the_overview_from(a_model)
        ) \
        .then(all_of(
            _kept(A_GOOD_OVERVIEW_WRITTEN),
            _the_second_ask_refused_quoting(asked, f"[{SOME_NUMBER_OF_ITS_OWN}]")
        ))


@pytest.mark.unit
def test_an_overview_speaking_as_we_is_sent_back_and_the_correction_kept() -> None:
    asked: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: AN_OVERVIEW_AS_WE},
                                                 {OVERVIEW_FIELD: A_GOOD_OVERVIEW},
                                                 recording_into=asked)
        ) \
        .when(
            lambda: _the_overview_from(a_model)
        ) \
        .then(all_of(
            _kept(A_GOOD_OVERVIEW_WRITTEN),
            _the_second_ask_refused_quoting(asked, f"[{WE}]")
        ))


@pytest.mark.unit
def test_an_answer_with_no_call_is_asked_for_again() -> None:
    Scenario() \
        .given(
            a_model := a_model_answering_in_turn(None, {OVERVIEW_FIELD: A_GOOD_OVERVIEW})
        ) \
        .when(
            lambda: _the_overview_from(a_model)
        ) \
        .then(
            _kept(A_GOOD_OVERVIEW_WRITTEN)
        )


@pytest.mark.unit
def test_an_overview_refused_twice_is_given_up_saying_why() -> None:
    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: AN_OVERVIEW_IN_DIGITS},
                                                 {OVERVIEW_FIELD: AN_OVERVIEW_IN_DIGITS})
        ) \
        .when(
            lambda: _the_overview_from(a_model)
        ) \
        .then(
            _given_up_saying(f"[{SOME_NUMBER_OF_ITS_OWN}]")
        )


@pytest.mark.unit
@pytest.mark.parametrize("failure", [ModelRefused(SOME_REASON),
                                     AnswerTruncated(SOME_REASON),
                                     TurnPaused(SOME_REASON)],
                         ids=["refused", "truncated", "paused"])
def test_a_model_that_does_not_answer_gives_the_overview_up(failure: Exception) -> None:
    # The incident is over and the postmortem written; an overview nobody could
    # get is no reason to fail the walk, and no reason to post anything either.
    Scenario() \
        .given(
            a_model := _a_model_failing_with(failure)
        ) \
        .when(
            lambda: _the_overview_from(a_model)
        ) \
        .then(
            _given_up_saying(f"the model did not answer: {SOME_REASON}")
        )


@pytest.mark.unit
def test_a_model_out_of_reach_on_the_run_s_last_try_gives_the_overview_up() -> None:
    # No later try is coming to write it: the walk goes on without one.
    Scenario() \
        .given(
            a_model := _a_model_failing_with(ModelUnavailable(SOME_REASON))
        ) \
        .when(
            lambda: _the_overview_from(a_model, outage_ends_it=True)
        ) \
        .then(
            _given_up_saying(f"the model could not be reached: {SOME_REASON}")
        )


@pytest.mark.unit
def test_a_model_out_of_reach_with_tries_left_reaches_the_caller() -> None:
    # The run is tried again from the synopsis, which an outage can outlast:
    # given up now, it would be given up for good.
    some_outage = ModelUnavailable(DONT_CARE_REASON)

    Scenario() \
        .given(
            a_model := _a_model_failing_with(some_outage)
        ) \
        .when(
            attempting(lambda: _the_overview_from(a_model))
        ) \
        .then(
            the_same_error_reached_the_caller(some_outage)
        )


@pytest.mark.unit
def test_a_request_the_api_rejects_gives_the_overview_up_in_the_api_s_words() -> None:
    # A replay with no answer recorded for the overview failed the whole walk,
    # after its postmortem, and nothing said why no synopsis was sent.
    some_rejection = "the model's API rejected the request: nothing queued"

    Scenario() \
        .given(
            a_model := _a_model_failing_with(RequestRejected(some_rejection))
        ) \
        .when(
            lambda: _the_overview_from(a_model)
        ) \
        .then(
            _given_up_saying(some_rejection)
        )


def _the_overview_from(llm: LLMClient,
                       said: Mapping[str, str] = SOME_FIGURES_SAID,
                       judge: LLMClient | None = None,
                       grounding_for: GroundingFor = Grounding,
                       outage_ends_it: bool = False) -> Overview:
    return the_overview(llm, service="io-shop", symptom="Checkout failed",
                        cause="A flag change turned off the path checkout relies on.",
                        figures=SOME_FIGURES, said=said, paging=Paging.ANSWERED,
                        disproven=False, resolution=DONT_CARE_RESOLUTION, judge=judge,
                        document=SOME_DOCUMENT, labels=SOME_LABELS,
                        incident_id=SOME_INCIDENT_ID, grounding_for=grounding_for,
                        outage_ends_it=outage_ends_it)


def _a_model_failing_with(failure: Exception) -> LLMClient:
    class Failing:
        def converse(self,
                     transcript: Transcript,
                     tools: list[ToolDefinition],
                     max_tokens: int | None = None) -> Turn:
            raise failure

    return Failing()


def _kept(expected: str) -> Assertion[Overview]:
    def assertion(overview: Overview) -> bool:
        if overview.text != expected or overview.withheld_because is not None:
            raise AssertionError(
                f"Expected the overview [{expected}] kept, got [{overview.text}] "
                f"withheld because [{overview.withheld_because}].")

        return True

    return assertion


def _given_up_saying(quoted: str) -> Assertion[Overview]:
    def assertion(overview: Overview) -> bool:
        if overview.text is not None or quoted not in (overview.withheld_because or ""):
            raise AssertionError(
                f"Expected no overview, given up for a reason saying [{quoted}], got "
                f"[{overview.text}] withheld because [{overview.withheld_because}].")

        return True

    return assertion


def _the_second_ask_refused_quoting(asked: Kept[Transcript], quoted: str) -> Assertion[Overview]:
    def assertion(_: Overview) -> bool:
        last = asked.taken[1][-1] if len(asked.taken) > 1 else None
        if not isinstance(last, ToolResults) or not all(
                result.failed and quoted in result.content for result in last.results):
            raise AssertionError(
                f"Expected the second ask to end in a failed result quoting {quoted}, "
                f"got {last}.")

        return True

    return assertion


@pytest.mark.unit
def test_an_overview_claim_the_grounding_flags_is_sent_back_naming_it() -> None:
    # Judged against the postmortem once the checks pass, and sent back once
    # like any fault, quoting the claim.
    asked: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: AN_OVERVIEW_CLAIMING_IT},
                                                 {OVERVIEW_FIELD: A_GOOD_OVERVIEW},
                                                 recording_into=asked),
            a_grounding := a_grounding_flagging([_a_flag_on(SOME_UNGROUNDED_CLAIM)])
        ) \
        .when(
            lambda: _the_overview_from(a_model, grounding_for=a_grounding)
        ) \
        .then(
            all_of(
                _kept(A_GOOD_OVERVIEW_WRITTEN),
                _the_second_ask_refused_quoting(asked, SOME_UNGROUNDED_CLAIM)
            )
        )


@pytest.mark.unit
def test_an_overview_flagged_on_its_first_attempt_is_judged_on_its_second_only_in_the_log(
) -> None:
    # The second attempt is the last, and a flag withholds nothing: an
    # overview the checks pass is sent, and its flags said in the log rather
    # than sent back.
    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: AN_OVERVIEW_CLAIMING_IT},
                                                 {OVERVIEW_FIELD: AN_OVERVIEW_CLAIMING_IT}),
            a_grounding := a_grounding_flagging([_a_flag_on(SOME_UNGROUNDED_CLAIM)])
        ) \
        .when(
            lambda: _the_overview_from(a_model, grounding_for=a_grounding)
        ) \
        .then(
            all_of(
                _kept(AN_OVERVIEW_CLAIMING_IT_WRITTEN),
                _judged(a_grounding, [{OVERVIEW_FIELD: AN_OVERVIEW_CLAIMING_IT}]),
                _logged(a_grounding, [{OVERVIEW_FIELD: AN_OVERVIEW_CLAIMING_IT}])
            )
        )


@pytest.mark.unit
def test_the_grounding_is_built_against_the_postmortem_s_rows_in_the_overview_s_own_log() -> None:
    # Its rows are the postmortem's labels, so a flag citing a row nobody can be
    # led to is the judge's mistake and dropped; and its flags are said in this
    # write-up's log, in its words.
    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: A_GOOD_OVERVIEW}),
            some_judge := a_model_answering_in_turn(),
            a_grounding := a_grounding_flagging([])
        ) \
        .when(
            lambda: _the_overview_from(a_model, grounding_for=a_grounding, judge=some_judge)
        ) \
        .then(
            all_of(
                built_with(a_grounding, judge=some_judge, rows_holding=SOME_LABELS,
                           scope=OVERVIEW_SCOPE, incident_id=SOME_INCIDENT_ID,
                           logger=THE_OVERVIEW_S_LOGGER,
                           logged_as="executive overview claim not grounded"),
                _its_rows_were(a_grounding, SOME_LABELS)
            )
        )


@pytest.mark.unit
def test_the_grounding_reads_no_overview_the_checks_sent_back() -> None:
    # The checks' faults are cheaper and certain; an overview they refuse is
    # rewritten before anyone reads its meaning.
    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: AN_OVERVIEW_IN_DIGITS},
                                                 {OVERVIEW_FIELD: A_GOOD_OVERVIEW}),
            a_grounding := a_grounding_flagging([])
        ) \
        .when(
            lambda: _the_overview_from(a_model, grounding_for=a_grounding)
        ) \
        .then(
            all_of(
                _kept(A_GOOD_OVERVIEW_WRITTEN),
                _judged(a_grounding, []),
                _logged(a_grounding, [{OVERVIEW_FIELD: A_GOOD_OVERVIEW}])
            )
        )


@pytest.mark.unit
def test_the_grounding_reads_the_overview_as_written_against_the_postmortem_and_its_ask() -> None:
    # The postmortem it was written from, and the ask that defines each figure
    # it names: a name in braces is written in by code, and not the judge's.
    # Only the ask says what a figure comes to.
    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: A_GOOD_OVERVIEW}),
            a_grounding := a_grounding_flagging([])
        ) \
        .when(
            lambda: _the_overview_from(a_model, grounding_for=a_grounding)
        ) \
        .then(
            all_of(
                _the_record_holds(a_grounding, [SOME_DOCUMENT, SOME_FIGURES["duration"]]),
                _judged(a_grounding, [{OVERVIEW_FIELD: A_GOOD_OVERVIEW}])
            )
        )


def _a_flag_on(quote: str) -> Flag:
    return Flag(quote=quote, rows=(), why=SOME_REASON_IT_IS_NOT, fields=(OVERVIEW_FIELD,))


def _judged(grounding: AGrounding, expected: list[dict[str, str]]) -> Assertion[Overview]:
    def assertion(_: Overview) -> bool:
        if grounding.judged.taken != expected:
            raise AssertionError(f"Expected the grounding asked to judge {expected}, got "
                                 f"{grounding.judged.taken}.")

        return True

    return assertion


def _logged(grounding: AGrounding, expected: list[dict[str, str]]) -> Assertion[Overview]:
    def assertion(_: Overview) -> bool:
        if grounding.logged_answers.taken != expected:
            raise AssertionError(f"Expected the grounding asked to log {expected}, got "
                                 f"{grounding.logged_answers.taken}.")

        return True

    return assertion


def _its_rows_were(grounding: AGrounding, expected: frozenset[str]) -> Assertion[Overview]:
    """That the grounding's rows are exactly `expected`: a row beyond them is
    one a flag could cite and survive."""
    def assertion(_: Overview) -> bool:
        rows = grounding.built.only().rows
        if rows != expected:
            raise AssertionError(f"Expected the grounding's rows to be exactly "
                                 f"{sorted(expected)}, got {sorted(rows)}.")

        return True

    return assertion


def _the_record_holds(grounding: AGrounding, expected: list[str]) -> Assertion[Overview]:
    def assertion(_: Overview) -> bool:
        record = grounding.built.only().record
        missing = [text for text in expected if text not in record]
        if missing:
            raise AssertionError(f"Expected the grounding's record to hold {missing}; it was "
                                 f"[{record}].")

        return True

    return assertion
