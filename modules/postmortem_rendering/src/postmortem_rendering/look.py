"""How a file Argus prints looks: its typefaces and the colours of its ink.

Shared by the postmortem's PDF and the executive synopsis's, so the two read as
one set - the synopsis is opened from a link and the postmortem from a link in
it, and a reader goes from one to the other.
"""

from __future__ import annotations

from pathlib import Path
from typing import Final

from fpdf import FPDF

_FONTS: Final = Path(__file__).parent / "fonts"

BODY: Final = "public-sans"
DISPLAY: Final = "source-serif"
MONO: Final = "jetbrains-mono"
FALLBACK: Final = "dejavu-sans"

INK: Final = (27, 36, 48)
MUTED: Final = (90, 102, 118)
RULE: Final = (221, 227, 234)
LINK: Final = (47, 107, 100)
CLOAK: Final = (62, 123, 116)


def with_the_typefaces(pdf: FPDF) -> None:
    """Gives `pdf` the typefaces the module ships: Source Serif 4 for headings,
    Public Sans for the body, JetBrains Mono for anything a reader might copy,
    and DejaVu Sans behind them for what they lack."""
    pdf.add_font(BODY, "", str(_FONTS / "PublicSans-Regular.ttf"))
    pdf.add_font(BODY, "B", str(_FONTS / "PublicSans-SemiBold.ttf"))
    pdf.add_font(DISPLAY, "", str(_FONTS / "SourceSerif4-Semibold.ttf"))
    pdf.add_font(MONO, "", str(_FONTS / "JetBrainsMono-Regular.ttf"))
    pdf.add_font(MONO, "B", str(_FONTS / "JetBrainsMono-Medium.ttf"))
    pdf.add_font(FALLBACK, "", str(_FONTS / "DejaVuSans.ttf"))
    pdf.add_font(FALLBACK, "B", str(_FONTS / "DejaVuSans-Bold.ttf"))
    pdf.set_fallback_fonts([FALLBACK], exact_match=False)
