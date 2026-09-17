"""Finding the Target Service's code by describing what it does (spec §7.4, §11).

The repository channel's third tool, and the only one that does not need the
cause to have a name. Substring search turns a named cause into a place to look;
this turns a *description* of one into a place to look, which is what Code-Fix
actually holds when the investigation concluded "the discount is divided by a
count that can be zero" and no file in the repository says `discount` anywhere.

Passages rather than files, because passages are what the index holds: a cut of
source with the lines it spans, near enough to what was described to be worth
reading. What this must never do is answer emptily for the wrong reason - a
store that could not be reached and an index nobody has built yet both have an
empty list ready to hand, and both would be read as "the cause is not in the
code".
"""

from __future__ import annotations

from typing import Any
from unittest.mock import create_autospec

import pytest
from argus_testkit.assertions import Assertion, all_of, an_error_was_raised
from argus_testkit.scenario import Scenario, attempting
from code_index.chunking import Chunk
from code_index.indexing import Embedder
from code_index.store import Found
from read_mcp_server.meaning import (
    NEAR_ENOUGH_TO_ANSWER,
    IndexedSha,
    IndexUnreachable,
    NearestPassages,
    search_repository_by_meaning,
    the_index_notice,
)
from read_mcp_server.repository import RepositoryReadSettings

THE_COMMIT_DEPLOYED = "77296acf1d2b4e5a6c7d8e9f0a1b2c3d4e5f6a7b"
AN_EARLIER_COMMIT = "3f1b9d2c8a7e6f5d4c3b2a1908f7e6d5c4b3a291"

DONT_CARE_DESCRIPTION = "something the service does"
SOME_VECTOR = [0.1, 0.2, 0.3]

_THE_DIVISION = "def average_spend(purchases):\n    return total(purchases) / len(purchases)"


@pytest.mark.unit
def test_a_description_comes_back_as_the_passages_nearest_it() -> None:
    # The whole point of the channel. What arrives is a sentence about behaviour
    # and what goes back is source - located, with the lines it occupies, so the
    # next move is `read_repository_file` on a file the model has a reason to
    # open rather than one whose name looked promising.
    index = an_index_holding(
        a_passage(
            path="src/io_shop/spend_summary.py",
            first_line=14,
            last_line=15,
            text=_THE_DIVISION
        ),
        a_passage(
            path="src/io_shop/accounts.py",
            first_line=3,
            last_line=4,
            text="def owner_of(account):\n    return account.owner"
        )
    )

    Scenario() \
        .when(
            lambda: search_repository_by_meaning(
                "divides by a count that can be zero",
                ref=THE_COMMIT_DEPLOYED,
                settings=some_settings(),
                embed=an_embedder_answering(SOME_VECTOR),
                find=index,
                indexed_sha=an_index_describing(THE_COMMIT_DEPLOYED)
            )
        ) \
        .then(
            all_of(
                _the_passages_answered_are([
                    "src/io_shop/spend_summary.py:14-15",
                    "src/io_shop/accounts.py:3-4"
                ]),
                _a_passage_quotes("return total(purchases) / len(purchases)")
            )
        )


@pytest.mark.unit
def test_the_nearest_passage_is_answered_first() -> None:
    # Ranked, because a caller that trusts the order and is handed an arbitrary
    # one spends its turn reading the least relevant passage. The store ranks;
    # what matters here is that nothing on the way out reorders them.
    index = an_index_holding(
        a_passage(path="src/io_shop/spend_summary.py", first_line=14, last_line=15,
                  text=_THE_DIVISION),
        a_passage(path="src/io_shop/accounts.py", first_line=3, last_line=4,
                  text="def owner_of(account):\n    return account.owner")
    )

    Scenario() \
        .when(
            lambda: search_repository_by_meaning(
                DONT_CARE_DESCRIPTION,
                ref=THE_COMMIT_DEPLOYED,
                settings=some_settings(),
                embed=an_embedder_answering(SOME_VECTOR),
                find=index,
                indexed_sha=an_index_describing(THE_COMMIT_DEPLOYED)
            )
        ) \
        .then(_the_answer_opens_with("src/io_shop/spend_summary.py:14-15"))


@pytest.mark.unit
def test_what_is_searched_for_is_the_description_that_was_asked_about() -> None:
    # A query and a passage have to be measured in the same space, which is what
    # embedding the description here rather than matching its words means. The
    # seam is the only place this can go wrong: an embedder handed the wrong
    # text answers a perfectly well-formed vector for a question nobody asked.
    embed = an_embedder_answering(SOME_VECTOR)
    index = an_index_holding()

    Scenario() \
        .when(
            lambda: search_repository_by_meaning(
                "divides by a count that can be zero",
                ref=THE_COMMIT_DEPLOYED,
                settings=some_settings(),
                embed=embed,
                find=index,
                indexed_sha=an_index_describing(THE_COMMIT_DEPLOYED)
            )
        ) \
        .then(
            all_of(
                _what_was_embedded_was(embed, "divides by a count that can be zero"),
                _what_was_searched_for_was(index, SOME_VECTOR)
            )
        )


