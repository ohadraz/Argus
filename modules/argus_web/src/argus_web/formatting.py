"""How the page marks up prose it shows.

The words a value comes out as are `postmortem_rendering`'s, shared with the
PDF, and so is which of them are labels with a row to lead to and which are
names that open somewhere; what is left here is what only a page does -
writing each as an anchor in markup.
"""

from __future__ import annotations

import re
from collections.abc import Collection, Iterable, Mapping
from itertools import groupby
from typing import Final

from markupsafe import Markup, escape
from postmortem_rendering import Role, Run

# What a model's Markdown is allowed to become on the page, and nothing more:
# paragraphs, between blank lines; a list, of lines opening on a dash or a star;
# bold, two asterisks either side; italics, one; and code, between backticks.
# The emphases each around a run that neither starts nor ends with a space, as
# CommonMark asks.
_A_BLANK_LINE: Final = re.compile(r"\n[ \t]*\n")
_A_LIST_ITEM: Final = re.compile(r"[-*] +(.*)")
_A_CODE_SPAN: Final = re.compile(r"`([^`]+)`")
_BOLD: Final = re.compile(r"\*\*(?=\S)(.+?)(?<=\S)\*\*")
_ITALIC: Final = re.compile(r"(?<!\*)\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)")


def with_references(prose: str, labels: Collection[str], addresses: Mapping[str, str]) -> Markup:
    """Prose with every label it cites linked to the row of that name - `C1`
    becomes `<a href="#C1">C1</a>` - and every name in `addresses` linked to
    where it opens, in a tab of its own, as every link off the page is.

    Only `labels` are linked - the ones with a row on the page - so a label
    the prose names and the page does not show stays plain text rather than
    a link to nowhere. Which words are a label or a name is
    `Run.with_references`'s to say, the same for the page as for the PDF.
    Everything else is escaped; only the links are markup.
    """
    return marked_up(Run(text=prose, role=Role.PROSE).with_references(labels, addresses))


def marked_up(runs: Iterable[Run]) -> Markup:
    """Runs `postmortem_rendering` already worded, in markup: a citation
    leading to its row, a link off the page in a tab of its own, a name said
    as one, and everything else escaped.

    For what the page shows in the postmortem's own words without being the
    postmortem - the changes the incident read, named as its rows name them."""
    return Markup("").join(_marked_up(run) for run in runs)


def from_markdown(markdown: str) -> Markup:
    """A model's Markdown in markup, through an allowlist: paragraphs, lists,
    bold, italics and code become their tags, and everything else - a link,
    a heading, a tag of the model's own - arrives as the text it was written
    as. The page marks the result safe, so anything let through here would be
    the model writing markup onto it."""
    shown: list[str] = []

    for block in _A_BLANK_LINE.split(markdown.strip()):
        for listed, run in groupby(block.splitlines(), key=_is_an_item):
            lines = list(run)

            if listed:
                items = "".join(f"<li>{_inline(_the_item_in(line))}</li>" for line in lines)
                shown.append(f"<ul>{items}</ul>")
            else:
                paragraph = "\n".join(_inline(line) for line in lines)
                shown.append(f"<p>{paragraph}</p>")

    return Markup("".join(shown))


def _is_an_item(line: str) -> bool:
    """Whether a line is one item of a list."""
    return _A_LIST_ITEM.fullmatch(line) is not None


def _the_item_in(line: str) -> str:
    """What a list line lists."""
    return _A_LIST_ITEM.sub(r"\1", line, count=1)


def _inline(text: str) -> str:
    """One line's text escaped, its bold, italics and code then made tags -
    code first and on its own, since what is between backticks is code and
    nothing else."""
    pieces = _A_CODE_SPAN.split(text)

    return "".join(
        f"<code>{escape(piece)}</code>" if is_code else
        _ITALIC.sub(r"<em>\1</em>", _BOLD.sub(r"<strong>\1</strong>", str(escape(piece))))
        for is_code, piece in ((index % 2 == 1, piece) for index, piece in enumerate(pieces))
    )


def _marked_up(run: Run) -> Markup:
    match run.role:
        case Role.CITATION:
            return Markup('<a href="#{0}">{1}</a>').format(run.address, run.text)
        case Role.LINK:
            off_the_page = Markup('<a href="{0}" target="_blank" rel="noopener noreferrer">{1}</a>')
            return off_the_page.format(run.address, run.text)
        case Role.CODE:
            return Markup("<code>{0}</code>").format(run.text)
        case _:
            return escape(run.text)
