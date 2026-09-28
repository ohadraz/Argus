"""What an earlier incident left in memory, staged for the walk that comes next.

Here rather than in the case that asserts on it, because two callers need the
same world. The e2e case seeds this and then asserts what the walk made of it;
`scripts/record_incident.py` has to seed the *same* thing when it captures the
corpus that case replays, or the recorded walk and the replayed one investigate
under different evidence - and a recording is a queue of answers served in order,
not a model reasoning afresh, so the divergence surfaces as the double running dry
somewhere nobody was looking.

The seeding goes through the walk's own writer rather than putting a document in
the collection. The shape a record is stored in belongs to `incident_memory`, and
a staging step that invented its own would let the writer drift from the reader
with every case still green.
"""

from __future__ import annotations

from argus_core import get_settings
from argus_core.embedding import an_embedder
from argus_core.models import REVERT_FEATURE_FLAG, ActionIdentity, Verdict
from incident_memory.keeping import kept_in
from incident_memory.records import RememberedIncident, WhatWasTried
from qdrant_client import QdrantClient

from tests.e2e.framework.argus import THE_SERVICE_NAME
from tests.e2e.framework.flags import THE_DEMO_FLAG

# An incident that is over, from long enough ago that nothing else is about it.
# Its id is arbitrary and never looked up: what a later walk reads is the list of
# what was tried.
AN_EARLIER_INCIDENT = "9c1d4e7a-0000-4000-8000-00000000fee1"

# What that earlier incident was described as. Close to what a flag incident on
# this service looks like - the same service, the same kind of failure, different
# words - because a search by similarity is exactly what has to bridge the
# difference. Measured against the query a walk actually builds from its alert and
# its first conclusion, this sits around 0.78 similarity against a floor of 0.5.
AS_IT_WAS_DESCRIBED = (
    "HighErrorRate on io-shop: checkout failures climbed sharply after a "
    "feature flag was switched on, and stayed up"
)


def that_flag_was_tried_before_and_did_not_help() -> None:
    """Files one finished incident whose flag revert was refuted.

    Returns nothing, which is what lets one function serve both callers: `calling`
    takes a step of any return type, and a recording's `and_then` is a plain
    procedure. A step that returned a verdict would have to be adapted at one of
    the two call sites, and the adapter is where the two worlds drift apart again.
    """
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
