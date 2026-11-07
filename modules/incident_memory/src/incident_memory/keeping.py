"""Putting a record in the store - the deliverer's side of it, and no walk's.

The one module that writes the store. A walk does not reach it: what a walk
files is a row the fence can refuse (`filing`), and only the deliverer, which
walks no run, carries the rows here. A walk that wrote the store itself would be
writing where nothing refuses a run another claim holds, and the upsert keyed on
the incident would keep whichever walk wrote last.

Two halves, as on the reading side. `remember` is the write in the store's
vocabulary: a record and its vector in. `kept_in` binds the model in front of
it, because a record has to be embedded before it can be kept and with the same
model the question will be put through (`recalling`).

There is no delete and no re-index - a record describes an incident that is
over. The collection is made on the first write: a store that has never been
written to is the ordinary state of a first deployment, and a memory that
refused to serve until somebody had run a setup step would be a memory nobody
has.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final
from uuid import UUID, uuid5

from argus_core.embedding import Embedder
from argus_core.vector_store import a_collection_that_exists
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct

from incident_memory.recalling import RECORD_FIELD, SERVICE_FIELD
from incident_memory.records import RememberedIncident

# The namespace an incident's id is hashed into to make a point id. Qdrant takes
# a UUID or an integer and an incident id is neither by guarantee, so the id is
# derived rather than required to be one - and derived rather than generated, so
# that a record delivered twice leaves one record instead of two votes.
POINT_NAMESPACE: Final = UUID("6f9619ff-8b86-d011-b42d-00c04fc964ff")

type Keeper = Callable[[RememberedIncident], None]


def remember(client: QdrantClient,
             collection: str,
             record: RememberedIncident,
             vector: list[float]) -> None:
    """Keeps this record, making the collection if it is not there yet.

    An upsert rather than an insert, keyed on the incident rather than on the
    moment of writing. A record refiled is delivered again, and two copies of
    one incident would count twice in an ordering - a past incident given a
    second vote for having been interrupted.
    """
    a_collection_that_exists(
        client, collection, width=len(vector), indexed_field=SERVICE_FIELD
    )

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


def kept_in(client: QdrantClient, collection: str, embed: Embedder) -> Keeper:
    """Keeping a record: embed what it is described as, then store it.

    Embedded on the way in, so the store never holds a record without its
    vector: a record nobody has embedded is a record no search reaches, and a
    store holding one would answer "nothing like this" while holding exactly
    this. Until then it waits as a filed row, which nothing searches.
    """

    def keep(record: RememberedIncident) -> None:
        remember(client, collection, record, embed([record.described_as])[0])

    return keep
