"""The figures the executive synopsis's overview may name, each written as the
postmortem page writes it - so the synopsis and the page it links to never state
one figure two ways - and each said as the overview's prose says it.

Only figures the record holds are named: a figure nobody measured has no name,
so the overview cannot be asked for it or write one in.

Each case is one postmortem and the figures it gives.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import timedelta
from decimal import Decimal

import pytest
from argus_core.models import Impact, ImpactExtent, Postmortem, said_as_money
from argus_testkit import Assertion, Scenario
from postmortem_rendering.impact import the_impact
from postmortem_rendering.synopsis_figures import (
    the_synopsis_figures,
    the_synopsis_figures_said,
)

from postmortem_rendering_test.framework.builders import a_postmortem, an_alert

SOME_MINUTES = 7
SOME_SECONDS = 12
SOME_IMPACT = Impact(duration=timedelta(minutes=SOME_MINUTES, seconds=SOME_SECONDS),
                     extent=ImpactExtent.MEASURED, peak_error_rate=0.338, requests_failed=1240)
SOME_LOSS = Decimal("1840.005")
SOME_COST = Decimal("31.504")
SOME_CURRENCY = "usd"


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
            lambda: the_synopsis_figures(some_postmortem, an_alert())
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
            lambda: the_synopsis_figures(some_postmortem, an_alert())
        ) \
        .then(
            _names_as("duration", f"at least {SOME_MINUTES}m {SOME_SECONDS}s")
        )


@pytest.mark.unit
def test_the_response_is_named_by_its_people_minutes_and_cost_to_the_cent() -> None:
    some_responders = 3
    some_minutes = 42
    some_postmortem = a_postmortem(responders=some_responders, engineer_minutes=some_minutes,
                                   responder_cost_estimate=SOME_COST,
                                   responder_cost_currency=SOME_CURRENCY)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures(some_postmortem, an_alert())
        ) \
        .then(
            _names({"responders": str(some_responders),
                    "engineer_minutes": f"{some_minutes} min",
                    "responder_cost": said_as_money(SOME_COST, SOME_CURRENCY)})
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
            lambda: the_synopsis_figures(some_postmortem, an_alert())
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
        responders=some_responders, engineer_minutes=some_minutes, responder_cost_estimate=None)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures(some_postmortem, an_alert())
        ) \
        .then(
            _names({"duration": f"{some_minutes_down}m 0s",
                    "responders": str(some_responders),
                    "engineer_minutes": f"{some_minutes} min"})
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
            lambda: the_synopsis_figures(some_postmortem, an_alert())
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
            lambda: the_synopsis_figures_said(some_postmortem, an_alert())
        ) \
        .then(
            _names_exactly(the_synopsis_figures(some_postmortem, an_alert()).keys())
        )


@pytest.mark.unit
@pytest.mark.parametrize("extent, said", [
    (ImpactExtent.MEASURED, f"{SOME_MINUTES} minutes {SOME_SECONDS} seconds"),
    (ImpactExtent.AT_LEAST, f"at least {SOME_MINUTES} minutes {SOME_SECONDS} seconds"),
    (ImpactExtent.METRICS_MISSING, f"at least {SOME_MINUTES} minutes {SOME_SECONDS} seconds")
], ids=["measured", "still-not-back", "metrics-missing"])
def test_prose_says_the_duration_in_words_and_a_floor_as_a_floor(extent: ImpactExtent,
                                                                 said: str) -> None:
    # "For 7m 12s" reads as a machine wrote it; "at least" is the figure
    # wherever the tile says it.
    some_postmortem = a_postmortem(impact=SOME_IMPACT.model_copy(update={"extent": extent}))

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures_said(some_postmortem, an_alert())
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
            lambda: the_synopsis_figures_said(some_postmortem, an_alert())
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
            lambda: the_synopsis_figures_said(some_postmortem, an_alert())
        ) \
        .then(
            _names_as("engineer_minutes", "none")
        )


@pytest.mark.unit
@pytest.mark.parametrize("extent, said", [
    (ImpactExtent.MEASURED, ""),
    (ImpactExtent.AT_LEAST, " so far")
], ids=["measured", "a-floor"])
def test_prose_says_no_loss_as_an_amount(extent: ImpactExtent, said: str) -> None:
    # The tile's "none so far" written into an amount's slot read "the cost to
    # the shop's takings at none so far".
    no_loss = Decimal(0)
    some_postmortem = a_postmortem(impact=SOME_IMPACT.model_copy(update={"extent": extent}),
                                   customer_loss_estimate=no_loss,
                                   estimate_currency=SOME_CURRENCY)

    Scenario() \
        .given(
            some_postmortem
        ) \
        .when(
            lambda: the_synopsis_figures_said(some_postmortem, an_alert())
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
            lambda: the_synopsis_figures_said(some_postmortem, an_alert())
        ) \
        .then(
            _names_as(name, the_synopsis_figures(some_postmortem, an_alert())[name])
        )


def _a_postmortem_with_every_figure() -> Postmortem:
    """A postmortem the overview may name every figure of."""
    return a_postmortem(impact=SOME_IMPACT,
                        customer_loss_estimate=SOME_LOSS,
                        estimate_currency=SOME_CURRENCY, responders=3, engineer_minutes=42,
                        responder_cost_estimate=SOME_COST,
                        responder_cost_currency=SOME_CURRENCY)


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
