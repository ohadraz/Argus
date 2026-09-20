"""Binding the model and the store together, which is where the pairing can break.

The store takes vectors and the walk has text, so something has to embed one
into the other - twice, once at each end. These cases are about that: whether
what is kept is the description's own vector, and whether the question is put
through the same model the records went through.

The embedder is a stand-in with an arrangement of its own, so "the same model
both times" is something a test can actually observe. Two vectors from two
models are two coordinate systems, and the distance between them is a number
that means nothing - which is exactly the failure that looks like an empty
corpus rather than like a bug.
"""

from __future__ import annotations

import pytest
from argus_core.embedding import Embedder
from argus_core.models import REVERT_FEATURE_FLAG, ActionIdentity, Verdict
from argus_testkit import Assertion, Scenario, all_of
from incident_memory.keeping import Recaller, kept_in, recalling_from
from incident_memory.records import RememberedIncident, WhatWasTried
from qdrant_client import QdrantClient

SOME_COLLECTION = "incidents"
SOME_SERVICE = "io-shop"

ENOUGH_ROOM_FOR_THEM_ALL = 10
NO_FLOOR_WORTH_MENTIONING = 0.0

# What each text embeds to, under the stand-in below. Two descriptions that
# should match sit near each other; the third sits well away from both.
WHAT_HAPPENED_HERE = "checkout began failing after a flag was switched on"
WHAT_HAPPENED_BEFORE = "checkout failures followed a feature flag change"
SOMETHING_ELSE_ENTIRELY = "the warehouse label printer ran out of paper"

_VECTORS = {
    WHAT_HAPPENED_HERE: [1.0, 0.0, 0.0, 0.0],
    WHAT_HAPPENED_BEFORE: [0.9, 0.1, 0.0, 0.0],
    SOMETHING_ELSE_ENTIRELY: [0.0, 0.0, 0.0, 1.0]
}


@pytest.mark.component
def test_a_record_is_found_by_a_description_that_means_the_same_thing(
    store: QdrantClient
) -> None:
    # The whole arrangement in one case: a record kept under one description is
    # reached by a different description that embeds near it. Neither end names
    # a vector, which is what the binding is for.
    the_incident_that_happened_before = "the-flag-one"

    kept_in(store, SOME_COLLECTION, _an_embedder())(
        _an_incident(the_incident_that_happened_before, WHAT_HAPPENED_BEFORE)
    )

    Scenario() \
        .given(store) \
        .when(lambda: _recalling(store)(WHAT_HAPPENED_HERE, SOME_SERVICE)) \
        .then(_these_incidents_come_back([the_incident_that_happened_before]))


@pytest.mark.component
def test_a_record_about_something_else_is_not_reached(store: QdrantClient) -> None:
    # The other half of the same claim. A search that returned this one would
    # mean the description was never what the record was stored under - which a
    # test asserting only the match above would not notice.
    the_one_about_something_else = "the-printer-one"
    a_floor_it_does_not_clear = 0.5

    kept_in(store, SOME_COLLECTION, _an_embedder())(
        _an_incident(the_one_about_something_else, SOMETHING_ELSE_ENTIRELY)
    )

    Scenario() \
        .given(store) \
        .when(lambda: _recalling(store, floor=a_floor_it_does_not_clear)(
            WHAT_HAPPENED_HERE, SOME_SERVICE
        )) \
        .then(_these_incidents_come_back([]))


@pytest.mark.component
def test_the_whole_record_comes_back_not_just_what_it_was_found_by(store: QdrantClient) -> None:
    # The record goes through an embedder and a store and comes back whole. It
    # is the list of attempts that a later ordering reads, and a binding that
    # kept only what it searched by would be a memory of nothing.
    the_flag_that_did_not_help = "new-checkout-flow"

    kept_in(store, SOME_COLLECTION, _an_embedder())(
        _an_incident("the-flag-one",
                     WHAT_HAPPENED_BEFORE,
                     tried=[(the_flag_that_did_not_help, Verdict.REFUTED)])
    )

    Scenario() \
        .given(store) \
        .when(lambda: _recalling(store)(WHAT_HAPPENED_HERE, SOME_SERVICE)) \
        .then(all_of(
            _it_remembers_trying(the_flag_that_did_not_help),
            _it_remembers_the_verdict(Verdict.REFUTED)
        ))


def _an_embedder() -> Embedder:
    """A model with an arrangement instead of weights.

    Every text it is given is one of the three above, so what a description
    embeds to is decided by this test rather than by how a sentence happens to
    land - which is what makes "near" and "far" facts here rather than hopes.
    """
    def embed(texts: list[str], /) -> list[list[float]]:
        return [_VECTORS[text] for text in texts]

    return embed


def _recalling(store: QdrantClient,
               floor: float = NO_FLOOR_WORTH_MENTIONING) -> Recaller:
    return recalling_from(
        store,
        SOME_COLLECTION,
        _an_embedder(),
        limit=ENOUGH_ROOM_FOR_THEM_ALL,
        floor=floor
    )


def _an_incident(incident_id: str,
                 described_as: str,
                 tried: list[tuple[str, Verdict]] | None = None) -> RememberedIncident:
    return RememberedIncident(
        incident_id=incident_id,
        described_as=described_as,
        service=SOME_SERVICE,
        alert_name="HighErrorRate",
        tried=[
            WhatWasTried(
                identity=ActionIdentity(
                    action_type=REVERT_FEATURE_FLAG, subject=subject
                ),
                verdict=verdict
            )
            for subject, verdict in (tried if tried is not None else [("a-flag", Verdict.REFUTED)])
        ]
    )


def _these_incidents_come_back(expected: list[str]) -> Assertion[list[RememberedIncident]]:
    def assertion(remembered: list[RememberedIncident]) -> bool:
        came_back = [incident.incident_id for incident in remembered]

        if came_back != expected:
            raise AssertionError(f"expected {expected}, got {came_back}")

        return True

    return assertion


def _it_remembers_trying(subject: str) -> Assertion[list[RememberedIncident]]:
    def assertion(remembered: list[RememberedIncident]) -> bool:
        subjects = [
            attempt.identity.subject
            for incident in remembered for attempt in incident.tried
        ]

        if subject not in subjects:
            raise AssertionError(f"expected [{subject}] among {subjects}")

        return True

    return assertion


def _it_remembers_the_verdict(verdict: Verdict) -> Assertion[list[RememberedIncident]]:
    def assertion(remembered: list[RememberedIncident]) -> bool:
        verdicts = [attempt.verdict for incident in remembered for attempt in incident.tried]

        if verdict not in verdicts:
            raise AssertionError(f"expected [{verdict}] among {verdicts}")

        return True

    return assertion
