"""What the response cost: the people's minutes and what they were, and Argus's
tokens - never money, which divided by the minutes beside it is a rate of pay.

Each case is one postmortem and the cards the section says it as.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from argus_testkit import Scenario, the_answer_was
from postmortem_rendering.cost import the_cost
from postmortem_rendering.impact import Card

from postmortem_rendering_test.framework.builders import a_postmortem


@pytest.mark.unit
def test_the_minutes_say_how_many_responded_and_what_they_were_beside_argus_s_tokens() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(engineer_minutes=47, responders=2,
                                            responder_titles=["SRE", "Backend Engineer"],
                                            tokens_spent=81_402)
        ) \
        .when(
            lambda: the_cost(some_postmortem)
        ) \
        .then(
            the_answer_was((Card(value="47 min",
                                 label="engineer time, 2 responders (SRE, Backend Engineer)"),
                            Card(value="81,402", label="tokens spent by Argus"))))


@pytest.mark.unit
def test_one_responder_is_one_responder() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(engineer_minutes=12, responders=1,
                                            responder_titles=[])
        ) \
        .when(
            lambda: the_cost(some_postmortem)[0].label
        ) \
        .then(
            the_answer_was("engineer time, 1 responder"))


@pytest.mark.unit
def test_nothing_recorded_says_so() -> None:
    Scenario() \
        .given(
            some_postmortem := a_postmortem(engineer_minutes=None, responders=None,
                                            tokens_spent=None)
        ) \
        .when(
            lambda: the_cost(some_postmortem)
        ) \
        .then(
            the_answer_was((Card(value="not recorded", label="engineer time"),
                            Card(value="not recorded", label="tokens spent by Argus"))))


@pytest.mark.unit
def test_what_the_minutes_cost_in_pay_is_never_said() -> None:
    # Divided by the minutes, any figure for it is a responder's rate of pay -
    # and with one responder and their title beside it, that person's band.
    Scenario() \
        .given(
            some_postmortem := a_postmortem(engineer_minutes=47, responders=1,
                                            responder_cost_estimate=Decimal("311.00"),
                                            responder_cost_minimum=Decimal("208.00"),
                                            responder_cost_maximum=Decimal("492.00"),
                                            responder_cost_currency="usd")
        ) \
        .when(
            lambda: " ".join(f"{card.value} {card.label}" for card in the_cost(some_postmortem))
        ) \
        .then(
            the_answer_was("47 min engineer time, 1 responder not recorded tokens spent by Argus"))
