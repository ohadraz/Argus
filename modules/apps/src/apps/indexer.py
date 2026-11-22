"""The index catch-up's root: what keeps the repository index at the deployed
commit (spec §11.5).

`python -m apps.indexer`, and `--once` for the pass a stack makes before its
services start. What a pass decides is `repository_index.catching_up`'s; this
decides what it runs against - the code host, the store's writing side, the
pool and the embedder - and starts the loop.
"""

from __future__ import annotations

import logging
from argparse import ArgumentParser
from functools import partial
from typing import Final

from code_host.github import GitHubReads, GitHubReadSettings
from core import (
    DatabaseSettings,
    SettingsSlice,
    TelemetrySettings,
    get_settings,
    open_pool,
)
from core.models import CodeSearch
from core.schema import require_schema
from embedding_fastembed import an_embedder
from repository_index.building import IndexSettings, index_repository
from repository_index.catching_up import catch_up, catch_up_forever
from repository_index.records import get
from telemetry import start_telemetry
from telemetry.langfuse import LangfuseSettings, to_langfuse
from vector_store_qdrant.indexing import the_index_at
from vector_store_qdrant.settings import QdrantSettings

logger = logging.getLogger(__name__)

# What this process is called in its telemetry, and the directory its runs are
# written under.
_SERVICE: Final = "argus-index"


class CatchUpSettings(SettingsSlice):
    """How often the loop looks, with what, and whether there is anything to
    look for.

    The interval is the longest an index may describe yesterday's code while
    nobody is telling it otherwise - a bound on staleness rather than a
    performance knob. Short enough that a push nobody delivered is caught
    within a coffee, long enough that a repository nothing happens to is not
    fetched every minute.
    """

    repository_index_interval_seconds: float
    # The model every passage is embedded with - the one the read tier embeds
    # a question with, which is what makes the two comparable.
    repository_index_embedding_model: str
    # Whether this deployment keeps an index at all. A run set to grep alone
    # exits rather than building one nobody can search: the read tier
    # registers no tool for it, so every passage embedded here would be
    # embedded for no caller.
    code_search: CodeSearch


def main(argv: list[str] | None = None) -> None:
    """The process: a pool, a store, a model, then catch up until killed.

    `--once` makes one pass and exits, which is what a stack runs before the
    services that read the index - in the slot the schema job already
    occupies, and for the same reason: nothing else may be the process that
    has to start first. Without it the first search of a run races the first
    pass, and a suite's answer depends on which won.

    Everything this process needs is built here and nowhere else - the one
    place that knows a pool exists, that Qdrant has an address, or that the
    embedder loads a model. A `main` rather than module-level code, so that
    importing this module starts nothing.

    The schema is checked before the first pass. A process that indexed a
    repository and then found no table to record the commit in would have
    spent the whole build and left the index looking as though it had never
    run.
    """
    parser = ArgumentParser(description="Keeps the index describing what is deployed.")
    parser.add_argument(
        "--once",
        action="store_true",
        help="make one pass and exit, rather than catching up until killed"
    )
    once = parser.parse_args(argv).once

    settings = get_settings()
    index_settings = IndexSettings.of(settings)
    catch_up_settings = CatchUpSettings.of(settings)

    # Started before anything is decided, so that a process which decides to do
    # nothing says so in this run's logs as well as on the console.
    with start_telemetry(TelemetrySettings.of(settings), _SERVICE,
                         also=to_langfuse(LangfuseSettings())):
        # Before a pool, a store or a model. A deployment searching by grep
        # alone has no reader for any of this, and an index built for nobody
        # costs a repository download and an ONNX runtime to sit unread.
        if catch_up_settings.code_search is CodeSearch.GREP:
            logger.info("no index kept", extra={"code_search": catch_up_settings.code_search})

            return

        # The code host's adapter, built here and nowhere else in this process
        # and handed on as its reads port - the read credential alone, since
        # building an index changes a repository in no way.
        code = GitHubReads(GitHubReadSettings())
        repository = code.repository

        # The store's adapter likewise, handed on as the port: a pass writes
        # through a `VectorIndex`, and the vendor is this line's alone.
        with (
            the_index_at(QdrantSettings().qdrant_url,
                         index_settings.repository_index_collection) as store,
            open_pool(DatabaseSettings.of(settings)) as pool
        ):
            with pool.connection() as conn:
                require_schema(conn)

            embed = an_embedder(catch_up_settings.repository_index_embedding_model)

            def pass_over() -> str | None:
                """One pass, with a connection of its own.

                Per pass rather than held for the life of the loop: most passes
                find nothing to do and end in seconds, and a connection kept
                open between them is one the pool cannot give to anybody else
                while this process sleeps.
                """
                with pool.connection() as conn:
                    return catch_up(
                        settings=index_settings,
                        recorded=partial(get, conn, repository),
                        head_of=code.head_of,
                        changed_between=code.paths_changed_between,
                        index=lambda sha, paths: index_repository(
                            sha,
                            settings=index_settings,
                            conn=conn,
                            store=store,
                            embed=embed,
                            code=code,
                            paths=paths
                        )
                    )

            logger.info("index catch-up started", extra={"repository": repository, "once": once})

            if once:
                pass_over()
            else:
                catch_up_forever(
                    catch_up_settings.repository_index_interval_seconds, pass_over
                )


if __name__ == "__main__":
    main()
