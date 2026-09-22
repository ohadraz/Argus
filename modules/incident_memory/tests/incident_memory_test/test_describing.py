"""The text a later incident is compared against.

It is assembled rather than written. Nothing here is asked of a model: the
description's only job is to be matched against, and the alert's own words
beside what the investigation concluded embed to very nearly where a composed
sentence would - at no cost, with no failure mode, and reproducibly.

So every case below is about what reaches the text and what a missing piece
does to it. The alert is always there; the rest of an incident may not be, and
an incident that named no cause still has to be findable by the one thing it
did have.
"""

from __future__ import annotations

import pytest
from argus_testkit import Assertion, Scenario, all_of
from incident_memory.describing import what_it_looked_like

from incident_memory_test.framework.builders import a_hypothesis, an_alert


@pytest.mark.unit
def test_the_alerts_own_words_are_in_the_text() -> None:
    # What the monitoring called it. Two incidents with the same cause can be
    # named differently, which is why this is not the whole description - but a
    # search by the alert's wording has to find an incident that alert opened.
    the_alert_that_opened_it = "HighErrorRate"
    the_service_it_happened_to = "io-shop"
    what_the_alert_said = "error rate above 5% for 10 minutes"

    Scenario() \
        .given(an_alert(the_alert_that_opened_it,
                        the_service_it_happened_to,
                        what_the_alert_said)) \
        .when(lambda: what_it_looked_like(
            an_alert(the_alert_that_opened_it,
                     the_service_it_happened_to,
                     what_the_alert_said),
            a_hypothesis()
        )) \
        .then(all_of(
            _it_says(the_alert_that_opened_it),
            _it_says(the_service_it_happened_to),
            _it_says(what_the_alert_said)
        ))


@pytest.mark.unit
def test_what_the_investigation_concluded_is_in_the_text() -> None:
    # The half that makes two differently-named alerts match each other. The
    # conclusion is here to be searched by, not to be believed later: a new
    # incident derives its own cause, and this is only how it finds the old one.
    what_the_investigation_said = "the new-checkout-flow flag was switched on"

    Scenario() \
        .given(a_hypothesis(what_the_investigation_said)) \
        .when(lambda: what_it_looked_like(
            an_alert(),
            a_hypothesis(what_the_investigation_said)
        )) \
        .then(_it_says(what_the_investigation_said))


@pytest.mark.unit
def test_every_cited_observation_is_in_the_text() -> None:
    # The most specific words the incident produced, and so the ones most likely
    # to match a later incident that looked the same. Dropping the second would
    # make a description quietly depend on which observation came first.
    one_thing_that_was_seen = "error rate rose from 0.4% to 31% at 10:07"
    another_thing_that_was_seen = "payment calls began timing out"

    Scenario() \
        .given(a_hypothesis(observations=[one_thing_that_was_seen,
                                          another_thing_that_was_seen])) \
        .when(lambda: what_it_looked_like(
            an_alert(),
            a_hypothesis(observations=[one_thing_that_was_seen,
                                       another_thing_that_was_seen])
        )) \
        .then(all_of(
            _it_says(one_thing_that_was_seen),
            _it_says(another_thing_that_was_seen)
        ))


@pytest.mark.unit
def test_an_incident_that_named_no_cause_is_described_by_its_alert() -> None:
    # An escalation with nothing concluded is still worth finding: its record
    # says which subjects were changed and did not help, which is the part that
    # never depended on a cause being named.
    the_alert_that_opened_it = "HighErrorRate"
    what_the_alert_said = "error rate above 5% for 10 minutes"

    Scenario() \
        .given(an_alert(the_alert_that_opened_it, summary=what_the_alert_said)) \
        .when(lambda: what_it_looked_like(
            an_alert(the_alert_that_opened_it, summary=what_the_alert_said),
            None
        )) \
        .then(all_of(
            _it_says(the_alert_that_opened_it),
            _it_says(what_the_alert_said)
        ))


@pytest.mark.unit
def test_an_alert_that_said_nothing_leaves_no_gap_behind_it() -> None:
    # `Alert.summary` is optional and a real alert often omits it. Joined
    # blindly, the missing piece leaves a separator with nothing on either side
    # - which is a token the embedder is handed and a reader would call a bug.
    the_alert_that_opened_it = "HighErrorRate"

    Scenario() \
        .given(an_alert(the_alert_that_opened_it, summary=None)) \
        .when(lambda: what_it_looked_like(
            an_alert(the_alert_that_opened_it, summary=None),
            None
        )) \
        .then(all_of(
            _it_says(the_alert_that_opened_it),
            _it_reads_as_whole_lines()
        ))


def _it_says(expected: str) -> Assertion[str]:
    def assertion(described_as: str) -> bool:
        if expected not in described_as:
            raise AssertionError(f"Expected [{expected}] within [{described_as}].")

        return True

    return assertion


def _it_reads_as_whole_lines() -> Assertion[str]:
    def assertion(described_as: str) -> bool:
        empty = [line for line in described_as.splitlines() if not line.strip()]

        if empty:
            raise AssertionError(f"Expected no empty line within [{described_as}].")

        if described_as != described_as.strip():
            raise AssertionError(f"Expected nothing dangling around [{described_as}].")

        return True

    return assertion
