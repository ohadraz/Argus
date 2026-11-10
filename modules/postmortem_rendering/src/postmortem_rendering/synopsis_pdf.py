"""The executive synopsis printed: the file its Slack message links to.

Printed by the postmortem's own layout code (`pdf`), so the two files read as
one set - the same masthead and mark, headings, figure tiles and ruled tables.
This is where a caller finds it; how it is drawn is `pdf`'s.
"""

from __future__ import annotations

from postmortem_rendering.pdf import synopsis_as_pdf

__all__ = ["synopsis_as_pdf"]
