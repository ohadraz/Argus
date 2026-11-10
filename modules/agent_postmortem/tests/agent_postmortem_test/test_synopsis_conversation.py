"""The one exchange with the model for the executive synopsis's overview.

Asked once, sent back once with what was wrong, and given up after that or
after the model fails to answer: an overview that is not right is not sent, so
there is nothing to keep but the reason.
"""

from __future__ import annotations

from collections.abc import Mapping

import pytest
from agent_postmortem.synopsis_conversation import Overview, the_overview
from agent_postmortem.synopsis_prompting import OVERVIEW_FIELD, Paging
from argus_core.llm import LLMClient, ModelRefused, ModelUnavailable, RequestRejected
from argus_core.models import ToolDefinition, ToolResults, Transcript, Turn
from argus_testkit import Assertion, Kept, Scenario, all_of

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
                       said: Mapping[str, str] = SOME_FIGURES_SAID) -> Overview:
    return the_overview(llm, service="io-shop", symptom="Checkout failed",
                        cause="A flag change turned off the path checkout relies on.",
                        figures=SOME_FIGURES, said=said, paging=Paging.ANSWERED,
                        disproven=False, resolution=DONT_CARE_RESOLUTION)


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
