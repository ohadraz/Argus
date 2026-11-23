"""The executive synopsis, written from the stored postmortem.

The response arrives priced, and the synopsis carries it as priced. The
overview is the conversation's, kept or given up there, and handed in - naming
the record's pull request wherever it names one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from argus_testkit import Assertion, Kept, Scenario
from core.llm import LLMClient
from core.models import (
    ExecutiveSynopsisDocument,
    OpenedPullRequest,
    PostmortemDocument,
    PricedResponse,
    TitleCost,
)
from executive_synopsis.synopsis_conversation import Overview
from executive_synopsis.synopsis_prompting import Paging
from executive_synopsis.synopsis_writing import Overviewing, write_executive_synopsis
from postmortem_writing import SHARED_PAGE_ASSUMPTION_LABEL

from executive_synopsis_test.framework.builders import a_model_answering_in_turn

SOME_SERVICE = "io-shop"
SOME_INCIDENT_ID = "6f1c2a8e-4b1d-4c6e-9a51-0d2f3b7e8c11"
SOME_CURRENCY = "usd"
SOME_TITLE = "Senior Kuki"

THEIR_MINUTES = 30
THEIR_ROW = TitleCost(title=SOME_TITLE, responders=2, minutes=THEIR_MINUTES,
                      midpoint=Decimal(THEIR_MINUTES), minimum=Decimal(THEIR_MINUTES) / 2,
                      maximum=Decimal(THEIR_MINUTES) * 2)
SOME_BASIS = ["Working year: annual pay bands divided by 2000 hours"]
THEIR_COST = PricedResponse(cost_by_title=[THEIR_ROW],
                            responder_cost_estimate=THEIR_ROW.midpoint,
                            responder_cost_minimum=THEIR_ROW.minimum,
                            responder_cost_maximum=THEIR_ROW.maximum,
                            responder_cost_currency=SOME_CURRENCY,
                            response_cost_basis=SOME_BASIS)

SOME_MINUTES = 7
SOME_SECONDS = 12
SOME_FIGURES = {"duration": f"{SOME_MINUTES}m {SOME_SECONDS}s",
                "responder_cost": f"{THEIR_ROW.midpoint:.2f} {SOME_CURRENCY}"}
SOME_FIGURES_SAID = {**SOME_FIGURES,
                     "duration": f"{SOME_MINUTES} minutes {SOME_SECONDS} seconds"}
SOME_RESOLUTION = ("Argus: turned monthly-spend-feature off - recovered",)
SOME_SYMPTOM = "Checkout failed"
SOME_CAUSE = "A flag change turned off the path checkout relies on."
SOME_OVERVIEW = (f"{SOME_SYMPTOM} for {SOME_FIGURES_SAID['duration']}; "
                 f"the response cost {SOME_FIGURES_SAID['responder_cost']}.")
# The postmortem as its reader reads it, and every label its rows go by.
SOME_LABEL = "T1"
SOME_DOCUMENT = f"Timeline (UTC)\n{SOME_LABEL} | 14:03 | Argus turned the flag off."
SOME_LABELS = frozenset({SOME_LABEL})
# The draft this incident's record holds.
SOME_PULL_REQUEST_NUMBER = 1
SOME_PULL_REQUEST = OpenedPullRequest(
    number=SOME_PULL_REQUEST_NUMBER,
    url=f"https://github.invalid/acme/shop/pull/{SOME_PULL_REQUEST_NUMBER}",
    branch="argus/fix-abc")
# The draft a replay's recording names: the one the recording run opened.
SOME_OTHER_RUNS_PULL_REQUEST_NUMBER = 449


@pytest.mark.unit
def test_a_kept_overview_is_the_synopsis_s_overview() -> None:
    Scenario() \
        .given(
            an_overview := _an_overview_of(Overview(text=SOME_OVERVIEW))
        ) \
        .when(
            lambda: _the_synopsis_of(_a_postmortem_of_two_seniors(), an_overview)
        ) \
        .then(
            _overview_kept(SOME_OVERVIEW)
        )


@pytest.mark.unit
def test_an_overview_naming_another_run_s_pull_request_names_the_record_s() -> None:
    # A replay's recording names the draft of the run that recorded it, where
    # the synopsis's own Resolution names this run's two lines below.
    Scenario() \
        .given(
            an_overview := _an_overview_of(Overview(
                text=_a_draft_fix_awaiting_review(SOME_OTHER_RUNS_PULL_REQUEST_NUMBER)))
        ) \
        .when(
            lambda: _the_synopsis_of(_a_postmortem_of_two_seniors().model_copy(
                update={"pull_request": SOME_PULL_REQUEST}), an_overview)
        ) \
        .then(
            _overview_kept(_a_draft_fix_awaiting_review(SOME_PULL_REQUEST.number))
        )


@pytest.mark.unit
def test_an_overview_given_up_leaves_the_synopsis_without_one_saying_why() -> None:
    some_reason = "the overview was refused twice"

    Scenario() \
        .given(
            an_overview := _an_overview_of(Overview(text=None, withheld_because=some_reason))
        ) \
        .when(
            lambda: _the_synopsis_of(_a_postmortem_of_two_seniors().model_copy(
                update={"pull_request": SOME_PULL_REQUEST}), an_overview)
        ) \
        .then(
            _overview_withheld_because(some_reason)
        )


@pytest.mark.unit
def test_the_overview_is_asked_of_the_postmortem_and_judged_against_it() -> None:
    # Its symptom and cause to write from, and the whole of it as a reader
    # reads it - with every label its rows go by - for the judge to read the
    # overview against.
    asked: Kept[dict[str, Any]] = Kept()

    Scenario() \
        .given(
            an_overview := _an_overview_of(Overview(text=SOME_OVERVIEW), asked_into=asked),
            some_judge := a_model_answering_in_turn()
        ) \
        .when(
            lambda: _the_synopsis_of(_a_postmortem_of_two_seniors(), an_overview,
                                     judge=some_judge)
        ) \
        .then(
            _asked_with(asked, {"service": SOME_SERVICE, "symptom": SOME_SYMPTOM,
                                "cause": SOME_CAUSE, "figures": SOME_FIGURES,
                                "said": SOME_FIGURES_SAID, "paging": Paging.ANSWERED,
                                "disproven": False, "resolution": SOME_RESOLUTION,
                                "judge": some_judge, "document": SOME_DOCUMENT,
                                "labels": SOME_LABELS, "incident_id": SOME_INCIDENT_ID,
                                "outage_ends_it": False})
        )


@pytest.mark.unit
@pytest.mark.parametrize("outage_ends_it", [True, False], ids=["last-try", "tries-left"])
def test_the_overview_is_asked_saying_whether_an_outage_ends_it(outage_ends_it: bool) -> None:
    # Whether this is the run's last try is the caller's to know; the
    # conversation is only told what it comes to.
    asked: Kept[dict[str, Any]] = Kept()

    Scenario() \
        .given(
            an_overview := _an_overview_of(Overview(text=SOME_OVERVIEW), asked_into=asked)
        ) \
        .when(
            lambda: _the_synopsis_of(_a_postmortem_of_two_seniors(), an_overview,
                                     outage_ends_it=outage_ends_it)
        ) \
        .then(
            _asked_with_an_outage_ending_it(asked, outage_ends_it)
        )


@pytest.mark.unit
@pytest.mark.parametrize("paged, responders, paging", [
    (False, 0, Paging.NOT_PAGED),
    (True, 0, Paging.UNACKNOWLEDGED),
    (None, None, Paging.NOT_KNOWN)
], ids=["nobody-paged", "page-unacknowledged", "not-read"])
def test_the_overview_is_asked_saying_why_nobody_responded(paged: bool | None,
                                                          responders: int | None,
                                                          paging: Paging) -> None:
    # Read off the postmortem's record of whether a page went out, not off the
    # count: a page nobody acknowledged and no page at all both count nobody.
    asked: Kept[dict[str, Any]] = Kept()

    Scenario() \
        .given(
            an_overview := _an_overview_of(Overview(text=SOME_OVERVIEW), asked_into=asked)
        ) \
        .when(
            lambda: _the_synopsis_of(_a_postmortem_of_two_seniors().model_copy(
                update={"paged": paged, "responders": responders}), an_overview)
        ) \
        .then(
            _asked_with_paging(asked, paging)
        )


@pytest.mark.unit
def test_the_overview_is_asked_saying_the_alarm_was_disproven() -> None:
    # Read off the postmortem's disproof: a disproven alarm has no duration,
    # and the ask says why where it would go.
    asked: Kept[dict[str, Any]] = Kept()
    dont_care_when_disproven = datetime.now(UTC)

    Scenario() \
        .given(
            an_overview := _an_overview_of(Overview(text=SOME_OVERVIEW), asked_into=asked)
        ) \
        .when(
            lambda: _the_synopsis_of(_a_postmortem_of_two_seniors().model_copy(
                update={"disproven_at": dont_care_when_disproven}), an_overview)
        ) \
        .then(
            _asked_as_disproven(asked)
        )


@pytest.mark.unit
def test_the_response_is_carried_as_priced() -> None:
    # Every row, every total and every line of the basis, as the pricing left
    # them: the synopsis is where they are kept.
    Scenario() \
        .when(
            lambda: _the_synopsis_of(_a_postmortem_of_two_seniors())
        ) \
        .then(
            _priced_as(THEIR_COST)
        )


@pytest.mark.unit
@pytest.mark.parametrize("shared", [True, False], ids=["shared", "not-shared"])
def test_a_response_shared_with_other_incidents_is_said_in_the_postmortem_s_words(
    shared: bool
) -> None:
    # The postmortem says it beside its minutes, and the synopsis beside its
    # cost - in the same words, taken from the postmortem rather than said again.
    some_sharing = (f"{SHARED_PAGE_ASSUMPTION_LABEL}: the on-call incident this one was "
                    f"paged under was also about 1 other incident")
    dont_care_other_assumption = "Some other assumption"
    some_assumptions = [dont_care_other_assumption, *([some_sharing] if shared else [])]

    Scenario() \
        .when(
            lambda: _the_synopsis_of(_a_postmortem_of_two_seniors().model_copy(
                update={"assumptions": some_assumptions}))
        ) \
        .then(
            _said_shared(some_sharing if shared else None)
        )


def _the_synopsis_of(postmortem: PostmortemDocument,
                     overview_of: Overviewing | None = None,
                     judge: LLMClient | None = None,
                     outage_ends_it: bool = False) -> ExecutiveSynopsisDocument:
    """The synopsis of `postmortem`, the two seniors' response priced."""
    return write_executive_synopsis(
        postmortem, incident_id=SOME_INCIDENT_ID, service=SOME_SERVICE, cost=THEIR_COST,
        figures=SOME_FIGURES, said=SOME_FIGURES_SAID, resolution=SOME_RESOLUTION,
        document=SOME_DOCUMENT, labels=SOME_LABELS,
        llm=_dont_care_llm(),
        judge=judge if judge is not None else _dont_care_llm(),
        outage_ends_it=outage_ends_it,
        overview_of=(overview_of if overview_of is not None
                     else _an_overview_of(Overview(text=SOME_OVERVIEW))))