@pytest.mark.unit
def test_a_passage_no_nearer_than_anything_else_is_not_offered() -> None:
    # A store always answers its k nearest, however far away they are: ask an
    # index of a shop about kernel scheduling and it returns the shop's checkout
    # with a low score. Offered unfiltered, that is a model reading three
    # irrelevant files and concluding the retriever found the cause.
    index = an_index_holding(
        a_passage(path="src/io_shop/spend_summary.py", first_line=14, last_line=15,
                  text=_THE_DIVISION, score=NEAR_ENOUGH_TO_ANSWER + 0.1),
        a_passage(path="src/io_shop/accounts.py", first_line=3, last_line=4,
                  text="def owner_of(account):\n    return account.owner",
                  score=NEAR_ENOUGH_TO_ANSWER - 0.1)
    )

    Scenario() \
        .when(
            lambda: search_repository_by_meaning(
                DONT_CARE_DESCRIPTION,
                ref=THE_COMMIT_DEPLOYED,
                settings=some_settings(),
                embed=an_embedder_answering(SOME_VECTOR),
                find=index,
                indexed_sha=an_index_describing(THE_COMMIT_DEPLOYED)
            )
        ) \
        .then(_the_passages_answered_are(["src/io_shop/spend_summary.py:14-15"]))


@pytest.mark.unit
def test_nothing_near_enough_is_an_answer_rather_than_a_failure() -> None:
    # The honest empty. The index is current, the store was reached, and nothing
    # in the service resembles what was described - which is a fact about the
    # repository and a useful one, exactly as a substring that matches nothing
    # is.
    Scenario() \
        .when(
            lambda: search_repository_by_meaning(
                DONT_CARE_DESCRIPTION,
                ref=THE_COMMIT_DEPLOYED,
                settings=some_settings(),
                embed=an_embedder_answering(SOME_VECTOR),
                find=an_index_holding(),
                indexed_sha=an_index_describing(THE_COMMIT_DEPLOYED)
            )
        ) \
        .then(_nothing_was_answered())


@pytest.mark.unit
def test_a_store_that_could_not_be_reached_is_not_answered_as_nothing_found() -> None:
    # THE ONE THAT MATTERS. Nothing-near-enough and could-not-look are the same
    # empty list and opposite facts about the world. Silent, the second teaches
    # a model that the cause is not in the code - the conclusion this whole
    # channel exists to stop being reached by accident.
    index = create_autospec(NearestPassages, instance=True)
    index.side_effect = ConnectionError("no route to the store")

    Scenario() \
        .when(
            attempting(
                lambda: search_repository_by_meaning(
                    DONT_CARE_DESCRIPTION,
                    ref=THE_COMMIT_DEPLOYED,
                    settings=some_settings(),
                    embed=an_embedder_answering(SOME_VECTOR),
                    find=index,
                    indexed_sha=an_index_describing(THE_COMMIT_DEPLOYED)
                )
            )
        ) \
        .then(an_error_was_raised(IndexUnreachable))


@pytest.mark.unit
def test_a_passage_outside_the_service_s_own_source_is_not_answered() -> None:
    # The same scope the substring channel applies, and for the same reason: the
    # repository carries the harness that stages incidents against the shop, and
    # that harness describes in prose what it is staging. Searched by meaning it
    # is the *best* match for a description of the fault - the answer rather
    # than the evidence.
    #
    # Applied here as well as at indexing time because the two are configured
    # separately: an index built under a wider scope than the reader is asked
    # about must not answer outside it.
    index = an_index_holding(
        a_passage(path="src/io_shop/spend_summary.py", first_line=14, last_line=15,
                  text=_THE_DIVISION),
        a_passage(path="src/target_app/scenarios.py", first_line=8, last_line=9,
                  text="# divides the discount by a count that can be zero")
    )

    Scenario() \
        .when(
            lambda: search_repository_by_meaning(
                DONT_CARE_DESCRIPTION,
                ref=THE_COMMIT_DEPLOYED,
                settings=some_settings(source_paths="src/io_shop"),
                embed=an_embedder_answering(SOME_VECTOR),
                find=index,
                indexed_sha=an_index_describing(THE_COMMIT_DEPLOYED)
            )
        ) \
        .then(_the_passages_answered_are(["src/io_shop/spend_summary.py:14-15"]))


