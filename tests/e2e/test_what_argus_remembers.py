"""What the stack remembers of an incident, and that the next one reaches for it.

Two halves of one mechanism, and only the whole stack can show either. The
record is composed from rows the walk wrote, embedded by a model that runs in
Argus's own process, and put in a collection nothing else here touches - which
is four pieces that a unit test can only assert separately.

The seeding is deliberately done **through the same writer the walk uses**, and
it lives in the framework rather than here: `scripts/record_incident.py` has to
stage the same world when it captures the corpus these cases replay. See
`tests.e2e.framework.memory`.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx2
import psycopg
import pytest
from argus_core import get_settings
from argus_core.embedding import an_embedder
from argus_core.events import SimilarIncidentsRecalled
from argus_core.models import IncidentStatus, Verdict
from argus_incidents.repository import events
from argus_testkit import Assertion, Scenario, all_of, calling, eventually
from incident_memory.store import recalled
from qdrant_client import QdrantClient

from tests.e2e.framework.argus import (
    DATABASE_URL,
    MITIGATION_TIMEOUT_SECONDS,
    RECORDED_FLAG_TOGGLE,
    RECORDED_FLAG_TOGGLE_RED_HERRING,
    THE_SERVICE_NAME,
    WALK_TIMEOUT_SECONDS,
    argus_ended_with_status,
    argus_is_triggered_with_alert,
    incident_id_from,
    the_model_answers_from,
)
from tests.e2e.framework.builders import a_grafana_style_alert_with
from tests.e2e.framework.flags import THE_DEMO_FLAG
from tests.e2e.framework.memory import (
    AN_EARLIER_INCIDENT,
    AS_IT_WAS_DESCRIBED,
    that_flag_was_tried_before_and_did_not_help,
)
from tests.e2e.framework.world import a_scenario_was_seeded


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
def test_an_earlier_incident_like_this_one_is_found_and_said() -> None:
    # The read half: an earlier incident on this service changed this flag and
    # the service stayed broken, and this walk has to find it. What is asserted
    # is the search, not what came of it. Whether the order then *changes* needs
    # a round that offered a second candidate to move the flag behind, and how
    # many candidates a round offers is the model's to decide - so an assertion
    # on the reordering is an assertion about the corpus's generosity, which is
    # how this case came to fail on a re-record that changed nothing here.
    #
    # The demotion itself is covered where it is deterministic: the walk's own
    # suite, and `incident_memory`'s.
    some_alert = a_grafana_style_alert_with(service=THE_SERVICE_NAME,
                                            alert_name="HighErrorRate",
                                            severity="critical")

    Scenario() \
        .given(
            calling(that_flag_was_tried_before_and_did_not_help),
            calling(a_scenario_was_seeded("flag-toggle-red-herring")),
            calling(the_model_answers_from(RECORDED_FLAG_TOGGLE_RED_HERRING))
        ) \
        .when(
            argus_is_triggered_with_alert(some_alert)
        ) \
        .then(
            eventually(
                _the_walk_said_it_recalled(AN_EARLIER_INCIDENT),
                timeout=WALK_TIMEOUT_SECONDS
            )
        )


def _a_flag_was_toggled() -> Callable[[], bool]:
    return a_scenario_was_seeded("feature-flag-toggle")


def _it_was_remembered_as_having_tried(
    subject: str, verdict: Verdict
) -> Assertion[httpx2.Response]:
    """What the collection holds for the incident that just ended.

    Searched rather than fetched by id, because searching is what a later walk
    does: a record that was written and cannot be found is, from where it
    matters, a record that was not written.
    """
    def assertion(response: httpx2.Response) -> bool:
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
                f"Expected incident [{incident_id}] to have been remembered, "
                f"found {[one.incident_id for one in found]}"
            )

        tried = [(one.identity.subject, one.verdict) for one in remembered[0].tried]

        if (subject, verdict) not in tried:
            raise AssertionError(
                f"Expected [{subject}] [{verdict}] among {tried}"
            )

        return True

    return assertion


def _the_walk_said_it_recalled(incident_id: str) -> Assertion[httpx2.Response]:
    """That the walk searched memory and, on its own timeline, named what it
    found.

    Read from the account rather than from the store, for the reason the write
    half reads from the store rather than the account: what is under test here is
    that the walk reached memory during the incident and said so, and a record
    sitting in a collection proves only that this test put it there.
    """
    def assertion(response: httpx2.Response) -> bool:
        with psycopg.connect(DATABASE_URL) as conn:
            recorded = events.get_by_incident(conn, incident_id_from(response))

        said = [
            event for event in recorded
            if isinstance(event, SimilarIncidentsRecalled)
        ]

        if not said:
            raise AssertionError(
                "Expected the walk to say what it recalled from memory, "
                f"it said {sorted({event.kind for event in recorded})}"
            )

        found = [one for event in said for one in event.incident_ids]

        if incident_id not in found:
            raise AssertionError(
                f"Expected incident [{incident_id}] among what was recalled, "
                f"got {found}."
            )

        return True

    return assertion
