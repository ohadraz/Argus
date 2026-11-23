"""The figures the executive synopsis's overview may name, each written as the
postmortem page writes it - so the synopsis and the page it links to never state
one figure two ways - and each said as the overview's prose says it.

Only figures the record holds are named: a figure nobody measured has no name,
so the overview cannot be asked for it or write one in. The response's cost is
the synopsis's own, priced before the figures are worded and handed in.

Each case is one postmortem, the response as priced, and the figures they give.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from argus_testkit import Assertion, Scenario
from core.models import (
    ErrorRateLevels,
    Impact,
    ImpactExtent,
    Postmortem,
    PricedResponse,
    TimelineEntry,
    TimelineMarker,
    TitleCost,
)
from narration import said_as_money
from postmortem_rendering.impact import the_impact
from postmortem_rendering.synopsis_figures import (
    the_synopsis_figures,
    the_synopsis_figures_said,
)

from postmortem_rendering_test.framework.builders import a_marker, a_postmortem, an_alert

SOME_MINUTES = 7
SOME_SECONDS = 12
SOME_IMPACT = Impact(duration=timedelta(minutes=SOME_MINUTES, seconds=SOME_SECONDS),
                     extent=ImpactExtent.MEASURED, peak_error_rate=0.338, requests_failed=1240)
SOME_LOSS = Decimal("1840.005")
SOME_COST = Decimal("31.504")
SOME_CURRENCY = "usd"
SOME_RESPONDERS = 3
SOME_RESPONSE_MINUTES = 42
SOME_TITLE = "Senior Kuki"
DONT_CARE_END = datetime(2026, 10, 21, 19, 30, tzinfo=UTC)

# The response priced in all - every title it held priced at its band.
SOME_PRICE = PricedResponse(responder_cost_estimate=SOME_COST,
                            responder_cost_currency=SOME_CURRENCY)
# What pricing leaves where nothing was priced in all: nobody responded, or a
# title no band covers.
NOTHING_PRICED = PricedResponse()


@pytest.mark.unit
def test_the_duration_and_the_loss_are_named_as_the_page_writes_them() -> None:
    some_postmortem = a_postmortem(impact=SOME_IMPACT,
                                   customer_loss_estimate=SOME_LOSS,
                                   estimate_currency=SOME_CURRENCY)
    the_page = the_impact(some_postmortem, an_alert())

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures(some_postmortem, an_alert(), NOTHING_PRICED)
        ) \
        .then(
            _names({"duration": the_page.cards[0].value,
                    "peak_error_rate": the_page.cards[1].value,
                    "customer_loss": the_page.cards[-1].value})
        )


@pytest.mark.unit
def test_a_floor_is_named_as_a_floor() -> None:
    # "At least" is the figure: said without it, a lower bound reads as final.
    dont_care_loss = Decimal("200")
    some_postmortem = a_postmortem(
        impact=SOME_IMPACT.model_copy(update={"extent": ImpactExtent.AT_LEAST}),
        customer_loss_estimate=dont_care_loss, estimate_currency=SOME_CURRENCY)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures(some_postmortem, an_alert(), NOTHING_PRICED)
        ) \
        .then(
            _names_as("duration", f"at least {SOME_MINUTES}m {SOME_SECONDS}s")
        )


@pytest.mark.unit
def test_the_response_is_named_by_its_people_minutes_and_cost_to_the_cent() -> None:
    some_postmortem = a_postmortem(responders=SOME_RESPONDERS,
                                   engineer_minutes=SOME_RESPONSE_MINUTES)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures(some_postmortem, an_alert(), SOME_PRICE)
        ) \
        .then(
            _names({"responders": str(SOME_RESPONDERS),
                    "engineer_minutes": f"{SOME_RESPONSE_MINUTES} min",
                    "responder_cost": said_as_money(SOME_COST, SOME_CURRENCY)})
        )


@pytest.mark.unit
def test_a_response_with_a_title_nothing_priced_names_no_cost() -> None:
    # The priced title's row has an amount, and the response in all has none:
    # a cost missing one title is wrong in the flattering direction, so none
    # is named and none can be asked for.
    some_priced_minutes = 30
    some_unpriced_minutes = SOME_RESPONSE_MINUTES - some_priced_minutes
    priced_in_part = PricedResponse(
        cost_by_title=[TitleCost(title=SOME_TITLE, responders=2, minutes=some_priced_minutes,
                                 midpoint=SOME_COST, minimum=SOME_COST, maximum=SOME_COST),
                       TitleCost(title=None, responders=1, minutes=some_unpriced_minutes,
                                 midpoint=None, minimum=None, maximum=None)],
        responder_cost_currency=SOME_CURRENCY)
    some_postmortem = a_postmortem(responders=SOME_RESPONDERS,
                                   engineer_minutes=SOME_RESPONSE_MINUTES)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures(some_postmortem, an_alert(), priced_in_part)
        ) \
        .then(
            _names_none_of(["responder_cost"])
        )


@pytest.mark.unit
def test_a_disproven_alarm_names_no_duration_harm_or_loss() -> None:
    # There was no stretch: named, the alert and the close read as an outage.
    some_responders = 1
    some_minutes = 9
    some_postmortem = a_postmortem(
        impact=Impact(duration=timedelta(0), extent=ImpactExtent.DISPROVEN,
                      peak_error_rate=None),
        responders=some_responders, engineer_minutes=some_minutes)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures(some_postmortem, an_alert(), NOTHING_PRICED)
        ) \
        .then(
            _names({"responders": str(some_responders),
                    "engineer_minutes": f"{some_minutes} min"})
        )


@pytest.mark.unit
def test_what_was_not_measured_is_not_named() -> None:
    # No loss estimated, no peak read, no response priced: none of them named,
    # so none can be asked for.
    some_minutes_down = 5
    some_responders = 2
    some_minutes = 20
    some_postmortem = a_postmortem(
        impact=Impact(duration=timedelta(minutes=some_minutes_down), extent=ImpactExtent.MEASURED,
                      peak_error_rate=None),
        responders=some_responders, engineer_minutes=some_minutes)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures(some_postmortem, an_alert(), NOTHING_PRICED)
        ) \
        .then(
            _names({"duration": f"{some_minutes_down}m 0s",
                    "responders": str(some_responders),
                    "engineer_minutes": f"{some_minutes} min"})
        )


@pytest.mark.unit
@pytest.mark.parametrize("rose", [False, None], ids=["no-rise", "not-told-apart"])
def test_a_peak_where_no_rise_was_measured_is_not_named(rose: bool | None) -> None:
    # The page shows the error rate's levels on one card there, not its peak:
    # named, the peak reads as a rise the page says nobody measured.
    dont_care_before = 0.0105
    dont_care_while_broken = 0.1832
    some_postmortem = a_postmortem(
        impact=SOME_IMPACT.model_copy(update={"error_rates": ErrorRateLevels(
            before=dont_care_before, while_broken=dont_care_while_broken, rose=rose)}))

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures(some_postmortem, an_alert(), NOTHING_PRICED)
        ) \
        .then(
            _names_none_of(["peak_error_rate"])
        )


@pytest.mark.unit
@pytest.mark.parametrize("responders, minutes", [(None, None), (0, 0)],
                         ids=["not-read", "nobody-paged"])
def test_no_response_names_no_response(responders: int | None, minutes: int | None) -> None:
    # Named where nobody was paged, "0" and "none" became "0 people responded,
    # and their time came to none" - false where a person ended it unpaged.
    some_postmortem = a_postmortem(impact=SOME_IMPACT, responders=responders,
                                   engineer_minutes=minutes)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures(some_postmortem, an_alert(), NOTHING_PRICED)
        ) \
        .then(
            _names_none_of(["responders", "engineer_minutes", "responder_cost"])
        )


@pytest.mark.unit
def test_prose_says_each_figure_the_tiles_name_and_no_other() -> None:
    # One name, one figure: the overview names a figure once and has it
    # written in as prose says it.
    some_postmortem = _a_postmortem_with_every_figure()

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures_said(some_postmortem, an_alert(), SOME_PRICE)
        ) \
        .then(
            _names_exactly(the_synopsis_figures(some_postmortem, an_alert(), SOME_PRICE).keys())
        )


@pytest.mark.unit
@pytest.mark.parametrize("extent, ended, said", [
    (ImpactExtent.MEASURED, True, f"{SOME_MINUTES} minutes {SOME_SECONDS} seconds"),
    (ImpactExtent.AT_LEAST, False, f"at least {SOME_MINUTES} minutes {SOME_SECONDS} seconds"),
    (ImpactExtent.METRICS_MISSING, False,
     f"at least {SOME_MINUTES} minutes {SOME_SECONDS} seconds"),
    (ImpactExtent.METRICS_MISSING, True, f"{SOME_MINUTES} minutes {SOME_SECONDS} seconds"),
    (ImpactExtent.METRICS_RESUMED, False, f"{SOME_MINUTES} minutes {SOME_SECONDS} seconds")
], ids=["measured", "still-not-back", "metrics-missing", "metrics-missing-reported-over",
        "metrics-resumed-not-back"])
def test_prose_says_the_duration_in_words_and_a_floor_as_a_floor(extent: ImpactExtent,
                                                                 ended: bool,
                                                                 said: str) -> None:
    # "For 7m 12s" reads as a machine wrote it; "at least" is the figure
    # wherever the tile says it - a stretch cut short with nothing ending it,
    # never one a person's report ended, nor the whole stretch the metrics
    # were missing for.
    some_postmortem = a_postmortem(impact=SOME_IMPACT.model_copy(update={"extent": extent}),
                                   timeline=_ended_at_its_close() if ended else [])

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures_said(some_postmortem, an_alert(), NOTHING_PRICED)
        ) \
        .then(
            _names_as("duration", said)
        )


@pytest.mark.unit
@pytest.mark.parametrize("minutes, unit", [(17, "minutes"), (1, "minute")],
                         ids=["minutes", "one-minute"])
def test_prose_says_what_the_responders_minutes_measure(minutes: int, unit: str) -> None:
    # Beside a seven-minute outage, seventeen minutes of responders' time
    # reads as a mistake unless it says what it counts.
    some_responders = 2
    some_postmortem = a_postmortem(responders=some_responders, engineer_minutes=minutes)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures_said(some_postmortem, an_alert(), NOTHING_PRICED)
        ) \
        .then(
            _names_as("engineer_minutes",
                      f"{minutes} {unit} (from each responder taking the page until the page "
                      f"was closed)")
        )


@pytest.mark.unit
def test_prose_says_no_minutes_as_none_and_says_nothing_of_a_page() -> None:
    # Nothing was counted, so nothing is said of what was counted.
    some_responders = 1
    some_postmortem = a_postmortem(responders=some_responders, engineer_minutes=0)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures_said(some_postmortem, an_alert(), NOTHING_PRICED)
        ) \
        .then(
            _names_as("engineer_minutes", "none")
        )


@pytest.mark.unit
@pytest.mark.parametrize("extent, ended, said", [
    (ImpactExtent.MEASURED, True, ""),
    (ImpactExtent.AT_LEAST, False, " so far"),
    (ImpactExtent.METRICS_MISSING, True, ""),
    (ImpactExtent.METRICS_RESUMED, False, " so far")
], ids=["measured", "a-floor", "metrics-missing-reported-over", "metrics-resumed-not-back"])
def test_prose_says_no_loss_as_an_amount(extent: ImpactExtent, ended: bool, said: str) -> None:
    # The tile's "none so far" written into an amount's slot read "the cost to
    # the shop's takings at none so far". "So far" wherever nothing ended the
    # incident, the takings still counting where the read stopped.
    no_loss = Decimal(0)
    some_postmortem = a_postmortem(impact=SOME_IMPACT.model_copy(update={"extent": extent}),
                                   timeline=_ended_at_its_close() if ended else [],
                                   customer_loss_estimate=no_loss,
                                   estimate_currency=SOME_CURRENCY)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures_said(some_postmortem, an_alert(), NOTHING_PRICED)
        ) \
        .then(
            _names_as("customer_loss", f"{said_as_money(no_loss, SOME_CURRENCY)}{said}")
        )


@pytest.mark.unit
@pytest.mark.parametrize("name", ["peak_error_rate", "customer_loss", "responders",
                                  "responder_cost"])
def test_prose_says_every_other_figure_as_its_tile_does(name: str) -> None:
    some_postmortem = _a_postmortem_with_every_figure()

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures_said(some_postmortem, an_alert(), SOME_PRICE)
        ) \
        .then(
            _names_as(name, the_synopsis_figures(some_postmortem, an_alert(), SOME_PRICE)[name])
        )


def _ended_at_its_close() -> list[TimelineEntry]:
    """A timeline marking the impact's end, as one is where the metrics or a
    person's report ended it - its instant nothing here reads."""
    return [a_marker(TimelineMarker.IMPACT_ENDS, DONT_CARE_END)]