@pytest.mark.unit
def test_an_index_behind_the_commit_asked_about_says_so_before_it_answers() -> None:
    # An index that has fallen behind still answers, and what it answers may
    # simply be old. Both commits are named because a reader that knows them can
    # judge whether the gap matters - and because a warning that only says
    # "possibly stale" is one a model has no way to act on.
    index = an_index_holding(
        a_passage(path="src/io_shop/spend_summary.py", first_line=14, last_line=15,
                  text=_THE_DIVISION)
    )

    Scenario() \
        .when(
            lambda: search_repository_by_meaning(
                DONT_CARE_DESCRIPTION,
                ref=THE_COMMIT_DEPLOYED,
                settings=some_settings(),
                embed=an_embedder_answering(SOME_VECTOR),
                find=index,
                indexed_sha=an_index_describing(AN_EARLIER_COMMIT)
            )
        ) \
        .then(
            all_of(
                _the_answer_opens_with_a_notice_naming(
                    AN_EARLIER_COMMIT, THE_COMMIT_DEPLOYED
                ),
                _a_passage_quotes("return total(purchases) / len(purchases)")
            )
        )


@pytest.mark.unit
def test_an_index_describing_the_commit_asked_about_adds_nothing_to_its_answer() -> None:
    # The other half, and the one a warning left on by mistake would break. A
    # caller told every time that results may be out of date stops reading the
    # line, which is how the stale case above ends up ignored when it is true.
    index = an_index_holding(
        a_passage(path="src/io_shop/spend_summary.py", first_line=14, last_line=15,
                  text=_THE_DIVISION)
    )

    Scenario() \
        .when(
            lambda: search_repository_by_meaning(
                DONT_CARE_DESCRIPTION,
                ref=THE_COMMIT_DEPLOYED,
                settings=some_settings(),
                embed=an_embedder_answering(SOME_VECTOR),
                find=index,
                indexed_sha=an_index_describing(THE_COMMIT_DEPLOYED)
            )
        ) \
        .then(_the_answer_opens_with("src/io_shop/spend_summary.py:14-15"))


@pytest.mark.unit
def test_an_index_that_was_never_built_says_so_rather_than_finding_nothing() -> None:
    # The dangerous empty. Before the first pass the store holds nothing, so
    # every description finds nothing whatever the repository contains - and an
    # unadorned empty list is indistinguishable from a service that does not do
    # the thing described.
    Scenario() \
        .when(
            lambda: search_repository_by_meaning(
                DONT_CARE_DESCRIPTION,
                ref=THE_COMMIT_DEPLOYED,
                settings=some_settings(),
                embed=an_embedder_answering(SOME_VECTOR),
                find=an_index_holding(),
                indexed_sha=an_index_describing(None)
            )
        ) \
        .then(_the_only_thing_answered_says("nothing has been indexed"))


@pytest.mark.unit
def test_an_index_behind_what_is_deployed_has_something_to_say_on_its_own() -> None:
    # The same fact the search answer opens with, asked for without searching.
    # Code-Fix states it before its first call, because a model that learns the
    # index is stale only from a result it has already acted on has learned it
    # a turn too late.
    Scenario() \
        .when(
            lambda: the_index_notice(
                ref=THE_COMMIT_DEPLOYED,
                indexed_sha=an_index_describing(AN_EARLIER_COMMIT)
            )
        ) \
        .then(_what_was_said_names(AN_EARLIER_COMMIT, THE_COMMIT_DEPLOYED))


@pytest.mark.unit
def test_an_index_describing_what_is_deployed_has_nothing_to_say() -> None:
    # Empty rather than a reassurance. A caller that puts "the index is current"
    # in front of a model has spent tokens saying nothing, and made the line
    # that matters one a reader has learned to skip.
    Scenario() \
        .when(
            lambda: the_index_notice(
                ref=THE_COMMIT_DEPLOYED,
                indexed_sha=an_index_describing(THE_COMMIT_DEPLOYED)
            )
        ) \
        .then(_nothing_was_said())


@pytest.mark.unit
def test_an_index_that_was_never_built_says_that_rather_than_that_it_is_behind() -> None:
    # Two different things are wrong and only one of them is a lag. An index
    # nobody has built finds nothing whatever the repository holds, and a model
    # told merely that its results may be out of date reads an empty answer as
    # a fact about the code.
    Scenario() \
        .when(
            lambda: the_index_notice(
                ref=THE_COMMIT_DEPLOYED,
                indexed_sha=an_index_describing(None)
            )
        ) \
        .then(_what_was_said_includes("nothing has been indexed"))


def _what_was_said_names(indexed: str, deployed: str) -> Assertion[str]:
    """Both commits, so a reader can judge the gap rather than fear it."""
    def assertion(said: str) -> bool:
        if indexed not in said or deployed not in said:
            raise AssertionError(
                f"Expected a notice naming [{indexed}] and [{deployed}], got [{said}]."
            )

        return True

    return assertion


