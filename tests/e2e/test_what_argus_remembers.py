"""What the stack remembers of an incident, and what it does with it next time.

Two halves of one mechanism, and only the whole stack can show either. The
record is composed from rows the walk wrote, embedded by a model that runs in
Argus's own process, and put in a collection nothing else here touches - which
is four pieces that a unit test can only assert separately.

The seeding is deliberately done **through the same writer the walk uses**. A
`given` that reached into the store and put a document there would be a test
asserting that the reader understands a shape the test itself invented, and the
writer could then drift from it forever with every case still green.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
import psycopg
import pytest
from argus_core import get_settings
from argus_core.embedding import an_embedder
from argus_core.events import CandidatesReordered
from argus_core.models import (
    REVERT_FEATURE_FLAG,
    ActionIdentity,
    IncidentStatus,
    Verdict,
)
from argus_incidents.repository import events
from argus_testkit import Assertion, Scenario, all_of, calling, eventually
from incident_memory.keeping import kept_in
from incident_memory.records import RememberedIncident, WhatWasTried
from incident_memory.store import recalled
from qdrant_client import QdrantClient

from tests.e2e.framework.argus import (
    DATABASE_URL,
    MITIGATION_TIMEOUT_SECONDS,
    RECORDED_FLAG_TOGGLE,
    RECORDED_FLAG_TOGGLE_RED_HERRING,
    REQUEST_TIMEOUT_SECONDS,
    TARGET_SERVICE_BASE_URL,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.flags import THE_DEMO_FLAG

# An incident that is over, from long enough ago that nothing else here is
# about it. Its id is arbitrary and never looked up: what a later walk reads is
# the list of what was tried.
AN_EARLIER_INCIDENT = "9c1d4e7a-0000-4000-8000-00000000fee1"

# What that earlier incident was described as. Close to what this one will look
# like - the same service, the same kind of failure, different words - because
# a search by similarity is exactly what has to bridge the difference.
AS_IT_WAS_DESCRIBED = (
    "HighErrorRate on io-shop: checkout failures climbed sharply after a "
    "feature flag was switched on, and stayed up"
)


@pytest.mark.e2e
def test_an_incident_that_ends_is_remembered_by_what_it_tried() -> None:
    # The write half, end to end. Argus changed a flag, the service recovered,
    # and what is filed is exactly that pair - the subject and the verdict -
    # because that is the part the next incident cannot work out for itself.
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name="HighErrorRate",
                                            severity="critical")

    Scenario() \
        .given(
            calling(_a_flag_was_toggled()),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                all_of(
                    argus_ended_with_status(IncidentStatus.MITIGATED),
                    _it_was_remembered_as_having_tried(THE_DEMO_FLAG,
                                                      Verdict.CONFIRMED)
                ),
                timeout=MITIGATION_TIMEOUT_SECONDS
            )
        )


@pytest.mark.e2e
def test_a_subject_an_earlier_incident_refuted_is_moved_down_the_list() -> None:
    # The read half, and the only thing memory is allowed to do to a walk. An
    # earlier incident changed this flag and the service stayed broken; this
    # incident's evidence points at it again, and it is still tried - but after
    # whatever the walk has no reason to doubt.
    #
    # The red-herring scenario is the one to run it against, because there the
    # flag really was toggled and really is not the cause: the reordering is
    # then the difference between reaching the actual explanation on the second
    # attempt and reaching it on the first.
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name="HighErrorRate",
                                            severity="critical")

    Scenario() \
        .given(
            calling(_that_flag_was_tried_before_and_did_not_help()),
            calling(_a_flag_was_toggled_but_is_not_the_cause()),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE_RED_HERRING))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                _the_order_was_changed_on(AN_EARLIER_INCIDENT),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _that_flag_was_tried_before_and_did_not_help() -> Callable[[], bool]:
    """Puts one finished incident into memory, through the walk's own writer.

    Not by writing a document into the collection. The shape a record is stored
    in belongs to `incident_memory`, and a `given` that invented its own would
    let the writer drift from the reader with every case still passing.
    """
    def seed_memory() -> bool:
        settings = get_settings()
        store = QdrantClient(url=settings.qdrant_url)

        try:
            kept_in(
                store,
                settings.incident_memory_collection,
                an_embedder(settings.incident_memory_embedding_model)
            )(
                RememberedIncident(
                    incident_id=AN_EARLIER_INCIDENT,
                    described_as=AS_IT_WAS_DESCRIBED,
                    service=THE_SERVICE_NAME,
                    alert_name="HighErrorRate",
                    tried=[
                        WhatWasTried(
                            identity=ActionIdentity(
                                action_type=REVERT_FEATURE_FLAG, subject=THE_DEMO_FLAG
                            ),
                            verdict=Verdict.REFUTED
                        )
                    ]
                )
            )
        finally:
            store.close()

        return True

    return seed_memory


def _a_flag_was_toggled() -> Callable[[], bool]:
    return _a_scenario_was_seeded("feature-flag-toggle")


def _a_flag_was_toggled_but_is_not_the_cause() -> Callable[[], bool]:
    return _a_scenario_was_seeded("flag-toggle-red-herring")


def _a_scenario_was_seeded(scenario_id: str) -> Callable[[], bool]:
    def seed_scenario() -> bool:
        response = httpx.post(
            f"{TARGET_SERVICE_BASE_URL}/scenario/seed",
            json={"scenario_id": scenario_id},
            timeout=REQUEST_TIMEOUT_SECONDS
        )

        return response.status_code == httpx.codes.OK

    return seed_scenario


def _it_was_remembered_as_having_tried(
    subject: str, verdict: Verdict
) -> Assertion[httpx.Response]:
    """What the collection holds for the incident that just ended.

    Searched rather than fetched by id, because searching is what a later walk
    does: a record that was written and cannot be found is, from where it
    matters, a record that was not written.
    """
    def assertion(response: httpx.Response) -> bool:
        incident_id = incident_id_from(response)
        settings = get_settings()
        store = QdrantClient(url=settings.qdrant_url)

        try:
            found = recalled(
                store,
                settings.incident_memory_collection,
                an_embedder(settings.incident_memory_embedding_model)(
                    [AS_IT_WAS_DESCRIBED]
                )[0],
                service=THE_SERVICE_NAME,
                limit=settings.incident_memory_recall_limit,
                floor=settings.incident_memory_similarity_floor
            )
        finally:
            store.close()

        remembered = [one for one in found if one.incident_id == incident_id]

        if not remembered:
            raise AssertionError(
                f"expected incident [{incident_id}] to have been remembered, "
                f"found {[one.incident_id for one in found]}"
            )

        tried = [(one.identity.subject, one.verdict) for one in remembered[0].tried]

        if (subject, verdict) not in tried:
            raise AssertionError(
                f"expected [{subject}] [{verdict}] among {tried}"
            )

        return True

    return assertion


def _the_order_was_changed_on(incident_id: str) -> Assertion[httpx.Response]:
    """That the walk said, on its own timeline, why it changed its order.

    Read from the account rather than from the order itself: which candidate
    the model offered second is the model's business, and what this is about is
    that memory moved one and said so.
    """
    def assertion(response: httpx.Response) -> bool:
        with psycopg.connect(DATABASE_URL) as conn:
            recorded = events.get_by_incident(conn, incident_id_from(response))

        said = [
            event for event in recorded if isinstance(event, CandidatesReordered)
        ]

        if not said:
            raise AssertionError(
                "expected the walk to say it changed its candidate order, "
                f"it said {sorted({event.kind for event in recorded})}"
            )

        if said[0].on_the_strength_of != incident_id:
            raise AssertionError(
                f"expected the order changed on [{incident_id}], "
                f"got [{said[0].on_the_strength_of}]"
            )

        return True

    return assertion
