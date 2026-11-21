"""Asking the store what it holds like this incident - the walk's side of it.

The walk reads memory and never writes it. What it files is a row the fence can
refuse (`filing`), and the store is filled from the rows by a process of its own
(`delivering`) - so everything here is a read, and a read made for a run that
was since taken back changes nothing anybody else holds. That is why this is the
side of memory a walk may reach, and why what it is handed is a `VectorSearch`:
a write typed here does not type-check.

Two halves. `recalled` is the search itself, in the store's vocabulary: a vector
in, records out. `recalling_from` binds the model and the store into the
question the walk actually asks, which is text: the same model has to embed the
question as embedded the records, and binding it here, once, is what stops two
callers arranging that separately.

No store is opened here. The process that holds one opens it where it is wired,
through the vendor's adapter, and hands it in typed as the port.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Final

from core.embedding import Embedder
from core.vector_store import Equals, VectorSearch, VectorStoreUnavailable

from incident_memory.records import RememberedIncident

# What a record carries beside its vector. `service` is its own field because
# every search narrows by it and a filter needs something to match on; the
# record travels whole beside it, because what a recall is for is the list of
# what was tried, and an id the caller then had to look up elsewhere would make
# memory a second database. Named here, where they are read, and written by
# `keeping` in the same words.
SERVICE_FIELD: Final = "service"
RECORD_FIELD: Final = "record"

type Recaller = Callable[[str, str], list[RememberedIncident]]


def recalled(store: VectorSearch,
             vector: Sequence[float],
             *,
             service: str,
             limit: int,
             floor: float,
             attempts: int = 1,
             retry_seconds: float = 0.0,
             sleep: Callable[[float], None] = time.sleep) -> list[RememberedIncident]:
    """The incidents most like this one, nearest first, at most `limit` of them.

    Narrowed to one service inside the search, before anything is compared.
    Whether two incidents happened to the same service is an exact question,
    and a description that merely mentions a service name is not an answer to
    it - and narrowed afterwards, the nearest incidents of other services would
    take places this service's own were owed.

    `floor` is the caller's policy, applied inside the search so that nothing
    above ever sees a record it was meant to ignore. A nearest-neighbour search
    always answers: without a floor, a corpus holding one unrelated incident
    hands it back as the nearest thing it has, and an ordering would demote a
    candidate on it.

    A search the store failed for itself is asked again, up to `attempts` in
    all, `retry_seconds` apart: Qdrant answered one with "Expected at least one
    response for one query" while the record searched for was there. A refusal
    of the question is raised at once, since the same question gets the same
    answer; and the last failure is raised, since the caller is the one who knows
    what to do without memory.

    Fewer than one attempt is refused rather than read as asking nothing: a
    search that never ran has no answer to give, and an empty one would read as
    a memory holding nothing like this incident.
    """
    if attempts < 1:
        raise ValueError(f"a search needs at least one attempt, and was allowed {attempts}")

    def searched() -> list[RememberedIncident]:
        return [
            RememberedIncident.model_validate(hit.payload[RECORD_FIELD])
            for hit in store.nearest(
                vector,
                limit=limit,
                where=[Equals(field=SERVICE_FIELD, value=service)],
                floor=floor
            )
        ]

    # Every attempt but the last may be asked again; the last one's failure is
    # the caller's, whatever it was.
    for _ in range(attempts - 1):
        try:
            return searched()
        except VectorStoreUnavailable:
            sleep(retry_seconds)

    return searched()


def recalling_from(store: VectorSearch,
                   embed: Embedder,
                   *,
                   limit: int,
                   floor: float,
                   attempts: int = 1,
                   retry_seconds: float = 0.0) -> Recaller:
    """Recalling records: embed the question with the same model, then search.

    The same model, necessarily. Two vectors from two models are two coordinate
    systems, and the distance between them is a number that means nothing - which
    is why the model is bound here, once, rather than named at each end.

    `limit` and `floor` are bound here too. They are a deployment's policy and
    they do not vary per call, so a caller passing them each time would be a
    caller with an opinion about relevance it has no way to hold. So are
    `attempts` and `retry_seconds`, for the same reason.
    """

    def recall(described_as: str, service: str) -> list[RememberedIncident]:
        return recalled(
            store,
            embed([described_as])[0],
            service=service,
            limit=limit,
            floor=floor,
            attempts=attempts,
            retry_seconds=retry_seconds
        )

    return recall
