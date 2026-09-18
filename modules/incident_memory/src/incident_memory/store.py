"""Records, in and out of the store that holds them.

The only module here that knows Qdrant exists. Everything above it deals in
`RememberedIncident`, so what is stored and what comes back stay this module's
vocabulary to translate rather than a vendor's shape leaking up into the walk.

Two questions, which are the only two long-term memory asks: keep this, and what
do you have like this. There is no delete and no re-index - a record describes an
incident that is over, and an incident that is over does not change.

The collection is made on the first write. A store that has never been written to
is the ordinary state of a first deployment, and a memory that refused to serve
until somebody had run a setup step would be a memory nobody has.
"""

from __future__ import annotations

from typing import Final
from uuid import UUID, uuid5

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from incident_memory.records import RememberedIncident

# What a record carries beside its vector. `service` is its own field because
# every search narrows by it and a filter needs something to match on; the
# record travels whole beside it, because what a recall is for is the list of
# what was tried, and an id the caller then had to look up elsewhere would make
# memory a second database.
SERVICE_FIELD: Final = "service"
RECORD_FIELD: Final = "record"

# Cosine, because these are sentence embeddings and what matters between two of
# them is direction rather than magnitude - a long description and a short one
# about the same incident should not be far apart for being different lengths.
VECTOR_DISTANCE: Final = Distance.COSINE

# The namespace an incident's id is hashed into to make a point id. Qdrant takes
# a UUID or an integer and an incident id is neither by guarantee, so the id is
# derived rather than required to be one - and derived rather than generated, so
# that a walk resumed and written twice leaves one record instead of two votes.
POINT_NAMESPACE: Final = UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")


def remember(client: QdrantClient,
             collection: str,
             record: RememberedIncident,
             vector: list[float]) -> None:
    """Keeps this record, making the collection if it is not there yet.

    An upsert rather than an insert, keyed on the incident rather than on the
    moment of writing. A walk that was resumed writes its record again, and two
    copies of one incident would count twice in an ordering - a past incident
    given a second vote for having been interrupted.
    """
    _a_collection_that_exists(client, collection, len(vector))

    client.upsert(
        collection_name=collection,
        points=[
            PointStruct(
                id=str(uuid5(POINT_NAMESPACE, record.incident_id)),
                vector=vector,
                payload={
                    SERVICE_FIELD: record.service,
                    RECORD_FIELD: record.model_dump(mode="json")
                }
            )
        ]
    )


def recalled(client: QdrantClient,
             collection: str,
             vector: list[float],
             *,
             service: str,
             limit: int,
             floor: float) -> list[RememberedIncident]:
    """The incidents most like this one, nearest first, at most `limit` of them.

    Narrowed to one service before anything is compared. Whether two incidents
    happened to the same service is an exact question, and a description that
    merely mentions a service name is not an answer to it.

    `floor` is the caller's policy, applied here so that nothing above ever sees
    a record it was meant to ignore. A nearest-neighbour search always answers:
    without a floor, a corpus holding one unrelated incident hands it back as the
    nearest thing it has, and an ordering would demote a candidate on it.

    A store with no collection yet finds nothing, which is an answer rather than
    a failure - it is the ordinary state before the first incident ends.
    """
    if not client.collection_exists(collection):
        return []

    found = client.query_points(
        collection_name=collection,
        query=vector,
        query_filter=Filter(
            must=[FieldCondition(key=SERVICE_FIELD, match=MatchValue(value=service))]
        ),
        limit=limit,
        score_threshold=floor,
        with_payload=True
    )

    return [
        RememberedIncident.model_validate((point.payload or {})[RECORD_FIELD])
        for point in found.points
    ]


def _a_collection_that_exists(client: QdrantClient,
                              collection: str,
                              width: int) -> None:
    """Makes the collection, and the index on the field every search filters by.

    The payload index is not an optimisation to add later. Every search here
    narrows by service, and narrowing during the search rather than after it is
    the whole reason a store like this was chosen - without the index Qdrant has
    nothing to traverse the filter with and falls back to scanning.
    """
    if client.collection_exists(collection):
        return

    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=width, distance=VECTOR_DISTANCE)
    )
    client.create_payload_index(
        collection_name=collection,
        field_name=SERVICE_FIELD,
        field_schema=PayloadSchemaType.KEYWORD
    )
