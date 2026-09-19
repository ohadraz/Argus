"""Making a vector collection exist, for whichever corpus wants one.

Here rather than in either module that keeps one, and for the reason
`an_embedder` is here: the repository index holds passages of source and
long-term memory holds descriptions of incidents, the two corpora have nothing
to say to each other, and what they share is the one step that is not about
either - asking a store for a collection and getting one.

It was written twice before it was written here, identically but for the field
each indexes by, which is the state that ends with two provisionings disagreeing
about what a collection is. Only the provisioning moved: what a payload holds,
what a query filters on and what comes back are each corpus's own, and a kernel
holding an opinion about those would be a kernel that has to be edited every
time a corpus changes its mind.

Cosine, for both and for anything after them. The embedders in use answer
normalised vectors, so cosine and dot product agree - and where they disagree,
cosine is the one that does not quietly reward a long document for being long.

Tested from the two modules that call it rather than by a suite of its own, and
deliberately: what there is to get wrong here is what a real store does with
these calls, and a local client is not that store - it accepts the payload index
and warns that it does nothing. So each corpus's component suite asserts its own
field comes back indexed, against the Qdrant it runs against. `an_embedder` is
here for the same reason, with the same answer.
"""

from __future__ import annotations

from typing import Final

from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PayloadSchemaType, VectorParams

VECTOR_DISTANCE: Final = Distance.COSINE


def a_collection_that_exists(client: QdrantClient,
                             collection: str,
                             *,
                             width: int,
                             indexed_field: str) -> None:
    """Makes the collection if it is not there, with an index on one field.

    The payload index is not an optimisation to add later, which is why it is
    made here rather than left to whoever remembers. Both corpora filter every
    search by a field - one by path, one by service - and filtering during the
    search rather than after it is the whole reason a store like this was
    chosen. Without the index Qdrant has nothing to traverse the filter with and
    falls back to scanning.

    `width` is read off the vectors the caller is about to store rather than
    configured, because it is a fact about the model that produced them: a
    number in a settings file is one that can disagree with the weights on disk,
    and the disagreement surfaces as a refused upsert at the far end of a pass.

    Returning quietly where the collection already exists is the ordinary case -
    every write after the first - and not a condition worth reporting upwards.
    """
    if client.collection_exists(collection):
        return

    client.create_collection(
        collection_name=collection,
        vectors_config=VectorParams(size=width, distance=VECTOR_DISTANCE)
    )
    client.create_payload_index(
        collection_name=collection,
        field_name=indexed_field,
        field_schema=PayloadSchemaType.KEYWORD
    )
