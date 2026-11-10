"""The executive synopsis as a reader reads it, worked out once for the Slack
message.

Every figure is the postmortem page's own, worded by the same code, so the
synopsis and the page it links to never state one figure two ways. The human
cost is the one part the page does not have: per title, with its range, a
total that is the stored postmortem's to the cent, and the basis it rests on.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from argus_core import new_id
from argus_core.models import (
    ExecutiveSynopsis,
    Impact,
    ImpactExtent,
    Postmortem,
    TimelineMarker,
    TitleCost,
    said_as_money,
)
from argus_testkit import Assertion, Scenario, all_of
from postmortem_rendering.head import a_head
from postmortem_rendering.impact import the_impact
from postmortem_rendering.resolution import ReportedResolution
from postmortem_rendering.resolution_list import the_resolution_list
from postmortem_rendering.synopsis import CostRow, SynopsisLines, the_synopsis

from postmortem_rendering_test.framework.builders import a_marker, a_postmortem, an_alert


def _the_sum_of(amounts: Iterable[Decimal | None]) -> Decimal | None:
    """Every amount added - or none, where any one is none, as a total missing
    a responder is never a partial sum."""
    counted = list(amounts)
    if any(amount is None for amount in counted):
        return None

    return sum((amount for amount in counted if amount is not None), Decimal(0))


def _a_title_cost(title: str | None,
                  responders: int,
                  minutes: int,
                  midpoint: Decimal | None) -> TitleCost:
    """A title's share of the response, its band half its midpoint to twice it
    - or unpriced, where `midpoint` is `None`."""
    return TitleCost(title=title, responders=responders, minutes=minutes, midpoint=midpoint,
                     minimum=midpoint / 2 if midpoint is not None else None,
                     maximum=midpoint * 2 if midpoint is not None else None)


def _their_total(costs: list[TitleCost]) -> TitleCost:
    """What `costs` come to together, as the postmortem stores the total."""
    return TitleCost(title="Total",
                     responders=sum(cost.responders for cost in costs),
                     minutes=sum(cost.minutes for cost in costs),
                     midpoint=_the_sum_of(cost.midpoint for cost in costs),
                     minimum=_the_sum_of(cost.minimum for cost in costs),
                     maximum=_the_sum_of(cost.maximum for cost in costs))


SOME_OVERVIEW = "Checkout failed after a flag change."
SOME_ADDRESS = "https://argus.example/incidents/kuki/postmortem"
SOME_CURRENCY = "USD"
SOME_BEGINNING = datetime(2026, 11, 9, 14, 3, tzinfo=UTC)
SOME_MINUTES = 7
SOME_SECONDS = 12
SOME_DURATION_SAID = f"{SOME_MINUTES}m {SOME_SECONDS}s"
SOME_IMPACT = Impact(duration=timedelta(minutes=SOME_MINUTES, seconds=SOME_SECONDS),
                     extent=ImpactExtent.MEASURED, peak_error_rate=0.338, requests_failed=1240)
# What the page says a responder with no title was, in the row of their own.
NO_TITLE_RECORDED = "No title recorded"

TWO_TITLES = [
    _a_title_cost("Senior Kuki", responders=2, minutes=30, midpoint=Decimal("25.00")),
    _a_title_cost("Junior Buki", responders=1, minutes=12, midpoint=Decimal("6.00"))
]
THEIR_TOTAL = _their_total(TWO_TITLES)
SOME_BASIS = ["Working year: annual pay bands divided by 2000 hours",
              *(f"Pay band: {cost.title} priced at the midpoint of the title's band"
                for cost in TWO_TITLES)]


@pytest.mark.unit
def test_the_parts_are_read_in_the_order_a_reader_asks_them() -> None:
    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(), _a_priced_postmortem(), an_alert(), None,
                                 SOME_ADDRESS)
        ) \
        .then(
            _headed(["overview", "when", "impact", "resolution", "human-cost"])
        )


@pytest.mark.unit
def test_the_overview_is_the_model_s_prose_as_it_was_kept() -> None:
    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(), _a_priced_postmortem(), an_alert(), None,
                                 SOME_ADDRESS)
        ) \
        .then(
            _overview_says(SOME_OVERVIEW)
        )


@pytest.mark.unit
@pytest.mark.parametrize("extent, lasted", [
    (ImpactExtent.MEASURED, f" ({SOME_DURATION_SAID})"),
    (ImpactExtent.AT_LEAST, f" (at least {SOME_DURATION_SAID})")
], ids=["measured", "a-floor"])
def test_when_it_happened_is_the_postmortem_s_window_in_utc_and_how_long_it_lasted(
        extent: ImpactExtent, lasted: str) -> None:
    # From and to alone leave the reader to subtract; how long is what a
    # reader of When wants first, as the duration's tile says it.
    some_postmortem = _a_priced_postmortem(impact=SOME_IMPACT.model_copy(
        update={"extent": extent}))

    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(), some_postmortem, an_alert(), None, SOME_ADDRESS)
        ) \
        .then(
            _the_window_is(f"{a_head(some_postmortem, an_alert(), None).date.said}{lasted}")
        )


@pytest.mark.unit
def test_a_disproven_alarm_s_when_says_no_duration() -> None:
    # It had no stretch: the alert and the close, as the page says them.
    some_postmortem = _a_priced_postmortem(
        impact=Impact(duration=timedelta(0), extent=ImpactExtent.DISPROVEN,
                      peak_error_rate=None))

    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(), some_postmortem, an_alert(), None, SOME_ADDRESS)
        ) \
        .then(
            _the_window_is(a_head(some_postmortem, an_alert(), None).date.said)
        )


@pytest.mark.unit
@pytest.mark.parametrize("impact", [
    SOME_IMPACT,
    Impact(duration=timedelta(0), extent=ImpactExtent.DISPROVEN, peak_error_rate=None)
], ids=["measured", "disproven"])
def test_the_impact_is_the_postmortem_page_s_own_cards(impact: Impact) -> None:
    # A disproven alarm's too: no stretch, no harm and no loss, as the page
    # says of one.
    some_postmortem = _a_priced_postmortem(impact=impact)

    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(), some_postmortem, an_alert(), None, SOME_ADDRESS)
        ) \
        .then(
            _the_impact_is(the_impact(some_postmortem, an_alert()).cards)
        )


@pytest.mark.unit
@pytest.mark.parametrize("resolution", [
    None,
    ReportedResolution(by="Dana Kuki", channel="Slack", at=SOME_BEGINNING, note=None)
], ids=["argus-ended-it", "a-person-ended-it"])
def test_the_resolution_is_the_list_of_what_was_done_and_by_whom(
        resolution: ReportedResolution | None) -> None:
    some_postmortem = _a_priced_postmortem()

    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(), some_postmortem, an_alert(), resolution,
                                 SOME_ADDRESS)
        ) \
        .then(
            _the_resolution_is(the_resolution_list(some_postmortem, resolution))
        )


@pytest.mark.unit
def test_each_title_is_a_row_beside_the_stored_total_and_the_basis() -> None:
    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(), _a_priced_postmortem(), an_alert(), None,
                                 SOME_ADDRESS)
        ) \
        .then(all_of(
            _rows_are([_a_row_of(cost) for cost in TWO_TITLES]),
            _total_is(_a_row_of(THEIR_TOTAL)),
            _notes_are(SOME_BASIS)
        ))


@pytest.mark.unit
def test_a_single_row_stands_without_a_total_beneath_it() -> None:
    # A total equal to the one row above it says the row twice - "not priced"
    # three times over, with the basis line, where nothing could price it.
    one_title = [_a_title_cost(None, responders=2, minutes=17, midpoint=None)]
    its_total = _their_total(one_title)
    an_unpriced_postmortem = _a_priced_postmortem(
        responders=its_total.responders, engineer_minutes=its_total.minutes,
        responder_cost_estimate=None, responder_cost_minimum=None,
        responder_cost_maximum=None, responder_cost_currency=None, response_cost_basis=[])

    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(cost_by_title=one_title), an_unpriced_postmortem,
                                 an_alert(), None, SOME_ADDRESS)
        ) \
        .then(all_of(
            _rows_are([_a_row_of(cost) for cost in one_title]),
            _no_total_beneath_one_row()
        ))


@pytest.mark.unit
def test_rows_that_each_round_down_still_add_up_to_the_total() -> None:
    # A third of a dollar three times rounds to 0.33 three times, and a reader
    # adding the rows finds a cent missing from the total beside them.
    the_whole = Decimal(1)
    a_third = the_whole / 3
    some_rows = [TitleCost(title=title, responders=1, minutes=10, midpoint=a_third,
                           minimum=a_third, maximum=a_third)
                 for title in ("Kuki", "Buki", "Muki")]
    their_total = _their_total(some_rows)
    some_postmortem = _a_priced_postmortem(responders=their_total.responders,
                                           engineer_minutes=their_total.minutes,
                                           responder_cost_estimate=the_whole,
                                           responder_cost_minimum=the_whole,
                                           responder_cost_maximum=the_whole)

    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(cost_by_title=some_rows), some_postmortem,
                                 an_alert(), None, SOME_ADDRESS)
        ) \
        .then(
            _midpoints_are([f"0.34 {SOME_CURRENCY}", f"0.33 {SOME_CURRENCY}",
                            f"0.33 {SOME_CURRENCY}"])
        )


@pytest.mark.unit
def test_a_responder_with_no_title_and_a_title_nothing_priced_keep_their_rows() -> None:
    # Counted, not priced: the basis says which title nothing could price.
    some_unpriced_title = "Principal Buki"
    some_rows = [_a_title_cost(None, responders=1, minutes=9, midpoint=None),
                 _a_title_cost(some_unpriced_title, responders=1, minutes=12, midpoint=None)]
    their_total = _their_total(some_rows)
    some_basis = ["Unpriced title: no responder cost, because no pay band covers "
                  f"[{some_unpriced_title}]"]
    an_unpriced_postmortem = _a_priced_postmortem(
        responders=their_total.responders, engineer_minutes=their_total.minutes,
        responder_cost_estimate=None, responder_cost_minimum=None,
        responder_cost_maximum=None, responder_cost_currency=None,
        response_cost_basis=some_basis)

    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(cost_by_title=some_rows), an_unpriced_postmortem,
                                 an_alert(), None, SOME_ADDRESS)
        ) \
        .then(all_of(
            _rows_are([_a_row_of(cost) for cost in some_rows]),
            _total_is(_a_row_of(their_total)),
            _notes_are(some_basis)
        ))


@pytest.mark.unit
def test_a_breakdown_that_could_not_be_matched_shows_the_totals_and_says_so() -> None:
    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(cost_by_title=[], breakdown_unmatched=True),
                                 _a_priced_postmortem(), an_alert(), None, SOME_ADDRESS)
        ) \
        .then(all_of(
            _rows_are([]),
            _total_is(_a_row_of(THEIR_TOTAL)),
            _a_note_says("could not be matched")
        ))


@pytest.mark.unit
def test_a_response_shared_with_other_incidents_is_said_beside_the_cost() -> None:
    some_sharing = ("Shared page: the on-call incident this one was paged under was also "
                    "about 1 other incident")

    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(response_shared=some_sharing),
                                 _a_priced_postmortem(), an_alert(), None, SOME_ADDRESS)
        ) \
        .then(
            _a_note_says(some_sharing)
        )


@pytest.mark.unit
@pytest.mark.parametrize("responders, paged, said", [
    (0, False, "Nobody was paged for this incident."),
    (0, True, "Somebody was paged for this incident, and nobody acknowledged the page."),
    (None, None, "could not be read")
], ids=["nobody-paged", "page-unacknowledged", "source-unread"])
def test_no_response_has_no_cost_and_says_why(responders: int | None, paged: bool | None,
                                             said: str) -> None:
    # The postmortem records nobody responding as none and an on-call source
    # it could not read as unknown - and whether a page went out, which tells
    # a page nobody acknowledged from no page at all. Three blanks, said apart.
    no_response = _a_priced_postmortem(
        responders=responders, engineer_minutes=responders, paged=paged,
        responder_cost_estimate=None, responder_cost_minimum=None,
        responder_cost_maximum=None, responder_cost_currency=None, response_cost_basis=[])

    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(cost_by_title=[]), no_response, an_alert(), None,
                                 SOME_ADDRESS)
        ) \
        .then(all_of(
            _rows_are([]),
            _no_total(),
            _a_note_says(said)
        ))


@pytest.mark.unit
def test_the_customer_loss_and_the_responder_cost_are_never_one_figure() -> None:
    # The business and the people are two costs: added, the figure says
    # neither.
    some_loss = Decimal("100.00")
    some_postmortem = _a_priced_postmortem(customer_loss_estimate=some_loss,
                                           estimate_currency=SOME_CURRENCY)

    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(), some_postmortem, an_alert(), None, SOME_ADDRESS)
        ) \
        .then(
            _says_nowhere(f"{_the_sum_of([some_loss, THEIR_TOTAL.midpoint])}")
        )


@pytest.mark.unit
@pytest.mark.parametrize("address", [SOME_ADDRESS, None], ids=["configured", "not-configured"])
def test_the_postmortem_is_linked_where_its_address_is_known(address: str | None) -> None:
    Scenario() \
        .when(
            lambda: the_synopsis(_a_synopsis(), _a_priced_postmortem(), an_alert(), None,
                                 address)
        ) \
        .then(
            _links_to(address)
        )


def _a_synopsis(**differing: Any) -> ExecutiveSynopsis:
    """A synopsis of the two titles' response, with its overview kept - and
    whatever a case says differs."""
    return ExecutiveSynopsis(id=new_id(), incident_id=new_id(),
                             created_at=SOME_BEGINNING + timedelta(hours=1),
                             overview=SOME_OVERVIEW,
                             cost_by_title=TWO_TITLES).model_copy(update=differing)


def _a_priced_postmortem(**differing: Any) -> Postmortem:
    """A postmortem of the two titles' response, priced at their total, with a
    measured window - and whatever a case says differs."""
    return a_postmortem(
        impact=SOME_IMPACT,
        timeline=[a_marker(TimelineMarker.IMPACT_BEGINS, SOME_BEGINNING),
                  a_marker(TimelineMarker.IMPACT_ENDS, SOME_BEGINNING + SOME_IMPACT.duration)],
        responders=THEIR_TOTAL.responders,
        engineer_minutes=THEIR_TOTAL.minutes,
        responder_cost_estimate=THEIR_TOTAL.midpoint,
        responder_cost_minimum=THEIR_TOTAL.minimum,
        responder_cost_maximum=THEIR_TOTAL.maximum,
        responder_cost_currency=SOME_CURRENCY
    ).model_copy(update={"response_cost_basis": SOME_BASIS, **differing})


def _a_row_of(cost: TitleCost) -> CostRow:
    """The row `cost` is shown as: its people, its minutes, and its cost at the
    midpoint with the range - neither where nothing priced it."""
    return CostRow(
        title=cost.title if cost.title is not None else NO_TITLE_RECORDED,
        people=cost.responders,
        minutes=f"{cost.minutes} min",
        midpoint=(said_as_money(cost.midpoint, SOME_CURRENCY)
                  if cost.midpoint is not None else None),
        range=(f"{said_as_money(cost.minimum, None)} to "
               f"{said_as_money(cost.maximum, SOME_CURRENCY)}"
               if cost.minimum is not None and cost.maximum is not None else None))


def _headed(expected: list[str]) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if list(synopsis.headings) != expected:
            raise AssertionError(f"Expected the parts {expected}, got {list(synopsis.headings)}.")

        return True

    return assertion


def _overview_says(expected: str) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if synopsis.overview.said != expected:
            raise AssertionError(
                f"Expected the overview [{expected}], got [{synopsis.overview.said}].")

        return True

    return assertion


def _the_window_is(expected: str) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if synopsis.window.said != expected or "UTC" not in synopsis.window.said:
            raise AssertionError(
                f"Expected the window [{expected}] in UTC, got [{synopsis.window.said}].")

        return True

    return assertion


def _the_impact_is(expected: Any) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if synopsis.impact != expected:
            raise AssertionError(f"Expected the page's cards {expected}, got {synopsis.impact}.")

        return True

    return assertion


def _the_resolution_is(expected: tuple[str, ...]) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if synopsis.resolution != expected:
            raise AssertionError(
                f"Expected the resolution {expected}, got {synopsis.resolution}.")

        return True

    return assertion


def _rows_are(expected: list[CostRow]) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if list(synopsis.human_cost.rows) != expected:
            raise AssertionError(
                f"Expected the rows {expected}, got {list(synopsis.human_cost.rows)}.")

        return True

    return assertion


def _total_is(expected: CostRow) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if synopsis.human_cost.total != expected:
            raise AssertionError(
                f"Expected the total {expected}, got {synopsis.human_cost.total}.")

        return True

    return assertion


def _no_total() -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if synopsis.human_cost.total is not None:
            raise AssertionError(
                f"Expected no total, since nobody responded, got {synopsis.human_cost.total}.")

        return True

    return assertion


def _no_total_beneath_one_row() -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if synopsis.human_cost.total is not None:
            raise AssertionError(f"Expected no total beneath the one row, which says it "
                                 f"already, got {synopsis.human_cost.total}.")

        return True

    return assertion


def _midpoints_are(expected: list[str | None]) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        midpoints = [row.midpoint for row in synopsis.human_cost.rows]
        if midpoints != expected:
            raise AssertionError(f"Expected the midpoints {expected}, got {midpoints}.")

        return True

    return assertion


def _notes_are(expected: list[str]) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if list(synopsis.human_cost.notes) != expected:
            raise AssertionError(
                f"Expected the notes {expected}, got {list(synopsis.human_cost.notes)}.")

        return True

    return assertion


def _a_note_says(expected: str) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if not any(expected in note for note in synopsis.human_cost.notes):
            raise AssertionError(f"Expected a note saying [{expected}], got "
                                 f"{list(synopsis.human_cost.notes)}.")

        return True

    return assertion


def _says_nowhere(unexpected: str) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if unexpected in synopsis.model_dump_json():
            raise AssertionError(f"Expected [{unexpected}] nowhere in the synopsis, got "
                                 f"{synopsis.model_dump_json()}.")

        return True

    return assertion


def _links_to(expected: str | None) -> Assertion[SynopsisLines]:
    def assertion(synopsis: SynopsisLines) -> bool:
        if synopsis.postmortem_at != expected:
            raise AssertionError(f"Expected the postmortem linked at [{expected}], got "
                                 f"[{synopsis.postmortem_at}].")

        return True

    return assertion