def _a_postmortem_with_every_figure() -> Postmortem:
    """A postmortem the overview may name every figure of, beside `SOME_PRICE`."""
    return a_postmortem(impact=SOME_IMPACT,
                        customer_loss_estimate=SOME_LOSS,
                        estimate_currency=SOME_CURRENCY, responders=SOME_RESPONDERS,
                        engineer_minutes=SOME_RESPONSE_MINUTES)


def _names(expected: dict[str, str]) -> Assertion[dict[str, str]]:
    def assertion(figures: dict[str, str]) -> bool:
        if figures != expected:
            raise AssertionError(f"Expected the figures {expected}, got {figures}.")

        return True

    return assertion


def _names_exactly(names: Iterable[str]) -> Assertion[dict[str, str]]:
    expected = list(names)

    def assertion(figures: dict[str, str]) -> bool:
        if list(figures) != expected:
            raise AssertionError(f"Expected the names {expected}, got {list(figures)}.")

        return True

    return assertion


def _names_as(name: str, written: str) -> Assertion[dict[str, str]]:
    def assertion(figures: dict[str, str]) -> bool:
        if figures.get(name) != written:
            raise AssertionError(
                f"Expected [{name}] written as [{written}], got [{figures.get(name)}].")

        return True

    return assertion


def _names_none_of(names: list[str]) -> Assertion[dict[str, str]]:
    def assertion(figures: dict[str, str]) -> bool:
        named = [name for name in names if name in figures]
        if named:
            raise AssertionError(f"Expected none of {names} named, got {named} in {figures}.")

        return True

    return assertion
