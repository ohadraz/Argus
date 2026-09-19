"""Cutting a file into the pieces that get embedded.

A chunk is what retrieval hands back, so it has to be a thing a reader
recognises. Forty arbitrary lines starting mid-function is a passage nobody can
act on; one function, whole, with the lines it occupies, is an address and an
answer at once.

Python is cut at its own boundaries because the language already says where
they are. Everything else is cut into overlapping windows, which is a worse
answer and the only one available for a file whose structure this module cannot
read - and an unparseable `.py` is exactly that case wearing a misleading
suffix, so it falls back rather than raising.

Line numbers are 1-based and inclusive at both ends, matching what
`search_repository` already reports. Two channels that disagree about what line
7 means would send the same model to two different places.
"""

from __future__ import annotations

from math import ceil

import pytest
from argus_testkit import Assertion, Scenario, all_of
from code_index.chunking import Chunk, chunks_of

SOME_PATH = "src/io_shop/spend_summary.py"
SOME_TEXT_PATH = "README.md"


# Required by every call here and asserted by none of them: these cases cut
# Python at its own definitions, which the window bounds do not govern. The
# two cases that do assert on them name their own numbers, on the spot.
DONT_CARE_MAX_LINES = 60
DONT_CARE_OVERLAP = 10


@pytest.mark.unit
def test_each_top_level_function_becomes_its_own_chunk() -> None:
    the_first_functions_first_line = 1
    the_first_functions_last_line = 2
    the_second_functions_first_line = 5
    the_second_functions_last_line = 6

    Scenario() \
        .given(
            some_source := "\n".join([
                "def first() -> None:",          # 1 (`the_first_functions_first_line`)
                "    return None",               # 2 (`the_first_functions_last_line`)
                "",                              # 3
                "",                              # 4
                "def second() -> None:",         # 5 (`the_second_functions_first_line`)
                "    return None"                # 6 (`the_second_functions_last_line`)
            ])
        ) \
        .when(lambda: chunks_of(
            SOME_PATH, some_source,
            max_lines=DONT_CARE_MAX_LINES, overlap=DONT_CARE_OVERLAP
        )) \
        .then(
            all_of(
                _a_chunk_spanning(the_first_functions_first_line, 
                                  the_first_functions_last_line),
                _a_chunk_spanning(the_second_functions_first_line,
                                  the_second_functions_last_line),
                _every_chunk_names(SOME_PATH)
            )
        )


@pytest.mark.unit
def test_a_class_is_one_chunk_rather_than_one_per_method() -> None:
    # A method read without the class around it loses what it is a method of,
    # and the fields it touches are declared in the half that was cut away.
    the_line_number_Summary_class_starts = 1
    the_line_number_Summary_class_ends = 6

    Scenario() \
        .given(
            some_source := "\n".join([
                "class Summary:",                # 1 (`the_line_number_Summary_class_starts`)
                "    def total(self) -> int:",   # 2
                "        return 0",              # 3
                "",                              # 4
                "    def count(self) -> int:",   # 5
                "        return 0"               # 6 (`the_line_number_Summary_class_ends`)
            ])
        ) \
        .when(lambda: chunks_of(
            SOME_PATH, some_source,
            max_lines=DONT_CARE_MAX_LINES, overlap=DONT_CARE_OVERLAP
        )) \
        .then(
            all_of(
                _a_chunk_spanning(the_line_number_Summary_class_starts, 
                                  the_line_number_Summary_class_ends),
                _exactly_this_many_chunks(1)
            )
        )


@pytest.mark.unit
def test_a_decorated_function_keeps_its_decorators() -> None:
    # `ast` puts a function's `lineno` on the `def`, so the obvious reading
    # silently drops the decorator - and a route or a fixture cut away from
    # what registers it is a passage that no longer says what it is for.
    some_function_decorator_1 = "@app.get(SUMMARY_ROUTE)"
    some_function_decorator_2 = "@traced"
    the_decorators_first_line = 1
    the_functions_last_line = 4

    Scenario() \
        .given(
            some_source := "\n".join([
                some_function_decorator_1,     # 1 (`the_decorators_first_line`)
                some_function_decorator_2,     # 2
                "def summary() -> None:",      # 3
                "    return None"              # 4 (`the_functions_last_line`)
            ])
        ) \
        .when(lambda: chunks_of(
            SOME_PATH, some_source,
            max_lines=DONT_CARE_MAX_LINES, overlap=DONT_CARE_OVERLAP
        )) \
        .then(
            all_of(
                _a_chunk_spanning(the_decorators_first_line,
                                  the_functions_last_line),
                _a_chunk_containing(some_function_decorator_1)
            )
        )


@pytest.mark.unit
def test_what_is_left_at_module_level_is_a_chunk_of_its_own() -> None:
    # The imports and the constants. Dropping them loses the flag names and the
    # configuration a module is built from, which is often the very thing the
    # investigation named.
    some_import_line = "from io_shop import flags"
    some_module_level_constant = "SPEND_SUMMARY = flags.SPEND"
    the_functions_first_line = 6
    the_functions_last_line = 7

    Scenario() \
        .given(
            some_source := "\n".join([
                some_import_line,                # 1
                "",                              # 2
                some_module_level_constant,      # 3
                "",                              # 4
                "",                              # 5
                "def summary() -> None:",        # 6 (`the_functions_first_line`)
                "    return None"                # 7 (`the_functions_last_line`)
            ])
        ) \
        .when(lambda: chunks_of(
            SOME_PATH, some_source,
            max_lines=DONT_CARE_MAX_LINES, overlap=DONT_CARE_OVERLAP
        )) \
        .then(
            all_of(
                _a_chunk_containing(some_module_level_constant),
                _a_chunk_spanning(the_functions_first_line, the_functions_last_line)
            )
        )


