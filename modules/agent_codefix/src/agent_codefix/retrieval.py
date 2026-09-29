"""What the fix loop asks of the repository, as shapes rather than as functions.

The read half of proposing a fix, and only the read half: what writes a branch
and opens a proposal is the write tier's, and stays beside the loop that reaches
it. Kept apart from the loop for the reason the investigator keeps its channels
apart - the loop is asked about a repository, the client functions are asked over
a connection, and a test standing one of these in should be standing in the
former.
"""

from __future__ import annotations

from typing import Protocol

# `Protocol` rather than a `Callable` alias throughout, for the reason the
# investigator's retrieval channels are: a test stands each of these in with
# `create_autospec`, which needs something introspectable - and specing against
# the client functions would be specing against the wrong shape, since those take
# the connection they are asked over and the loop is asked about a repository.


class SourceSearcher(Protocol):
    def __call__(self, query: str, ref: str, /) -> list[str]: ...


class MeaningSearcher(Protocol):
    """Finding code by describing what it does rather than by naming it.

    The other retrieval channel, and the same shape as the first on purpose:
    the loop answers both the same way, and a caller configured for one of
    them is offering the model a different tool rather than running different
    code.
    """

    def __call__(self, description: str, ref: str, /) -> list[str]: ...


class IndexNotice(Protocol):
    """What has to be said about the index before anything it answers is used.

    Asked once, before the conversation starts, rather than read off a search
    result: a model that learns the index is behind from a result it has
    already acted on has learned it a turn too late. Empty when there is
    nothing to say, which is the ordinary state.
    """

    def __call__(self, ref: str, /) -> str: ...


class FileLister(Protocol):
    def __call__(self, ref: str, /) -> list[str]: ...


class FileReader(Protocol):
    def __call__(self, path: str, ref: str, /) -> str: ...
