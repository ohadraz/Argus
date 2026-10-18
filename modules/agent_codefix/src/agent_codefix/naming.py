"""The files the investigation's evidence names, found in the repository.

Derived, never asked for: the Investigator has no repository to look in, so a
list of files it filled in would be a guess. The evidence already names them -
a log line ends on the file and the line the fault was raised on, a change
names what it modified - and the repository's own listing says which of those
names are files it holds.

Greedy on purpose, with the listing as the safety net. A name is looked for in
every spelling the evidence uses: a path with a line or a range of lines, a
bare filename, a log's path inside the container, a dotted module, a stem. Only
what the repository holds is listed, so a greedy reading costs a word that
happens to be a file's stem, and a missed spelling costs the one file that
mattered.

What is said to be missing is narrower: only a name shaped like a file the
repository could hold - one ending in an extension its own files carry. A
dotted name never is, being far more often an attribute than a module, and a
run of slashes never is, being as often a metric's columns or a URL as a path.
A name followed by "(" is a call and never a file at all. The limit: an
attribute that is not called and ends in an extension the repository carries -
`self.lock` beside a `uv.lock` - is said to be missing.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

from pydantic import BaseModel

# A word that could name a file: a run of the characters paths, modules and
# line references are spelled in.
_A_NAME: Final = re.compile(r"[\w./:-]+")

# Where in a file a name points - `:47`, `:44-46`, `:47:12` - which is not part
# of the file's name.
_A_PLACE_IN_IT: Final = re.compile(r"(?::\d+(?:-\d+)?)+$")

# What a sentence leaves before a name and after it. A leading `/` is the
# name's own - an absolute path said missing is said as the evidence wrote it.
_BEFORE_A_NAME: Final = ",:;"
_AFTER_A_NAME: Final = ".,:;-/"

# How many trailing segments two paths must share to be one file: a package and
# its module, as an import names them. One is a filename every package has.
_A_SHARED_TAIL: Final = 2

# One part of a dotted module.
_AN_IDENTIFIER: Final = re.compile(r"[A-Za-z_]\w*")


class FilesNamed(BaseModel):
    """The repository's files the evidence names, as the repository spells
    them, and the file-shaped names it does not hold, as the evidence spelled
    them - each in the order the evidence first names it."""

    held: list[str]
    absent: list[str]


def files_named_in(claims: Sequence[str], listing: Sequence[str]) -> FilesNamed:
    """Every file in `listing` that `claims` name, and every name shaped like a
    file that no file in it answers to."""
    extensions = frozenset(filter(None, (_extension_of(path) for path in listing)))
    held: dict[str, None] = {}
    absent: dict[str, None] = {}

    for claim in claims:
        for found in _A_NAME.finditer(claim):
            if claim.startswith("(", found.end()):
                continue

            name = _A_PLACE_IN_IT.sub("", found.group(0).rstrip(_AFTER_A_NAME))
            name = name.lstrip(_BEFORE_A_NAME).rstrip(_AFTER_A_NAME)
            files = _the_files_named(name, listing, extensions) if name else []

            if files:
                held.update(dict.fromkeys(files))
            elif name and _extension_of(name) in extensions:
                absent[name] = None

    return FilesNamed(held=list(held), absent=list(absent))


def _the_files_named(name: str,
                     listing: Sequence[str],
                     extensions: frozenset[str]) -> list[str]:
    """The files in `listing` that one name answers to, by the kind of name it
    is.

    A file's name is matched at a `/` in either direction: a log written inside
    the container names `/app/src/...`, which ends with the repository's path,
    and a bare filename is the end of the repository's path. And by a shared
    tail of a package and its module, for a traceback from where the service
    was installed rather than checked out: `.../site-packages/io_shop/x.py` is
    the repository's `src/io_shop/x.py`."""
    if _extension_of(name) in extensions:
        return [path for path in listing
                if _ends(path, name) or _ends(name, path) or _share_a_tail(path, name)]

    if "/" in name:
        return [path for path in listing if _ends(path, name)]

    if "." in name:
        return _by_its_longest_resolving_prefix(name.split("."), listing)

    return [path for path in listing if _stem_of(path) == name]


def _by_its_longest_resolving_prefix(parts: list[str], listing: Sequence[str]) -> list[str]:
    """The files a dotted module names: `io_shop.spend_summary.average` is the
    function in `io_shop/spend_summary`, so the longest run of its parts that is
    a file is the file. Nothing for a name that is no module at all - a host,
    whose parts are not identifiers."""
    if not all(_AN_IDENTIFIER.fullmatch(part) for part in parts):
        return []

    for length in range(len(parts), 0, -1):
        module = "/".join(parts[:length])
        found = [path for path in listing if _ends(_without_extension(path), module)]

        if found:
            return found

    return []


def _ends(longer: str, shorter: str) -> bool:
    """Whether `longer` is `shorter`, or ends with it after a `/`."""
    return longer == shorter or longer.endswith("/" + shorter)


def _share_a_tail(one: str, other: str) -> bool:
    """Whether two paths end in the same package and module."""
    return (one.split("/")[-_A_SHARED_TAIL:] == other.split("/")[-_A_SHARED_TAIL:]
            and min(one.count("/"), other.count("/")) >= _A_SHARED_TAIL - 1)


def _extension_of(path: str) -> str | None:
    """What a file's name ends in after its last dot - none for a name with no
    dot, or whose only dot starts it (`.gitignore`)."""
    stem, dot, extension = path.rsplit("/", 1)[-1].rpartition(".")

    return extension if stem and dot else None


def _without_extension(path: str) -> str:
    """A path less what its file's name ends in."""
    extension = _extension_of(path)

    return path[:-len(extension) - 1] if extension else path


def _stem_of(path: str) -> str:
    """A file's name up to its first dot."""
    return path.rsplit("/", 1)[-1].split(".", 1)[0]
