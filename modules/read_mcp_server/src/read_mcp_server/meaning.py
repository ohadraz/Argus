"""Finding the Target Service's code by describing what it does (spec §7.4, §11).

The repository channel's third tool, and the only one that does not need the
cause to have a name. Substring search turns a named cause into a place to look;
this turns a *description* of one into a place to look, which is what Code-Fix
actually holds when the investigation concluded "the discount is divided by a
count that can be zero" and no file in the repository says `discount` anywhere.

Passages rather than files, because passages are what the index holds: a cut of
source with the lines it spans. Nothing here reads a repository - the passages
were embedded ahead of time by `code_index`, off any incident's path, and what
this module does is ask which of them are near what was described.

Still a read, and still one this process could not turn into a write: the store
is reached with a query and the watermark with a select, and neither the vector
store nor the repository is touched by anything below (§13).

Three ways to answer nothing, and only one of them is a fact about the code.
Nothing near enough is an answer. An index nobody has built yet finds nothing
whatever the repository contains, and says so. A store that could not be reached
raises, because the alternative teaches a model that the cause is not in the
code - which is the conclusion the whole channel exists to stop being reached by
accident.
"""

from __future__ import annotations

from typing import Final, Protocol

from argus_core import Connections, SettingsSlice
from argus_core.models import CodeSearch
from argus_core.source_scope import belongs_to_the_service
from code_index import records
from code_index.freshness import Freshness
from code_index.indexing import Embedder
from code_index.store import Found, nearest
from qdrant_client import QdrantClient

from read_mcp_server.repository import RepositoryReadSettings

# How near a passage has to be to be worth a model's turn. A store always
# answers its k nearest however far away they are - ask an index of a shop about
# kernel scheduling and it offers the checkout - and unfiltered that is a model
# reading three irrelevant files and concluding the retriever found the cause.
#
# Measured rather than picked, and measured on both sides, because a floor that
# never fires and a floor that cannot fire look identical from the admitted side
# alone. Nine descriptions Code-Fix really searched with, against six this
# repository has no code for at all, over the whole index: every real hit scored
# 0.643 to 0.845, every absent one 0.477 to 0.653. Cosine on one small domain is
# compressed high, so the gap is nowhere near a half - what each candidate would
# do, out of 72 real hits and 48 from questions nothing here answers:
#
#     0.50    keeps 72    refuses  4     admits noise wholesale
#     0.55    keeps 72    refuses 16
#     0.60    keeps 72    refuses 27
#     0.62    keeps 72    refuses 31     <- here
#     0.64    keeps 72    refuses 42     the knee, and 0.003 from the lowest
#                                        real score: no margin at all
#     0.65    keeps 68    refuses 47     already dropping real passages
#     0.66    keeps 66    refuses 48
#
# 0.64 is where the rejection curve turns and is not the figure to take: the
# lowest real hit sits three thousandths above it, so a re-index, a model
# revision or a differently worded description drops a passage that mattered.
# 0.62 keeps everything with twenty times that margin and still refuses two
# thirds of the noise.
#
# The two mistakes are not symmetric, which is what settles the trade. A passage
# admitted too many costs a few hundred tokens and is cut again by the top-k
# behind this; a passage refused is code the agent never sees and cannot recover,
# and it may have been the fix. So the figure wanted is the highest one that
# still keeps every real hit, not the one that refuses the most noise.
#
# One embedder's numbers, as the old ones were: this belongs to
# `bge-small-en-v1.5` over one repository, and a different embedder needs the
# pair of measurements taken again rather than this figure carried across.
NEAR_ENOUGH_TO_ANSWER: Final = 0.62

# How many passages one search may answer with. Small on purpose - these are
# read in full rather than skimmed, and a model handed twenty spends its context
# on the tail of a ranking it has no way to judge.
MOST_PASSAGES_WORTH_ANSWERING: Final = 8

# What marks a line as being about the answer rather than part of it. The
# passages that follow are source, and a warning that could be mistaken for one
# is a warning a model may try to read a file for.
NOTICE_PREFIX: Final = "note: "


class IndexReadSettings(SettingsSlice):
    """Where the passages are kept, and whether this deployment keeps any.

    The whole of what this tier may know about the index, and it is a read:
    an address and a collection. Nothing here could build one - indexing is a
    different process, off any incident's path, and this one only asks.

    `code_search` is what decides whether any of it exists. A deployment
    searching by grep alone opens no store and registers no tool: a tool that
    is offered will be called, and one backed by an index nobody builds
    answers nothing for every description - which a model reads as a fact
    about the code.
    """

    qdrant_url: str
    code_index_collection: str
    code_search: CodeSearch

    @property
    def searches_by_meaning(self) -> bool:
        """Whether this deployment has an index to search at all."""
        return self.code_search is not CodeSearch.GREP


class IndexUnreachable(Exception):
    """The store could not be asked, so nothing is known about what is near.

    Distinct from finding nothing, which this module answers with. A caller
    that cannot tell the two apart reads an outage as evidence that the cause
    is not in the code.
    """


