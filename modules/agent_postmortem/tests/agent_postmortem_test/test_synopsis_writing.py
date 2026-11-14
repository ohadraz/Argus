"""The executive synopsis, written from the stored postmortem.

What the postmortem does not store - the minutes and the bands per title - is
read again here and shown only where it agrees with the postmortem's totals.
The overview is the conversation's, kept or given up there, and handed in -
naming the record's pull request wherever it names one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from agent_postmortem import SHARED_PAGE_ASSUMPTION_LABEL, EngagedResponder, NotPaged, PayBand
from agent_postmortem.synopsis_conversation import Overview
from agent_postmortem.synopsis_prompting import Paging
from agent_postmortem.synopsis_writing import Overviewing, write_executive_synopsis
from argus_core.llm import LLMClient
from argus_core.models import (
    ExecutiveSynopsisDocument,
    OpenedPullRequest,
    PostmortemDocument,
    TitleCost,
)
from argus_testkit import Assertion, Kept, Scenario, all_of

from agent_postmortem_test.framework.builders import (
    a_band_source_pricing,
    a_model_answering_in_turn,
    an_engagement_source_reporting_each,
    an_engagement_source_that_cannot_answer,
    some_sources,
)

SOME_SERVICE = "io-shop"
SOME_INCIDENT_ID = "6f1c2a8e-4b1d-4c6e-9a51-0d2f3b7e8c11"
SOME_CURRENCY = "USD"
SOME_TITLE = "Senior Kuki"

# A working year of 2,000 hours is 120,000 minutes, so a band whose midpoint
# is that many prices a minute at one - at half that at its bottom, and twice
# at its top.
WORKING_YEAR = 2000.0
MINUTES_A_WORKING_YEAR = Decimal(WORKING_YEAR) * 60
A_BAND = PayBand(minimum=MINUTES_A_WORKING_YEAR / 2, midpoint=MINUTES_A_WORKING_YEAR,
                 maximum=MINUTES_A_WORKING_YEAR * 2, currency=SOME_CURRENCY)
TWO_SENIORS = [EngagedResponder(minutes=10, job_title=SOME_TITLE),
               EngagedResponder(minutes=20, job_title=SOME_TITLE)]
THEIR_MINUTES = sum(senior.minutes for senior in TWO_SENIORS)
THEIR_ROW = TitleCost(title=SOME_TITLE, responders=len(TWO_SENIORS), minutes=THEIR_MINUTES,
                      midpoint=Decimal(THEIR_MINUTES), minimum=Decimal(THEIR_MINUTES) / 2,
                      maximum=Decimal(THEIR_MINUTES) * 2)

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
                                "labels": SOME_LABELS, "incident_id": SOME_INCIDENT_ID})
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
def test_a_breakdown_agreeing_with_the_postmortem_is_shown() -> None:
    Scenario() \
        .when(
            lambda: _the_synopsis_of(_a_postmortem_of_two_seniors())
        ) \
        .then(
            _broken_down_into([THEIR_ROW])
        )


@pytest.mark.unit
def test_a_breakdown_disagreeing_with_the_postmortem_is_left_out_and_said() -> None:
    # Somebody acknowledged after the postmortem was written.
    dont_care_minutes = 5
    a_third_senior = EngagedResponder(minutes=dont_care_minutes, job_title=SOME_TITLE)

    Scenario() \
        .when(
            lambda: _the_synopsis_of(_a_postmortem_of_two_seniors(),
                                     engaged=[*TWO_SENIORS, a_third_senior])
        ) \
        .then(
            _left_unmatched()
        )


@pytest.mark.unit
def test_a_response_that_cannot_be_read_again_is_left_out_and_said() -> None:
    Scenario() \
        .when(
            lambda: write_executive_synopsis(
                _a_postmortem_of_two_seniors(), incident_id=SOME_INCIDENT_ID,
                service=SOME_SERVICE, figures=SOME_FIGURES, said=SOME_FIGURES_SAID,
                resolution=SOME_RESOLUTION, document=SOME_DOCUMENT, labels=SOME_LABELS,
                sources=some_sources(engagement=an_engagement_source_that_cannot_answer(),
                                     bands=a_band_source_pricing({SOME_TITLE: A_BAND}),
                                     working_hours_a_year=WORKING_YEAR),
                llm=_dont_care_llm(), judge=_dont_care_llm(),
                overview_of=_an_overview_of(Overview(text=SOME_OVERVIEW)))
        ) \
        .then(
            _left_unmatched()
        )


@pytest.mark.unit
def test_a_response_nobody_was_paged_for_has_nothing_to_break_down() -> None:
    a_postmortem_nobody_responded_to = _a_postmortem_of_two_seniors().model_copy(update={
        "responders": 0, "engineer_minutes": 0, "responder_cost_estimate": None,
        "responder_cost_minimum": None, "responder_cost_maximum": None,
        "responder_cost_currency": None})

    Scenario() \
        .when(
            lambda: write_executive_synopsis(
                a_postmortem_nobody_responded_to, incident_id=SOME_INCIDENT_ID,
                service=SOME_SERVICE, figures=SOME_FIGURES, said=SOME_FIGURES_SAID,
                resolution=SOME_RESOLUTION, document=SOME_DOCUMENT, labels=SOME_LABELS,
                sources=some_sources(engagement=lambda dont_care_incident_id: NotPaged(),
                                     working_hours_a_year=WORKING_YEAR),
                llm=_dont_care_llm(), judge=_dont_care_llm(),
                overview_of=_an_overview_of(Overview(text=SOME_OVERVIEW)))
        ) \
        .then(
            all_of(
                _broken_down_into([]),
                _not_said_unmatched()
            )
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
                     engaged: list[EngagedResponder] | None = None,
                     judge: LLMClient | None = None) -> ExecutiveSynopsisDocument:
    """The synopsis of `postmortem`, its responders read again as `engaged` - the
    two seniors it was written from, unless a test says otherwise."""
    return write_executive_synopsis(
        postmortem, incident_id=SOME_INCIDENT_ID, service=SOME_SERVICE,
        figures=SOME_FIGURES, said=SOME_FIGURES_SAID, resolution=SOME_RESOLUTION,
        document=SOME_DOCUMENT, labels=SOME_LABELS,
        sources=some_sources(
            engagement=an_engagement_source_reporting_each(
                engaged if engaged is not None else TWO_SENIORS),
            bands=a_band_source_pricing({SOME_TITLE: A_BAND}),
            working_hours_a_year=WORKING_YEAR),
        llm=_dont_care_llm(),
        judge=judge if judge is not None else _dont_care_llm(),
        overview_of=(overview_of if overview_of is not None
                     else _an_overview_of(Overview(text=SOME_OVERVIEW))))


def _a_postmortem_of_two_seniors() -> PostmortemDocument:
    """A postmortem of the two seniors' response, priced at their band."""
    return PostmortemDocument(
        root_cause="dont care",
        cause_in_plain_words=SOME_CAUSE,
        symptom=SOME_SYMPTOM,
        executive_summary="dont care",
        customer_loss_estimate=None,
        estimate_currency=None,
        engineer_minutes=THEIR_ROW.minutes,
        responders=THEIR_ROW.responders,
        responder_cost_estimate=THEIR_ROW.midpoint,
        responder_cost_minimum=THEIR_ROW.minimum,
        responder_cost_maximum=THEIR_ROW.maximum,
        responder_cost_currency=SOME_CURRENCY,
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
                    incident_id: str) -> Overview:
        if asked_into is not None:
            asked_into.take({"service": service, "symptom": symptom, "cause": cause,
                             "figures": figures, "said": said, "paging": paging,
                             "disproven": disproven, "resolution": resolution,
                             "judge": judge, "document": document, "labels": labels,
                             "incident_id": incident_id})

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


