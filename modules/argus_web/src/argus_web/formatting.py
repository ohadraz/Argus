"""How the page marks up prose it shows.

The words a value comes out as are `postmortem_rendering`'s, shared with the
PDF, and so is which of them are labels with a row to lead to and which are
names that open somewhere; what is left here is what only a page does -
writing each as an anchor in markup.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping

from markupsafe import Markup, escape
from postmortem_rendering import Role, Run


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
    return Markup("").join(_marked_up(run) for run in
                           Run(text=prose, role=Role.PROSE).with_references(labels, addresses))


def _marked_up(run: Run) -> Markup:
    match run.role:
        case Role.CITATION:
            return Markup('<a href="#{0}">{1}</a>').format(run.address, run.text)
        case Role.LINK:
            off_the_page = Markup('<a href="{0}" target="_blank" rel="noopener noreferrer">{1}</a>')
            return off_the_page.format(run.address, run.text)
        case _:
            return escape(run.text)
