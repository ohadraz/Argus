"""A sentence of Code-Fix's explanation that speaks of several pieces of code
outside its patch at once.

Every slip of this kind Code-Fix made was one. Each reader of a stored figure
was said right on its own, and then the sentence about them together - "those
readers keep trusting it" - counted among them the one reader that compares
the figure with the purchases to catch it being wrong. What a line outside the
patch does is the syntax tree's to say, so a sentence like that is found here
and put back with what the tree says.

A piece is a file of the repository the patch does not touch, a module of one
written as code by its bare name, or a function or class defined only outside
the patch's files - a name defined in several files being one piece, since
nothing in the word says which. The trigger is one sentence, or one list with
the sentence leading it, naming two or more. One piece outside the patch is how
a fix's cause is said - the scrape names `metrics`, the values file names
`http-metrics` - and is never a group.

Names count only where they are shaped like an identifier no prose word is - an
underscore, or a capital inside it - backticks or not. A plain word in backticks
is as often a value as a name: "(`metrics` != `http-metrics`)" is a port, and
the service defines a function called `metrics` too. Nothing in the word says
which, for the reason a bare word is never a file in `naming`.
"""

from __future__ import annotations

import ast
import re
from collections.abc import Mapping, Sequence
from typing import Final

from agent_codefix.naming import files_named_in

PYTHON_SUFFIX: Final = ".py"

# How few pieces outside the patch one sentence or list has to name to speak of
# them as a group.
FEWEST_PIECES_IN_A_GROUP: Final = 2

_A_PARAGRAPH_BREAK: Final = re.compile(r"\n\s*\n")
_A_SENTENCE_END: Final = re.compile(r"(?<=[.!?])\s+")
_A_BULLET: Final = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")
# An identifier standing alone: a word joined to another by a hyphen -
# `http-metrics`, a port's name - is not one, whatever its halves are called.
# Nor is a word a dot leads into another: what a dotted name calls is its last
# part, and what comes before it is a module, which is a file the file check
# finds, or an object - `metrics.portName` is a key in a values file.
_AN_IDENTIFIER: Final = re.compile(r"(?<![\w-])[A-Za-z_][A-Za-z0-9_]*(?![\w-]|\.\w)")
# What makes a word an identifier rather than prose: an underscore, or a capital
# after a lower-case letter.
_CODE_SHAPED: Final = re.compile(r"_|[a-z][A-Z]")
_A_BARE_MODULE: Final = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")


def the_group_outside(explanation: str,
                      patch: Mapping[str, str],
                      listing: Sequence[str],
                      defined: Mapping[str, Sequence[str]]) -> str | None:
    """The paragraph holding the first sentence or list of `explanation` that
    names two or more pieces of code outside `patch` - `None` where none does.

    `listing` is every file the repository holds, and `defined` each function
    and class defined outside the patch's files, with every file defining it."""
    own = _names_defined_in(patch)

    for paragraph in _A_PARAGRAPH_BREAK.split(explanation):
        for group in _groups_in(paragraph):
            if len(_pieces_in(group, patch, listing, defined, own)) >= FEWEST_PIECES_IN_A_GROUP:
                return paragraph.strip()

    return None


def _groups_in(paragraph: str) -> list[str]:
    """Each sentence of a paragraph alone, and each list whole with the sentence
    that leads it into its bullets."""
    found: list[str] = []
    lead: str | None = None
    bullets: list[str] = []

    for line in paragraph.splitlines():
        if _A_BULLET.match(line):
            bullets.append(line.strip())
            continue

        if lead is not None and bullets:
            found.append("\n".join([lead, *bullets]))

        sentences = [sentence for sentence in _A_SENTENCE_END.split(line.strip()) if sentence]
        found.extend(sentences)
        lead = sentences[-1] if sentences and sentences[-1].rstrip().endswith(":") else None
        bullets = []

    if lead is not None and bullets:
        found.append("\n".join([lead, *bullets]))
    else:
        found.extend(bullets)

    return found


def _pieces_in(text: str,
               patch: Mapping[str, str],
               listing: Sequence[str],
               defined: Mapping[str, Sequence[str]],
               own: set[str]) -> set[str]:
    """The pieces of code outside the patch one sentence or list names."""
    pieces = {path for path in files_named_in([text], listing).held if path not in patch}

    for module in _A_BARE_MODULE.findall(text):
        if _CODE_SHAPED.search(module):
            pieces.update(path for path in listing
                          if path.endswith(f"/{module}{PYTHON_SUFFIX}") and path not in patch)

    named = {name: where for name in _names_shaped_as_code(text) if name not in own
             if (where := [path for path in defined.get(name, []) if path not in patch])}
    pieces.update(where[0] for where in named.values() if len(where) == 1)

    # A name several files define is one piece of its own only where none of
    # those files is already one: beside `reconcile_monthly_totals`, the
    # `anything_disagrees` its file defines is that file, whoever else defines
    # one too.
    pieces.update(f"{name} in {len(where)} files" for name, where in named.items()
                  if len(where) > 1 and not set(where) & pieces)

    return pieces


def _names_shaped_as_code(text: str) -> set[str]:
    """Every word shaped like an identifier no prose word is."""
    return {word for word in _AN_IDENTIFIER.findall(text) if _CODE_SHAPED.search(word)}


def _names_defined_in(patch: Mapping[str, str]) -> set[str]:
    """Every function and class the patch's own Python files define."""
    names: set[str] = set()

    for path, source in patch.items():
        if not path.endswith(PYTHON_SUFFIX):
            continue

        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue

        names.update(node.name for node in ast.walk(tree)
                     if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef))

    return names