def _a_postmortem_of_two_seniors() -> PostmortemDocument:
    """A postmortem of the two seniors' response."""
    return PostmortemDocument(
        root_cause="dont care",
        cause_in_plain_words=SOME_CAUSE,
        symptom=SOME_SYMPTOM,
        executive_summary="dont care",
        customer_loss_estimate=None,
        estimate_currency=None,
        engineer_minutes=THEIR_ROW.minutes,
        responders=THEIR_ROW.responders,
        tokens_spent=None,
        assumptions=[]
    )


def _a_draft_fix_awaiting_review(number: int) -> str:
    """An overview's sentence naming pull request `number` as Argus names one."""
    return f"A draft fix, PR #{number}, awaits review."


def _an_overview_of(overview: Overview,
                    asked_into: Kept[dict[str, Any]] | None = None) -> Overviewing:
    """A conversation that comes to `overview`, keeping what it was asked."""
    def overview_of(dont_care_llm: LLMClient,
                    *,
                    service: str,
                    symptom: str | None,
                    cause: str | None,
                    figures: Mapping[str, str],
                    said: Mapping[str, str],
                    paging: Paging,
                    disproven: bool,
                    resolution: Sequence[str],
                    judge: LLMClient | None,
                    document: str,
                    labels: frozenset[str],
                    incident_id: str,
                    outage_ends_it: bool = False) -> Overview:
        if asked_into is not None:
            asked_into.take({"service": service, "symptom": symptom, "cause": cause,
                             "figures": figures, "said": said, "paging": paging,
                             "disproven": disproven, "resolution": resolution,
                             "judge": judge, "document": document, "labels": labels,
                             "incident_id": incident_id, "outage_ends_it": outage_ends_it})

        return overview

    return overview_of


