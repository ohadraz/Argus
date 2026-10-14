"""How the page marks up prose it shows.

The words a value comes out as are `postmortem_rendering`'s, shared with the
PDF, and so is which of them are labels with a row to lead to; what is left
here is what only a page does - writing each such label as an anchor in markup.
"""

from __future__ import annotations

from collections.abc import Collection

from markupsafe import Markup, escape
from postmortem_rendering import Role, Run


def with_references(prose: str, labels: Collection[str]) -> Markup:
    """Prose with every label it cites linked to the row of that name: `C1`
    becomes `<a href="#C1">C1</a>`.

    Only `labels` are linked - the ones with a row on the page - so a label
    the prose names and the page does not show stays plain text rather than
    a link to nowhere. Which words are a label is `Run.with_citations`'s to
    say, the same for the page as for the PDF. Everything else is escaped;
    only the links are markup.
    """
    return Markup("").join(
        Markup('<a href="#{0}">{1}</a>').format(run.address, run.text)
        if run.role is Role.CITATION else escape(run.text)
        for run in Run(text=prose, role=Role.PROSE).with_citations(labels))