def _what_was_said_includes(text: str) -> Assertion[str]:
    def assertion(said: str) -> bool:
        if text not in said:
            raise AssertionError(f"Expected a notice saying [{text}], got [{said}].")

        return True

    return assertion


def _nothing_was_said() -> Assertion[str]:
    def assertion(said: str) -> bool:
        if said:
            raise AssertionError(f"Expected nothing to be said, got [{said}].")

        return True

    return assertion


def _the_passages_answered_are(located: list[str]) -> Assertion[list[str]]:
    """Which passages came back and where they are, notices left out."""
    def assertion(answered: list[str]) -> bool:
        found = [
            said.splitlines()[0] for said in answered if not said.startswith("note:")
        ]

        if found != located:
            raise AssertionError(f"Expected the passages {located}, got {found}.")

        return True

    return assertion


def _a_passage_quotes(text: str) -> Assertion[list[str]]:
    """The source travels with its location, or the location is a second call."""
    def assertion(answered: list[str]) -> bool:
        if not any(text in said for said in answered):
            raise AssertionError(f"Expected a passage quoting [{text}], got {answered}.")

        return True

    return assertion


def _the_answer_opens_with(expected: str) -> Assertion[list[str]]:
    def assertion(answered: list[str]) -> bool:
        opened = answered[0].splitlines()[0] if answered else ""

        if opened != expected:
            raise AssertionError(f"Expected the answer to open [{expected}], got [{opened}].")

        return True

    return assertion


def _the_answer_opens_with_a_notice_naming(indexed: str,
                                           deployed: str) -> Assertion[list[str]]:
    """Both commits, before anything a reader might act on."""
    def assertion(answered: list[str]) -> bool:
        opened = answered[0] if answered else ""

        if indexed not in opened or deployed not in opened:
            raise AssertionError(
                f"Expected an opening notice naming [{indexed}] and [{deployed}], "
                f"got [{opened}]."
            )

        return True

    return assertion


def _the_only_thing_answered_says(text: str) -> Assertion[list[str]]:
    def assertion(answered: list[str]) -> bool:
        if len(answered) != 1 or text not in answered[0]:
            raise AssertionError(f"Expected one answer saying [{text}], got {answered}.")

        return True

    return assertion


def _nothing_was_answered() -> Assertion[list[str]]:
    def assertion(answered: list[str]) -> bool:
        if answered:
            raise AssertionError(f"Expected nothing to be answered, got {answered}.")

        return True

    return assertion


def _what_was_embedded_was(embed: Any, description: str) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        embedded = embed.call_args.args[0]

        if embedded != [description]:
            raise AssertionError(f"Expected [{description}] embedded, got {embedded}.")

        return True

    return assertion


def _what_was_searched_for_was(index: Any, vector: list[float]) -> Assertion[Any]:
    def assertion(_: Any) -> bool:
        searched = index.call_args.args[0]

        if searched != vector:
            raise AssertionError(f"Expected the search at {vector}, got {searched}.")

        return True

    return assertion


def a_passage(path: str,
              first_line: int,
              last_line: int,
              text: str,
              score: float = 0.9) -> Found:
    """A passage the store would offer, and how near it was.

    The score defaults to near enough to answer, so a test that is not about
    the threshold does not have to state one.
    """
    return Found(
        chunk=Chunk(path=path, first_line=first_line, last_line=last_line, text=text),
        score=score
    )


def an_index_holding(*passages: Found) -> Any:
    """A stand-in for the store's ranked answer.

    The seam is the query rather than the client underneath it: what Qdrant does
    with a vector belongs to `code_index` and is asserted there against a real
    one. What belongs here is what this module does with the passages once it
    has them - rank, scope, threshold, locate, and say what is stale.
    """
    return create_autospec(NearestPassages, instance=True, return_value=list(passages))


def an_index_describing(sha: str | None) -> Any:
    """What the stored passages were built from, or nothing at all."""
    return create_autospec(IndexedSha, instance=True, return_value=sha)


def an_embedder_answering(vector: list[float]) -> Any:
    """A stand-in for the model. The real one loads 130MB to answer a sentence."""
    return create_autospec(Embedder, instance=True, return_value=[vector])


def some_settings(source_paths: str = "") -> RepositoryReadSettings:
    """The repository channel's slice, which this tool shares with substring
    search - so a file one channel will not answer from is a file the other
    will not either."""
    return RepositoryReadSettings(
        github_api_url="https://api.github.invalid",
        github_repository="dont-care/dont-care",
        github_read_token="ghp_dont-care-read-token",
        github_source_paths=source_paths
    )
