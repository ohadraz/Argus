"""The one exchange with the model for the executive synopsis's overview.

Asked once, sent back once with what was wrong, and given up after that or
after the model fails to answer: an overview that is not right is not sent, so
there is nothing to keep but the reason.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping

import pytest
from agent_postmortem.grounding import FLAGS_FIELD, QUOTE_FIELD, ROWS_FIELD, WHY_FIELD
from agent_postmortem.synopsis_conversation import Overview, the_overview
from agent_postmortem.synopsis_prompting import OVERVIEW_FIELD, Paging
from argus_core.llm import LLMClient, ModelRefused, ModelUnavailable, RequestRejected
from argus_core.models import Ask, ToolDefinition, ToolResults, Transcript, Turn
from argus_testkit import Assertion, Kept, Scenario, all_of, one_record_was_logged

from agent_postmortem_test.framework.builders import a_model_answering_in_turn

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
# A label no row of the postmortem goes by.
A_LABEL_NOT_IN_IT = "T9"
# A claim no line of the postmortem supports, said in an overview otherwise
# fine, and why the judge says the postmortem does not.
SOME_UNGROUNDED_CLAIM = "The flag was switched by hand."
AN_OVERVIEW_CLAIMING_IT = f"{A_GOOD_OVERVIEW} {SOME_UNGROUNDED_CLAIM}"
AN_OVERVIEW_CLAIMING_IT_WRITTEN = f"{A_GOOD_OVERVIEW_WRITTEN} {SOME_UNGROUNDED_CLAIM}"
SOME_REASON_IT_IS_NOT = "the postmortem says nothing of who switched it"
THE_OVERVIEW_S_LOGGER = "agent_postmortem.synopsis_conversation"


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
@pytest.mark.parametrize("failure", [ModelRefused(DONT_CARE_REASON),
                                     ModelUnavailable(DONT_CARE_REASON)],
                         ids=["refused", "unavailable"])
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
            _given_up_saying("the model")
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
                       judge: LLMClient | None = None) -> Overview:
    return the_overview(llm, service="io-shop", symptom="Checkout failed",
                        cause="A flag change turned off the path checkout relies on.",
                        figures=SOME_FIGURES, said=said, paging=Paging.ANSWERED,
                        disproven=False, resolution=DONT_CARE_RESOLUTION, judge=judge,
                        document=SOME_DOCUMENT, labels=SOME_LABELS,
                        incident_id=SOME_INCIDENT_ID)


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
def test_an_overview_claim_the_judge_flags_is_sent_back_naming_it() -> None:
    # Judged against the postmortem once the checks pass, and sent back once
    # like any fault, quoting the claim.
    asked: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: AN_OVERVIEW_CLAIMING_IT},
                                                 {OVERVIEW_FIELD: A_GOOD_OVERVIEW},
                                                 recording_into=asked),
            a_judge := a_model_answering_in_turn(_flagging(SOME_UNGROUNDED_CLAIM), _flagging())
        ) \
        .when(
            lambda: _the_overview_from(a_model, judge=a_judge)
        ) \
        .then(
            all_of(
                _kept(A_GOOD_OVERVIEW_WRITTEN),
                _the_second_ask_refused_quoting(asked, SOME_UNGROUNDED_CLAIM)
            )
        )


@pytest.mark.unit
def test_an_overview_flagged_again_on_its_second_attempt_is_kept_and_logged(
    caplog: pytest.LogCaptureFixture
) -> None:
    # The second attempt is the last, and a flag withholds nothing: an
    # overview the checks pass is sent, and the flag said where whoever
    # watches the model reads.
    caplog.set_level(logging.WARNING, logger=THE_OVERVIEW_S_LOGGER)

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: AN_OVERVIEW_CLAIMING_IT},
                                                 {OVERVIEW_FIELD: AN_OVERVIEW_CLAIMING_IT}),
            a_judge := a_model_answering_in_turn(_flagging(SOME_UNGROUNDED_CLAIM,
                                                           against=[SOME_LABEL]),
                                                 _flagging(SOME_UNGROUNDED_CLAIM,
                                                           against=[SOME_LABEL]))
        ) \
        .when(
            lambda: _the_overview_from(a_model, judge=a_judge)
        ) \
        .then(
            all_of(
                _kept(AN_OVERVIEW_CLAIMING_IT_WRITTEN),
                one_record_was_logged(caplog, THE_OVERVIEW_S_LOGGER, logging.WARNING,
                                      "executive overview claim not grounded",
                                      values={"incident_id": SOME_INCIDENT_ID,
                                              "fields": [OVERVIEW_FIELD],
                                              "quote": SOME_UNGROUNDED_CLAIM,
                                              "rows": [SOME_LABEL],
                                              "why": SOME_REASON_IT_IS_NOT})
            )
        )


@pytest.mark.unit
def test_an_overview_flag_citing_a_row_the_postmortem_does_not_hold_is_dropped() -> None:
    # A row nobody can be led to grounds nothing either way: the flag is the
    # judge's mistake, not the overview's.
    asked: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: AN_OVERVIEW_CLAIMING_IT},
                                                 recording_into=asked),
            a_judge := a_model_answering_in_turn(_flagging(SOME_UNGROUNDED_CLAIM,
                                                           against=[A_LABEL_NOT_IN_IT]))
        ) \
        .when(
            lambda: _the_overview_from(a_model, judge=a_judge)
        ) \
        .then(
            all_of(
                _kept(AN_OVERVIEW_CLAIMING_IT_WRITTEN),
                _asked_once(asked)
            )
        )


@pytest.mark.unit
def test_the_judge_reads_no_overview_the_checks_sent_back() -> None:
    # The checks' faults are cheaper and certain; an overview they refuse is
    # rewritten before anyone reads its meaning.
    judged: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: AN_OVERVIEW_IN_DIGITS},
                                                 {OVERVIEW_FIELD: A_GOOD_OVERVIEW}),
            a_judge := a_model_answering_in_turn(_flagging(), recording_into=judged)
        ) \
        .when(
            lambda: _the_overview_from(a_model, judge=a_judge)
        ) \
        .then(
            all_of(
                _kept(A_GOOD_OVERVIEW_WRITTEN),
                _the_judge_read_once(judged, shown=[A_GOOD_OVERVIEW],
                                     not_shown=[AN_OVERVIEW_IN_DIGITS])
            )
        )


@pytest.mark.unit
def test_the_judge_reads_the_overview_as_written_against_the_postmortem_and_its_ask() -> None:
    # The postmortem it was written from, and the ask that defines each figure
    # it names: a name in braces is written in by code, and not the judge's.
    # Only the ask says what a figure comes to.
    judged: Kept[Transcript] = Kept()

    Scenario() \
        .given(
            a_model := a_model_answering_in_turn({OVERVIEW_FIELD: A_GOOD_OVERVIEW}),
            a_judge := a_model_answering_in_turn(_flagging(), recording_into=judged)
        ) \
        .when(
            lambda: _the_overview_from(a_model, judge=a_judge)
        ) \
        .then(
            _the_judge_read_once(judged,
                                 shown=[SOME_DOCUMENT, A_GOOD_OVERVIEW, SOME_FIGURES["duration"]],
                                 not_shown=[])
        )


def _flagging(*quotes: str,
              against: list[str] | None = None) -> dict[str, list[dict[str, object]]]:
    """A judge's answer flagging each of `quotes`, citing the rows `against`, or
    none."""
    return {FLAGS_FIELD: [{QUOTE_FIELD: quote, ROWS_FIELD: against or [],
                           WHY_FIELD: SOME_REASON_IT_IS_NOT}
                          for quote in quotes]}


def _asked_once(asked: Kept[Transcript]) -> Assertion[Overview]:
    def assertion(_: Overview) -> bool:
        if len(asked.taken) != 1:
            raise AssertionError(
                f"Expected the writer asked once, its first overview kept; it was asked "
                f"{len(asked.taken)} times.")

        return True

    return assertion


def _the_judge_read_once(judged: Kept[Transcript], *, shown: list[str],
                         not_shown: list[str]) -> Assertion[Overview]:
    """That the judge was asked once, and shown each of `shown` and none of
    `not_shown`."""
    def assertion(_: Overview) -> bool:
        said = ["\n".join(exchange.text for exchange in transcript if isinstance(exchange, Ask))
                for transcript in judged.taken]
        missing = [text for text in shown if not said or text not in said[0]]
        present = [text for text in not_shown if said and text in said[0]]

        if len(said) != 1 or missing or present:
            raise AssertionError(
                f"Expected the judge asked once, shown {shown} and not {not_shown}; it was "
                f"asked {len(said)} times, {missing} were missing and {present} were shown, "
                f"in {said}.")

        return True

    return assertion