def _broken_down_into(expected: list[TitleCost]) -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(synopsis: ExecutiveSynopsisDocument) -> bool:
        if synopsis.cost_by_title != expected or synopsis.breakdown_unmatched:
            raise AssertionError(
                f"Expected the breakdown {expected}, got {synopsis.cost_by_title} "
                f"with unmatched [{synopsis.breakdown_unmatched}].")

        return True

    return assertion


def _left_unmatched() -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(synopsis: ExecutiveSynopsisDocument) -> bool:
        if synopsis.cost_by_title or not synopsis.breakdown_unmatched:
            raise AssertionError(
                f"Expected no breakdown, said to be unmatched, got {synopsis.cost_by_title} "
                f"with unmatched [{synopsis.breakdown_unmatched}].")

        return True

    return assertion


def _said_shared(expected: str | None) -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(synopsis: ExecutiveSynopsisDocument) -> bool:
        if synopsis.response_shared != expected:
            raise AssertionError(f"Expected the response said shared as [{expected}], "
                                 f"got [{synopsis.response_shared}].")

        return True

    return assertion


def _not_said_unmatched() -> Assertion[ExecutiveSynopsisDocument]:
    def assertion(synopsis: ExecutiveSynopsisDocument) -> bool:
        if synopsis.breakdown_unmatched:
            raise AssertionError("Expected nothing said unmatched, since nobody responded, "
                                 "got it said.")

        return True

    return assertion
