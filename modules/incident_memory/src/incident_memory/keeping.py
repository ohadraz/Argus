"""The two calls a deployment actually makes, with the model and the store bound in.

Above this, a record is a value and a search is a vector; below it, a collection
and an ONNX runtime. This is the one place that knows a record has to be embedded
before it can be kept, and that the same model has to embed the question - which
is exactly the pairing that goes wrong when two callers arrange it separately.

Built once where a process starts, and handed down as two callables. Nothing that
uses them knows a vector store exists, which is what lets a deployment with no
memory configured supply two that do nothing at all.
"""

from __future__ import annotations

from collections.abc import Callable

from argus_core.embedding import Embedder
from qdrant_client import QdrantClient

from incident_memory.records import RememberedIncident
from incident_memory.store import recalled, remember

type Keeper = Callable[[RememberedIncident], None]
type Recaller = Callable[[str, str], list[RememberedIncident]]


def kept_in(client: QdrantClient, collection: str, embed: Embedder) -> Keeper:
    """Keeping a record: embed what it is described as, then store it.

    The description is embedded rather than stored and embedded later, because
    a record nobody has embedded is a record no search reaches - and a store
    holding one would answer "nothing like this" while holding exactly this.
    """

    def keep(record: RememberedIncident) -> None:
        remember(client, collection, record, embed([record.described_as])[0])

    return keep


def recalling_from(client: QdrantClient,
                   collection: str,
                   embed: Embedder,
                   *,
                   limit: int,
                   floor: float) -> Recaller:
    """Recalling records: embed the question with the same model, then search.

    The same model, necessarily. Two vectors from two models are two coordinate
    systems, and the distance between them is a number that means nothing - which
    is why the model is bound here, once, rather than named at each end.

    `limit` and `floor` are bound here too. They are a deployment's policy and
    they do not vary per call, so a caller passing them each time would be a
    caller with an opinion about relevance it has no way to hold.
    """

    def recall(described_as: str, service: str) -> list[RememberedIncident]:
        return recalled(
            client,
            collection,
            embed([described_as])[0],
            service=service,
            limit=limit,
            floor=floor
        )

    return recall