@pytest.mark.unit
def test_a_file_that_is_not_python_is_cut_into_overlapping_windows() -> None:
    # Overlapping, so a sentence that straddles a boundary survives whole in
    # one of the two windows that cover it.
    some_lines = [
        "one",      # 1 (`the_first_line`)
        "two",      # 2 
        "three",    # 3 (`the_first_windows_last_line` and `the_second_windows_first_line`)
        "four",     # 4
        "five",     # 5 (`the_second_windows_last_line` and `the_third_windows_first_line`)
        "six"       # 6 (`the_last_line`)
    ]
    the_first_line = 1
    the_last_line = 6
    some_window_size = 3
    some_overlap = 1
    stride = some_window_size - some_overlap
    the_first_windows_last_line = the_first_line + some_window_size - 1
    the_second_windows_first_line = the_first_line + stride
    the_second_windows_last_line = the_second_windows_first_line + some_window_size - 1
    the_third_windows_first_line = the_second_windows_first_line + stride
    the_expected_num_of_chunks = ceil((the_last_line - some_overlap) / stride) 

    Scenario() \
        .given(some_source := "\n".join(some_lines)) \
        .when(
            lambda: chunks_of(
                SOME_TEXT_PATH, some_source, max_lines=some_window_size, overlap=some_overlap
            )
        ) \
        .then(
            all_of(
                _a_chunk_spanning(the_first_line, the_first_windows_last_line),
                _a_chunk_spanning(the_second_windows_first_line, the_second_windows_last_line),
                _a_chunk_spanning(the_third_windows_first_line, the_last_line),
                _exactly_this_many_chunks(the_expected_num_of_chunks)
            )
        )


@pytest.mark.unit
def test_python_that_will_not_parse_falls_back_to_windows() -> None:
    # A repository is allowed to contain a file that does not compile - a
    # template, something half-written, something for another interpreter - and
    # refusing to index the repository over one of them would trade the whole
    # index for a file nobody asked about.
    some_lines = [
        "def (((",                 # 1 (`the_first_line`)
        "    not python at all"    # 2 (`the_last_line`)
    ]
    some_window_size = 3
    some_overlap = 1
    stride = some_window_size - some_overlap
    the_first_line = 1
    the_last_line = min(len(some_lines), some_window_size)
    the_expected_num_of_chunks = ceil((the_last_line - some_overlap) / stride)

    Scenario() \
        .given(some_source := "\n".join(some_lines)) \
        .when(
            lambda: chunks_of(
                SOME_PATH, some_source, max_lines=some_window_size, overlap=some_overlap)
        ) \
        .then(
            all_of(
                _a_chunk_spanning(the_first_line, the_last_line),
                _exactly_this_many_chunks(the_expected_num_of_chunks)
            )
        )


@pytest.mark.unit
def test_a_file_with_nothing_in_it_yields_nothing() -> None:
    Scenario() \
        .given(nothing_at_all := "") \
        .when(lambda: chunks_of(
            SOME_PATH, nothing_at_all,
            max_lines=DONT_CARE_MAX_LINES, overlap=DONT_CARE_OVERLAP
        )) \
        .then(_exactly_this_many_chunks(0))


def _a_chunk_spanning(first_line: int, last_line: int) -> Assertion[list[Chunk]]:
    def a_chunk_spanning(chunks: list[Chunk]) -> bool:
        spans = [(chunk.first_line, chunk.last_line) for chunk in chunks]

        if (first_line, last_line) not in spans:
            raise AssertionError(
                f"Expected a chunk spanning lines [{first_line}-{last_line}], "
                f"and what came back spanned {spans}."
            )

        return True

    return a_chunk_spanning


def _a_chunk_containing(snippet: str) -> Assertion[list[Chunk]]:
    def a_chunk_containing(chunks: list[Chunk]) -> bool:
        if not any(snippet in chunk.text for chunk in chunks):
            raise AssertionError(
                f"Expected some chunk to contain [{snippet}], and none of the "
                f"{len(chunks)} that came back did."
            )

        return True

    return a_chunk_containing


def _every_chunk_names(path: str) -> Assertion[list[Chunk]]:
    def every_chunk_names(chunks: list[Chunk]) -> bool:
        wrong = [chunk.path for chunk in chunks if chunk.path != path]

        if wrong:
            raise AssertionError(
                f"Expected every chunk to name [{path}], and {len(wrong)} of "
                f"them named {wrong}."
            )

        return True

    return every_chunk_names


def _exactly_this_many_chunks(expected: int) -> Assertion[list[Chunk]]:
    def exactly_this_many_chunks(chunks: list[Chunk]) -> bool:
        if len(chunks) != expected:
            raise AssertionError(
                f"Expected [{expected}] chunks, and [{len(chunks)}] came back "
                f"spanning {[(c.first_line, c.last_line) for c in chunks]}."
            )

        return True

    return exactly_this_many_chunks