def _dont_care_llm() -> LLMClient:
    """A model nothing here may call: the conversation is handed in."""
    return a_model_answering_in_turn()


def _overview_kept(expected: str) -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(synopsis: ExecutiveSynopsisDocument) -> bool:
        if synopsis.overview != expected or synopsis.withheld_because is not None:
            raise AssertionError(
                f"Expected the overview [{expected}], got [{synopsis.overview}] "
                f"withheld because [{synopsis.withheld_because}].")

        return True

    return assertion


def _overview_withheld_because(expected: str) -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(synopsis: ExecutiveSynopsisDocument) -> bool:
        if synopsis.overview is not None or synopsis.withheld_because != expected:
            raise AssertionError(
                f"Expected no overview, withheld because [{expected}], got "
                f"[{synopsis.overview}] withheld because [{synopsis.withheld_because}].")

        return True

    return assertion


def _asked_with(asked: Kept[dict[str, Any]],
                expected: dict[str, Any]) -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(_: ExecutiveSynopsisDocument) -> bool:
        if asked.only() != expected:
            raise AssertionError(f"Expected the overview asked with {expected}, "
                                 f"got {asked.only()}.")

        return True

    return assertion


def _asked_with_an_outage_ending_it(asked: Kept[dict[str, Any]],
                                    expected: bool) -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(_: ExecutiveSynopsisDocument) -> bool:
        handed = asked.only()["outage_ends_it"]
        if handed is not expected:
            raise AssertionError(f"Expected the overview asked with outage_ends_it "
                                 f"[{expected}], got [{handed}].")

        return True

    return assertion


