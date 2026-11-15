"""A claim the model broke across lines, read as the sentence it is.

The model writes a paragraph and occasionally breaks it mid-clause, indenting
whatever continues. That is typesetting it did not mean and nobody asked for: a
claim is one sentence, and where it wraps is the renderer's business.

Resolved where the answer is accepted rather than in whichever view happens to
show it. One claim reaches a web page, a postmortem and a message to a human,
and a repair living in one of those is missing from the other two.

Deliberately *not* applied at the seam `escapes` runs at, which is every tool
argument of every agent. A line break is only meaningless in a value that is
one sentence by definition: Code-Fix proposes source code, and the Postmortem
writes an executive summary whose paragraph breaks are the document. Flattening
either would edit what the model meant, so the caller applies this to the
fields it knows are claims.
"""

from __future__ import annotations

import re
from typing import Final

# Any run of whitespace that contains a line break. The indent on the
# continuation goes with the break that caused it - the model indents because
# it wrapped, so the two are one piece of typesetting rather than two.
_A_LINE_BREAK: Final = re.compile(r"[ \t]*\n\s*")


def on_one_line(said: str) -> str:
    """One claim, as a sentence, however the model happened to lay it out.

    A break becomes the space it stands for rather than being dropped, because
    it is standing between two words. Padding at either end goes entirely: it
    separates the claim from nothing.
    """
    return _A_LINE_BREAK.sub(" ", said).strip()
