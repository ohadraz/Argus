"""The vector store, as Argus needs it: two ports, and the values that cross them.

Two corpora are kept in one: the repository index holds passages of source, and
long-term memory holds what earlier incidents tried. They share nothing but the
store, and what they ask of it is the same few questions - put these, forget
those, what do you hold under this field, and what is nearest this vector among
what matches.

Split where the walk's privilege is split. `VectorSearch` is the one question a
walk may ask, and a walk is handed nothing wider: a write typed in a walk does not
type-check, so "the walk only reads memory" is held by the types as well as by
the layering guard. `VectorIndex` is the whole of it, for the processes that
build a corpus - the deliverer and the index's catch-up loop - and for nobody
who walks an incident.

Every value here is Argus's own. A condition is stated as what it asks rather
than in a vendor's filter grammar, a hit is an id, a score and the payload it was
stored with, and a failure says whether asking again could help. What a payload
holds is each corpus's to say; the kernel holding an opinion about it would be a
kernel edited every time a corpus changes its mind.

The adapter is named for its vendor and lives in a package of its own
(`vector_store_qdrant`), built only where a process is wired. No third party is
imported here, so naming the port installs nothing: a module that types what it
holds as `VectorSearch` does not thereby install a store's client.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

# What a point carries beside its vector. A mapping of the corpus's own fields,
# read back exactly as it was written.
type Payload = Mapping[str, object]


@dataclass(frozen=True)
class Equals:
    """A payload field holding exactly this value.

    Long-term memory narrows every recall by it: whether two incidents happened
    to the same service is an exact question, and nearness is no answer to it.
    """

    field: str
    value: str


@dataclass(frozen=True)
class StartsWithAnyOf:
    """A payload field starting with one of these prefixes.

    What the repository index's scope is: a deployment says which directories
    of a repository are the service, by prefix, and a passage outside them is
    not answered from (`core.source_scope`).

    An empty list of prefixes is refused rather than read either way. "Starts
    with any of none" matches nothing, and an unscoped search means everything -
    a caller with no prefixes states no condition, and one that built this from
    an empty list has read its setting wrong.
    """

    field: str
    prefixes: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.prefixes:
            raise ValueError(
                f"a condition on [{self.field}] needs at least one prefix; "
                "a search scoped to nothing states no condition"
            )


# One condition a point must meet. Several are all met at once.
type Condition = Equals | StartsWithAnyOf


@dataclass(frozen=True)
class Hit:
    """A point a search offered, how near it was, and what it carried."""

    id: str
    score: float
    payload: Payload


@dataclass(frozen=True)
class Held:
    """A point the store holds, read back without its vector."""

    id: str
    payload: Payload


@dataclass(frozen=True)
class StoredVector:
    """A point to be kept: its id, its vector and its payload.

    The id is the corpus's to derive. Both corpora derive it from what the point
    describes, so the same thing written twice is one point rather than two.
    """

    id: str
    vector: Sequence[float]
    payload: Payload


class VectorStoreUnavailable(Exception):
    """The store failed for itself, so the same question asked again may be
    answered. Raised for a server's own failure, never for a refusal."""


class VectorQueryRefused(Exception):
    """The store refused the question, so asking it again gets the same answer."""


class VectorStoreUnreachable(Exception):
    """No answer could be had from the store: it was not reached, or what came
    back could not be read. Said apart from `VectorStoreUnavailable` because
    nothing here knows whether asking again would fare better, so a caller that
    asks again when the store failed for itself is not made to ask again here."""


class VectorSearch(Protocol):
    """The one question a walk may ask of the store: what is near this.

    Narrowed and floored inside the query, never after it. A store answers its
    `limit` nearest, and a filter applied to those afterwards hands back fewer
    than `limit` matches while more exist further down the ranking - the
    nearest passages outside a scope crowd out the ones inside it.
    """

    def nearest(self,
                vector: Sequence[float],
                /,
                *,
                limit: int,
                where: Sequence[Condition] = (),
                floor: float | None = None) -> list[Hit]:
        """At most `limit` points meeting every one of `where` and scoring at
        least `floor`, nearest first.

        A store that holds nothing yet finds nothing, which is an answer rather
        than a failure. `floor` of `None` admits everything the ranking reaches -
        which is what a measurement of where scores land needs, and what no
        search answering a model should ask for.

        Raises `VectorStoreUnavailable` when the store failed for itself,
        `VectorQueryRefused` when it refused the question, and
        `VectorStoreUnreachable` when no answer could be had from it at all.
        """
        ...


class VectorIndex(VectorSearch, Protocol):
    """The whole store, for a process that builds a corpus and walks no run."""

    def ensure(self, *, width: int, indexed_field: str, matched_by_prefix: bool = False) -> None:
        """Makes the store ready to hold vectors `width` wide, with `indexed_field`
        indexed for the conditions every search narrows by.

        Quiet where it is ready already, which is every write after the first.
        `matched_by_prefix` where the field is asked `StartsWithAnyOf` rather
        than `Equals`.
        """
        ...

    def upsert(self, vectors: Sequence[StoredVector], /) -> None:
        """Keeps these, replacing whatever was kept under the same ids."""
        ...

    def delete(self, ids: Sequence[str], /) -> None:
        """Forgets these ids. An id never kept is forgotten already."""
        ...

    def held(self, where: Sequence[Condition], /, *, with_payload: bool) -> list[Held]:
        """Every point meeting all of `where`, however many there are.

        Without its payload where `with_payload` is false, which is what a
        caller asking only which ids it holds should ask for.
        """
        ...
