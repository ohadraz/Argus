"""Cutting a file into the pieces that get embedded.

A chunk is what retrieval hands back, so it has to be something a reader
recognises. Forty arbitrary lines beginning mid-function is a passage nobody can
act on; one function, whole, with the lines it occupies, is an address and an
answer at once.

Python is cut at its own boundaries, because the language already says where
they are. Everything else falls back to overlapping windows - a worse answer,
and the only one available for a file whose structure this module cannot read.
An unparseable `.py` is that case wearing a misleading suffix, so it falls back
rather than raising: a repository is allowed to hold a template or something
half-written, and trading the whole index for one such file would be a poor
bargain struck over a file nobody asked about.

Line numbers are 1-based and inclusive at both ends, which is what
`search_repository` already reports. Two retrieval channels disagreeing about
what line 7 means would send the same model to two different places.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass

PYTHON_SUFFIX = ".py"

# The nodes that are a thing rather than a statement - what a reader would call
# a definition, and what a retrieved passage is worth being.
_DEFINITIONS = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)


@dataclass(frozen=True)
class Chunk:
    """One passage of one file, and where in that file it is.

    The path and the span travel with the text because they are what make a
    retrieved passage actionable: a model that has read one goes on to read the
    whole file, and it cannot do that from the text alone.
    """

    path: str
    first_line: int
    last_line: int
    text: str


def chunks_of(path: str,
              source: str,
              *,
              max_lines: int,
              overlap: int) -> list[Chunk]:
    """Cuts `source` into the passages that will be embedded.

    Python at its own boundaries, everything else - and anything that will not
    parse - into overlapping windows. `max_lines` and `overlap` govern only the
    fallback: a function is as long as it is, and truncating one to fit a window
    would hand back a passage that stops mid-statement.

    Both are required and neither is read from `Settings` here. Cutting a file
    is a domain rule, and a domain rule has no business knowing how Argus is
    configured: the caller already holds the numbers, importing this module
    should not require an environment, and a default frozen at import is one a
    test cannot vary without monkeypatching. They are keyword-only because they
    are two integers of the same type, and a call that swapped them would cut
    the whole repository wrong while reading perfectly.

    Lines rather than tokens: the fallback exists for files whose structure is
    unknown, and a tokeniser's idea of a boundary in a file it cannot parse is
    no better informed than a line count, at more cost.
    """
    lines = source.splitlines()

    if not lines:
        return []

    if path.endswith(PYTHON_SUFFIX):
        definitions = _the_definitions_in(source)

        if definitions is not None:
            return _cut_at(definitions, path, lines)

    return _windows_over(path, lines, max_lines, overlap)


def _the_definitions_in(source: str) -> list[tuple[int, int]] | None:
    """Where each top-level function and class begins and ends, or nothing.

    `None` rather than an empty list when the source will not parse, because
    the two mean opposite things: a module with no definitions in it has a body
    that is all one passage, where one that will not parse is a file this
    module cannot read at all.
    """
    try:
        parsed = ast.parse(source)
    except SyntaxError:
        return None

    spans = []

    for node in parsed.body:
        if isinstance(node, _DEFINITIONS) and node.end_lineno is not None:
            spans.append((_where_it_really_starts(node), node.end_lineno))

    return spans


def _where_it_really_starts(node: ast.FunctionDef
                            | ast.AsyncFunctionDef
                            | ast.ClassDef) -> int:
    """The first line of a definition, decorators included.

    `ast` puts `lineno` on the `def` or the `class`, so the obvious reading
    silently drops whatever is above it - and a route or a fixture cut away
    from what registers it is a passage that no longer says what it is for.
    """
    return min([node.lineno, *(decorator.lineno for decorator in node.decorator_list)])


def _cut_at(definitions: list[tuple[int, int]],
            path: str,
            lines: list[str]) -> list[Chunk]:
    """One chunk per definition, plus whatever was left at module level.

    The remainder is not an afterthought. Imports and constants are where a
    flag's name and a module's configuration live, which is very often the
    thing the investigation named - and a cut that kept only the definitions
    would drop exactly the line the search was going to match.
    """
    covered = {
        line
        for first_line, last_line in definitions
        for line in range(first_line, last_line + 1)
    }

    chunks = [
        _a_chunk_of(path, first_line, last_line, lines)
        for first_line, last_line in definitions
    ]
    chunks.extend(_what_was_left_outside(covered, path, lines))

    return sorted(chunks, key=lambda chunk: chunk.first_line)


def _what_was_left_outside(covered: set[int],
                           path: str,
                           lines: list[str]) -> list[Chunk]:
    """Every run of lines no definition claimed, as a chunk each.

    Runs rather than one chunk, because what sits between two functions is not
    continuous with what sits above the first. A run that is nothing but blank
    lines is dropped: it embeds to nothing and would be retrieved for nothing.
    """
    chunks = []
    run: list[int] = []

    for number in range(1, len(lines) + 1):
        if number in covered:
            chunks.extend(_a_run_of(run, path, lines))
            run = []
        else:
            run.append(number)

    chunks.extend(_a_run_of(run, path, lines))

    return chunks


def _a_run_of(run: list[int], path: str, lines: list[str]) -> list[Chunk]:
    """The run as a chunk, or nothing where there was nothing worth keeping."""
    if not run:
        return []

    chunk = _a_chunk_of(path, run[0], run[-1], lines)

    return [chunk] if chunk.text.strip() else []


def _windows_over(path: str,
                  lines: list[str],
                  max_lines: int,
                  overlap: int) -> list[Chunk]:
    """The file in fixed windows, each overlapping the one before it.

    Overlapping so that a passage straddling a boundary survives whole in one
    of the two windows covering it - the cut is arbitrary, so something has to
    make it survivable.
    """
    stride = max(max_lines - overlap, 1)

    return [
        _a_chunk_of(path, first_line, min(first_line + max_lines - 1, len(lines)), lines)
        for first_line in range(1, len(lines) + 1, stride)
    ]


def _a_chunk_of(path: str, first_line: int, last_line: int, lines: list[str]) -> Chunk:
    """One span of one file, with the span said in the numbers a reader uses.

    1-based and inclusive at both ends, which is a line off the list's own
    indexing in both directions - hence the one place that conversion happens.
    """
    return Chunk(
        path=path,
        first_line=first_line,
        last_line=last_line,
        text="\n".join(lines[first_line - 1:last_line])
    )