class NearestPassages(Protocol):
    """How this module asks the store what is near a vector.

    The seam is the query rather than the client under it: what Qdrant does with
    a vector belongs to `code_index` and is asserted there against a real one.
    The collection and the connection are bound where the server is built, so
    what arrives here is the question and nothing about where it is asked.
    """

    def __call__(self, vector: list[float], limit: int, /) -> list[Found]: ...


class IndexedSha(Protocol):
    """Which commit the stored passages describe, or nothing if none do.

    Bound to a repository at the composition root for the same reason: this
    module has one repository's index to talk about, and a parameter naming it
    would be a parameter every caller passes the same value for.
    """

    def __call__(self) -> str | None: ...


def the_index_at(settings: IndexReadSettings) -> NearestPassages:
    """The real query, aimed at the store this deployment keeps its index in.

    A factory rather than a function taking the address, so what the tool is
    handed stays the two-argument `NearestPassages` a test can stand in for.
    The client is built once, where the server is - opening one per call would
    pay for a connection on every question a model asks.
    """
    client = QdrantClient(url=settings.qdrant_url)

    def find(vector: list[float], limit: int, /) -> list[Found]:
        return nearest(client, settings.code_index_collection, vector, limit)

    return find


def the_commit_indexed_for(repository: str,
                           connections: Connections) -> IndexedSha:
    """The real watermark read, bound to the repository this deployment serves.

    Asked per call rather than read once at startup, because the catch-up loop
    moves the mark while this process is running: a server that cached it would
    go on warning about a gap that had been closed an hour ago, and a reader
    that stops believing the warning is a reader the true case cannot reach.

    A repository nothing is recorded about answers the same as one whose index
    has never been built, which is what both are.
    """
    def indexed_sha() -> str | None:
        with connections() as conn:
            recorded = records.get(conn, repository)

        return recorded.indexed_sha if recorded is not None else None

    return indexed_sha


def search_repository_by_meaning(description: str,
                                 ref: str,
                                 *,
                                 settings: RepositoryReadSettings,
                                 embed: Embedder,
                                 find: NearestPassages,
                                 indexed_sha: IndexedSha) -> list[str]:
    """The passages nearest `description`, nearest first, as `path:start-end`.

    `ref` is the commit the caller is working against, and is what the index's
    own commit is compared to. When they differ the answer opens with a notice
    naming both, because an index that has fallen behind still answers and what
    it answers may simply be old - and a reader that knows both commits can
    judge whether the gap matters, where one told only "possibly stale" cannot.

    Scoped by the same configuration the substring channel is, so a file one
    channel will not answer from is a file the other will not either. Applied
    here as well as at indexing time because the two are configured separately:
    an index built under a wider scope than this reader is asked about must not
    answer outside it.

    Raises `IndexUnreachable` when the store could not be asked.
    """
    passages = [
        _located(found)
        for found in _the_nearest_to(description, embed, find)
        if found.score >= NEAR_ENOUGH_TO_ANSWER
        if belongs_to_the_service(found.chunk.path, settings.github_source_paths)
    ]
    notice = the_index_notice(ref=ref, indexed_sha=indexed_sha)

    if not notice:
        return passages

    return [f"{NOTICE_PREFIX}{notice}", *passages]


def the_index_notice(*, ref: str, indexed_sha: IndexedSha) -> str:
    """What has to be said about the index before anything it answers is acted
    on, or nothing when there is nothing to say.

    The same fact `search_repository_by_meaning` opens with, asked for without
    searching. Code-Fix states it before its first call: a model that learns
    the index is behind only from a result it has already acted on has learned
    it a turn too late.

    Empty rather than a reassurance when the index is current. A line saying
    "the index is up to date" costs tokens to say nothing, and teaches a reader
    to skip the place where the warning that matters appears.
    """
    return Freshness(indexed_sha=indexed_sha(), deployed_sha=ref).notice or ""


def _the_nearest_to(description: str,
                    embed: Embedder,
                    find: NearestPassages) -> list[Found]:
    """What the store offers for this description, ranked as it ranked them.

    The description is embedded outside the attempt, because a model that
    failed to load is this process's own problem and reporting it as an
    unreachable store would send somebody to look at Qdrant.
    """
    vector = embed([description])[0]

    try:
        return find(vector, MOST_PASSAGES_WORTH_ANSWERING)
    except Exception as error:
        raise IndexUnreachable(
            f"could not search the index for [{description}]: {error}"
        ) from error


def _located(found: Found) -> str:
    """One passage, said where a developer's own tools would say it.

    The location is a line of its own rather than a prefix, because what follows
    is source and a header run into the first line of it changes what that line
    says.
    """
    return (
        f"{found.chunk.path}:{found.chunk.first_line}-{found.chunk.last_line}\n"
        f"{found.chunk.text}"
    )
