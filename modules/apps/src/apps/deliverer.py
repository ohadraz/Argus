"""The deliverer's root: what carries filed records into long-term memory.

`python -m apps.deliverer`. What a pass does is `incident_memory.delivering`'s;
this decides what it runs against - the pool, the store's writing side, the
embedder - and starts the loop.
"""

from __future__ import annotations

import logging
from typing import Final

from core import (
    DatabaseSettings,
    SettingsSlice,
    TelemetrySettings,
    get_settings,
    open_pool,
)
from core.embedding import an_embedder
from core.schema import require_schema
from incident_memory.delivering import deliver_forever, deliver_on
from incident_memory.keeping import kept_in
from telemetry import start_telemetry
from telemetry.langfuse import LangfuseSettings, to_langfuse
from vector_store_qdrant.indexing import the_index_at
from vector_store_qdrant.settings import QdrantSettings

logger = logging.getLogger(__name__)

# What this process is called in its telemetry, and the directory its runs are
# written under.
_SERVICE: Final = "argus-memory"


class DeliverySettings(SettingsSlice):
    """Whether memory is kept at all, in which collection, and how often to look.

    The interval bounds how long a finished incident's record may be filed and
    unsearchable. Short, because nothing waits on it but the next incident like
    this one - and a pass that finds nothing waiting is one query.
    """

    incident_memory_enabled: bool
    incident_memory_collection: str
    incident_memory_embedding_model: str
    incident_memory_delivery_interval_seconds: float


def main() -> None:
    """The process: a pool, a store, a model, then deliver until killed.

    Everything this process needs is built here and nowhere else. A `main`
    rather than module-level code, so that importing this module starts
    nothing.

    Nothing at all where this deployment keeps no memory. The walks still file
    their records, so switching memory on later delivers every incident filed
    while it was off - and until then, an embedding model loaded to deliver
    nothing would be loaded for nobody.

    The pool is not fenced: this process walks no run, so the fence lets it
    mark rows as every process but a worker writes. The schema is checked
    before the first pass, as every process here checks it.
    """
    settings = get_settings()
    delivery = DeliverySettings.of(settings)

    with start_telemetry(TelemetrySettings.of(settings), _SERVICE,
                         also=to_langfuse(LangfuseSettings())):
        if not delivery.incident_memory_enabled:
            logger.info("incident memory disabled")

            return

        with (
            open_pool(DatabaseSettings.of(settings)) as pool,
            # The adapter is built here and nowhere else in this process, and
            # handed on as the port: what `keeping` writes through is a
            # `VectorIndex`, and the vendor is this line's alone.
            the_index_at(QdrantSettings().qdrant_url,
                         delivery.incident_memory_collection) as store
        ):
            with pool.connection() as conn:
                require_schema(conn)

            keep = kept_in(store, an_embedder(delivery.incident_memory_embedding_model))

            def pass_over() -> int:
                """One pass, on a connection of its own for the whole of it -
                which is what the delivery's lock is held on."""
                with pool.connection() as conn:
                    return deliver_on(conn, keep)

            logger.info("delivery started")
            deliver_forever(delivery.incident_memory_delivery_interval_seconds, pass_over)


if __name__ == "__main__":
    main()