def _asked_with_paging(asked: Kept[dict[str, Any]],
                       expected: Paging) -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(_: ExecutiveSynopsisDocument) -> bool:
        if asked.only()["paging"] is not expected:
            raise AssertionError(f"Expected the overview asked with paging [{expected}], "
                                 f"got [{asked.only()['paging']}].")

        return True

    return assertion


def _asked_as_disproven(asked: Kept[dict[str, Any]]) -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(_: ExecutiveSynopsisDocument) -> bool:
        if asked.only()["disproven"] is not True:
            raise AssertionError(f"Expected the overview asked as disproven, "
                                 f"got [{asked.only()['disproven']}].")

        return True

    return assertion


def _priced_as(expected: PricedResponse) -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(synopsis: ExecutiveSynopsisDocument) -> bool:
        # The synopsis's own fields beyond the pricing's are ignored.
        carried = PricedResponse.model_validate(synopsis.model_dump())
        if carried != expected:
            raise AssertionError(f"Expected the response carried as [{expected}], "
                                 f"got [{carried}].")

        return True

    return assertion


def _said_shared(expected: str | None) -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(synopsis: ExecutiveSynopsisDocument) -> bool:
        if synopsis.response_shared != expected:
            raise AssertionError(f"Expected the response said shared as [{expected}], "
                                 f"got [{synopsis.response_shared}].")

        return True

    return assertion
