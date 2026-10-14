"""The postmortem printed: the same words as the page, in the same order, in a
file a reader keeps, forwards and attaches.

Nothing here decides what the document says - every word is in the values
`render` worked out. What is decided here is how it looks on paper, and that
follows the layout agreed for it - a mock drawn as an HTML page (artifact
3Jp9XdPuqg9YTBmajDTHnA), whose pixel sizes the figures below convert: Argus's
mark on the first page's masthead, the teal of its cloak for the rules, the
section markers and the links, a serif for the title and headings, figures in
tiles, tables ruled across rather than boxed, and a running header and footer
so any one page can be traced to its incident. Times are UTC alone, as the
values say them: a file has no reader's clock to say them again on.

The typefaces ship with the module: Source Serif 4 for headings, Public Sans
for the body and JetBrains Mono for anything a reader might copy. DejaVu Sans
stands behind them for what they lack - Cyrillic in Public Sans, the review
checklist's ticks - and a character none of them carries is left out of its
line while fpdf2 logs it, so the file is still made.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from typing import Final

from fpdf import FPDF
from fpdf.enums import TableBordersLayout, TableBorderStyle, TableCellStyle
from fpdf.fonts import FontFace
from fpdf.util import Padding

from postmortem_rendering.impact import Card
from postmortem_rendering.lines import Line, Role, Run
from postmortem_rendering.rendering import RenderedPostmortem

_PACKAGE: Final = Path(__file__).parent
_FONTS: Final = _PACKAGE / "fonts"
_LOGO: Final = _PACKAGE / "assets" / "argus.jpg"

_BODY: Final = "public-sans"
_DISPLAY: Final = "source-serif"
_MONO: Final = "jetbrains-mono"
_FALLBACK: Final = "dejavu-sans"

# A4, in millimetres, with the mock's margins.
_PAGE_WIDTH: Final = 210.0
_SIDE: Final = 18.0
_TOP: Final = 17.0
_WIDTH: Final = _PAGE_WIDTH - 2 * _SIDE
_LOGO_SIDE: Final = 32.0
# Where a later page's content starts: under the running header's rule, with
# the mock's 8px of padding and 16px of gap.
_BELOW_THE_HEADER: Final = _TOP + 5.5 + 4.2

# Type sizes in points, each the mock's pixel size at 96 to the inch.
_TITLE_PT: Final = 18.0
_HEADING_PT: Final = 11.25
_TEXT_PT: Final = 9.4
_TABLE_PT: Final = 8.25
_SMALL_PT: Final = 7.5
_TINY_PT: Final = 6.75
_FIGURE_PT: Final = 10.5
_LABEL_PT: Final = 7.9
_LINE: Final = 5.0

_INK: Final = (27, 36, 48)
_MUTED: Final = (90, 102, 118)
_RULE: Final = (221, 227, 234)
_LINK: Final = (47, 107, 100)
_CLOAK: Final = (62, 123, 116)
_RED: Final = (179, 38, 30)
_GREEN: Final = (46, 125, 79)

_BULLET: Final = "•"


class _Sheet(FPDF):
    """A4 with the running header from the second page on, and a footer on
    every page saying when the document was written and which page this is.

    It also keeps the links inside the file: one per label a row goes by,
    which every citation of that label leads to and which lands where the row
    is drawn.
    """

    def __init__(self, rendered: RenderedPostmortem) -> None:
        super().__init__(format="A4")
        self._title = rendered.title.said
        self._incident_id = rendered.incident_id
        written = next((run.text for run in rendered.head.written_by.runs
                        if run.role is Role.MOMENT), "")
        self._written = f"Argus postmortem · written {written}"
        self.labels = rendered.labels
        self._citations: dict[str, int] = {}

    def citation(self, label: str) -> int:
        """The link every citation of `label` goes by."""
        if label not in self._citations:
            self._citations[label] = self.add_link()
        return self._citations[label]

    def lands_at(self, label: str, page: int, y: float) -> None:
        """Lands the links citing `label` at `y` on `page`."""
        self.set_link(self.citation(label), y=y, page=page)

    def header(self) -> None:
        if self.page_no() == 1:
            return

        self.set_y(_TOP)
        self.set_text_color(*_INK)
        self.set_font(_BODY, "B", _SMALL_PT)
        self.set_char_spacing(1.6)
        self.cell(16, 4, "ARGUS")
        self.set_char_spacing(0)
        self.set_font(_MONO, "", _SMALL_PT)
        id_width = self.get_string_width(self._incident_id)
        self.set_font(_BODY, "", _SMALL_PT)
        self.set_text_color(*_MUTED)
        title_width = _WIDTH - 16 - id_width - 3
        self.cell(title_width, 4, self._shortened(self._title, title_width - 3))
        self.set_font(_MONO, "", _SMALL_PT)
        self.cell(id_width, 4, self._incident_id, align="R")
        self._rule(_TOP + 5.5, _CLOAK, 0.3)
        self.set_y(_BELOW_THE_HEADER)

    def footer(self) -> None:
        self.set_y(-15)
        self._rule(self.get_y(), _RULE, 0.26)
        self.set_y(-13.5)
        self.set_font(_BODY, "", 7.1)
        self.set_text_color(*_MUTED)
        self.cell(_WIDTH / 2, 4, self._written)
        self.cell(_WIDTH / 2, 4, f"Page {self.page_no()} of {{nb}}", align="R")

    def _rule(self, y: float, colour: tuple[int, int, int], width: float) -> None:
        self.set_draw_color(*colour)
        self.set_line_width(width)
        self.line(_SIDE, y, _SIDE + _WIDTH, y)

    def _shortened(self, text: str, width: float) -> str:
        if self.get_string_width(text) <= width:
            return text
        while text and self.get_string_width(f"{text}…") > width:
            text = text[:-1]
        return f"{text.rstrip()}…"


def as_pdf(rendered: RenderedPostmortem) -> bytes:
    """The document as a PDF, section by section in the order `rendered`
    names them."""
    pdf = _Sheet(rendered)
    pdf.set_margins(_SIDE, _TOP, _SIDE)
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_font(_BODY, "", str(_FONTS / "PublicSans-Regular.ttf"))
    pdf.add_font(_BODY, "B", str(_FONTS / "PublicSans-SemiBold.ttf"))
    pdf.add_font(_DISPLAY, "", str(_FONTS / "SourceSerif4-Semibold.ttf"))
    pdf.add_font(_MONO, "", str(_FONTS / "JetBrainsMono-Regular.ttf"))
    pdf.add_font(_MONO, "B", str(_FONTS / "JetBrainsMono-Medium.ttf"))
    pdf.add_font(_FALLBACK, "", str(_FONTS / "DejaVuSans.ttf"))
    pdf.add_font(_FALLBACK, "B", str(_FONTS / "DejaVuSans-Bold.ttf"))
    pdf.set_fallback_fonts([_FALLBACK], exact_match=False)
    pdf.set_title(rendered.title.said)
    pdf.set_creator("Argus")
    pdf.add_page()

    _the_masthead(pdf, rendered)

    for key, heading in rendered.headings.items():
        _a_heading(pdf, f"{heading} {rendered.timeline.zone}" if key == "timeline" else heading)
        _SECTIONS[key](pdf, rendered)

    return bytes(pdf.output())


def _the_masthead(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    """The first page's head: what the document is and which incident, the
    title, the incident's and the document's times, and Argus's mark in the
    corner - then a teal rule, and how finished it is and who ended it."""
    head = rendered.head
    left_width = _WIDTH - _LOGO_SIDE - 5.3
    logo_x = _SIDE + _WIDTH - _LOGO_SIDE

    pdf.image(str(_LOGO), x=logo_x, y=_TOP, w=_LOGO_SIDE, h=_LOGO_SIDE)
    pdf.set_draw_color(*_CLOAK)
    pdf.set_line_width(0.4)
    pdf.rect(logo_x, _TOP, _LOGO_SIDE, _LOGO_SIDE, round_corners=True, corner_radius=0.8)

    pdf.set_right_margin(_SIDE + _WIDTH - left_width)
    pdf.set_xy(_SIDE, _TOP + 1)
    _furniture(pdf, "INCIDENT POSTMORTEM", 1.0)
    pdf.ln(7)
    _furniture(pdf, "INCIDENT", 0.6)
    pdf.set_font(_MONO, "", _TABLE_PT)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 4, f" {rendered.incident_id}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)
    pdf.set_font(_DISPLAY, "", _TITLE_PT)
    pdf.multi_cell(left_width, 8, rendered.title.said, align="L",
                   new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4.5)
    # The two times a reader most easily takes for each other sit together under
    # the title, each labelled; how finished it is and who ended it go below
    # the rule.
    rows = dict(zip(head.labels, (head.incident, head.date, head.status, head.written_by,
                                  head.ended_by), strict=True))
    incident, date, status, written_by, ended_by = head.labels
    for label in (incident, date, written_by):
        _a_term(pdf, label, rows[label])
    pdf.set_right_margin(_SIDE)

    rule_y = max(pdf.get_y(), _TOP + _LOGO_SIDE) + 6
    pdf.set_draw_color(*_CLOAK)
    pdf.set_line_width(0.4)
    pdf.line(_SIDE, rule_y, _SIDE + _WIDTH, rule_y)
    pdf.set_y(rule_y + 8)
    for label in (status, ended_by):
        _a_term(pdf, label, rows[label])


def _furniture(pdf: _Sheet, text: str, spacing: float) -> None:
    """A small capitalised label the layout prints, not the document."""
    pdf.set_font(_BODY, "B", _SMALL_PT)
    pdf.set_text_color(*_MUTED)
    pdf.set_char_spacing(spacing)
    pdf.write(4, text)
    pdf.set_char_spacing(0)


def _a_term(pdf: _Sheet, label: str, line: Line, label_width: float = 19.0) -> None:
    """A labelled row: the label in its column, the line wrapping beside it."""
    left = pdf.l_margin
    pdf.set_x(left)
    pdf.set_font(_BODY, "", _TABLE_PT)
    pdf.set_text_color(*_MUTED)
    pdf.cell(label_width, 4.6, label)
    pdf.set_left_margin(left + label_width)
    _runs(pdf, line.runs, _TABLE_PT, 4.6)
    pdf.ln(5.6)
    pdf.set_left_margin(left)


def _a_heading(pdf: _Sheet, heading: str) -> None:
    """A section's heading, a teal square before it, kept with what follows -
    and with no space above it where it opens a page."""
    if pdf.will_page_break(26):
        pdf.add_page()
    if pdf.get_y() > _BELOW_THE_HEADER + 0.5:
        pdf.ln(6)
    y = pdf.get_y()
    pdf.set_fill_color(*_CLOAK)
    pdf.rect(_SIDE, y + 1.5, 2.1, 2.1, style="F")
    pdf.set_x(_SIDE + 4.2)
    pdf.set_font(_DISPLAY, "", _HEADING_PT)
    pdf.set_text_color(*_INK)
    pdf.cell(0, 5.2, heading, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(2.0)


def _a_subheading(pdf: _Sheet, heading: str, space_above: float = 3.6) -> None:
    """A heading inside a section, set at the body's size so it is never
    smaller than what it introduces, and kept close to it."""
    pdf.ln(space_above)
    pdf.set_x(pdf.l_margin)
    pdf.set_font(_BODY, "B", _TEXT_PT)
    pdf.set_text_color(*_INK)
    pdf.cell(0, _LINE, heading, new_x="LMARGIN", new_y="NEXT")
    pdf.ln(1.0)


def _cited(pdf: _Sheet, runs: Sequence[Run]) -> Iterator[Run]:
    """The runs with every label the prose cites cut out as a citation of the
    row it names."""
    for run in runs:
        yield from run.with_citations(pdf.labels) if run.role is Role.PROSE else (run,)


def _link(pdf: _Sheet, run: Run) -> str | int:
    """Where a run leads: a citation to its row, a link to its address, and
    anything else nowhere."""
    if run.role is Role.CITATION and run.address:
        return pdf.citation(run.address)
    return run.address or ""


def _runs(pdf: _Sheet, runs: Sequence[Run], size: float, height: float) -> None:
    """Runs written inline, wrapping at the margins in force, each set in what
    its role looks like."""
    for run in _cited(pdf, runs):
        family, style, colour, text, pt = _BODY, "", _INK, run.text, size

        match run.role:
            case Role.CODE:
                family, pt = _MONO, size * 0.9
            case Role.STRONG | Role.TO_STATE | Role.STATUS:
                style = "B"
            case Role.FROM_STATE:
                style, colour = "S", _MUTED
            case Role.QUOTE:
                text = f"“{run.text}”"
            case Role.LINK | Role.CITATION:
                colour = _LINK
            case Role.PLAIN | Role.PROSE | Role.NARRATION | Role.MOMENT:
                pass

        pdf.set_font(family, style, pt)
        pdf.set_text_color(*colour)
        pdf.write(height, text, link=_link(pdf, run))
    pdf.set_text_color(*_INK)


def _a_paragraph(pdf: _Sheet, line: Line, size: float = _TEXT_PT, height: float = _LINE) -> None:
    pdf.set_x(pdf.l_margin)
    _runs(pdf, line.runs, size, height)
    pdf.ln(height + 1)


def _quiet(pdf: _Sheet, said: str) -> None:
    """A note set small and muted - a sentence said in place of something
    absent, or one beside the figures."""
    pdf.set_font(_BODY, "", 7.9)
    pdf.set_text_color(*_MUTED)
    pdf.multi_cell(0, 4, said, align="L", new_x="LMARGIN", new_y="NEXT")
    pdf.set_text_color(*_INK)


def _an_item(pdf: _Sheet, runs: Sequence[Run], size: float = _TEXT_PT, after: float = 1.0,
             indent: float = 4.2) -> None:
    """A bulleted item: a muted bullet at the body's size in its own column,
    then the runs with a hanging indent."""
    left = pdf.l_margin
    pdf.set_x(left)
    pdf.set_font(_BODY, "", _TEXT_PT)
    pdf.set_text_color(*_MUTED)
    pdf.cell(indent, _LINE, _BULLET)
    pdf.set_left_margin(left + indent)
    _runs(pdf, runs, size, _LINE)
    pdf.ln(_LINE + after)
    pdf.set_left_margin(left)


def _beneath(pdf: _Sheet, runs: Sequence[Run], indent: float, colour: tuple[int, int, int],
             height: float = 4.2, size: float = _TABLE_PT, after: float = 0.6) -> None:
    """A smaller line under an item, at the item's indent."""
    left = pdf.l_margin
    pdf.set_left_margin(left + indent)
    pdf.set_x(left + indent)
    for run in _cited(pdf, runs):
        pdf.set_font(_BODY, "B" if run.role is Role.STATUS else "", size)
        pdf.set_text_color(*(_LINK if run.role is Role.CITATION else colour))
        pdf.write(height, run.text, link=_link(pdf, run))
    pdf.ln(height + after)
    pdf.set_left_margin(left)
    pdf.set_text_color(*_INK)


def _tiles(pdf: _Sheet, cards: Sequence[Card]) -> None:
    """The figures across in bordered tiles, each above what it is."""
    gap, pad_x, pad_y = 2.1, 2.4, 1.9
    width = (_WIDTH - gap * (len(cards) - 1)) / len(cards)

    pdf.set_font(_BODY, "", 7.1)
    lines = max(_lines_needed(pdf, width - 2 * pad_x, card.label) for card in cards)
    height = 2 * pad_y + 5.6 + lines * 3.4
    if pdf.will_page_break(height + 2):
        pdf.add_page()

    top = pdf.get_y()
    pdf.set_draw_color(*_RULE)
    pdf.set_line_width(0.26)
    for place, card in enumerate(cards):
        x = _SIDE + place * (width + gap)
        pdf.rect(x, top, width, height)
        pdf.set_xy(x + pad_x, top + pad_y)
        pdf.set_font(_MONO, "", _FIGURE_PT)
        pdf.set_text_color(*_INK)
        pdf.cell(width - 2 * pad_x, 5.6, card.value)
        pdf.set_xy(x + pad_x, top + pad_y + 5.6)
        pdf.set_font(_BODY, "", 7.1)
        pdf.set_text_color(*_MUTED)
        pdf.multi_cell(width - 2 * pad_x, 3.4, card.label, align="L")
    pdf.set_xy(_SIDE, top + height + 2)


def _lines_needed(pdf: _Sheet, width: float, text: str) -> int:
    """How many lines `text` wraps to at `width` in the font in force."""
    lines = pdf.multi_cell(width, 3.4, text, dry_run=True, output="LINES")
    assert isinstance(lines, list)
    return len(lines)


# A cell's text, how it is set, and where it links - `None` for each of the
# last two where it is plain body text going nowhere. Or a line of body text
# that may cite a label, which a table cell cannot set a part of as a link -
# so the table leaves the cell empty, and the line is written into it after.
type _Cell = tuple[str, FontFace | None, str | None] | Line

_CELL_LINE: Final = 4.2
_CELL_PADDING: Final = Padding(top=1.2, right=2.1, bottom=1.2, left=0)

_TIME: Final = FontFace(family=_MONO, size_pt=_TABLE_PT * 0.95)
_NUMBER: Final = FontFace(family=_MONO, emphasis="BOLD", size_pt=_TABLE_PT * 0.95)
_MARKER: Final = FontFace(family=_MONO, emphasis="BOLD", size_pt=_TINY_PT, color=_RED)
_UNOWNED: Final = FontFace(family=_BODY, emphasis="BOLD", color=_RED)
_DONE: Final = FontFace(family=_BODY, emphasis="BOLD", color=_GREEN)
_LINKED: Final = FontFace(family=_BODY, color=_LINK)


class _RuledAcross(TableBordersLayout):
    """Rules between rows only, the one under the headings in ink as the agreed
    layout draws it, the rest in the light rule colour.

    Asked for each cell's borders as the cell is drawn, with the page at its
    row's top and its left edge, it is also the one place that knows where a
    cell is. So it keeps where each row under the headings was drawn - `tops`,
    its page and top by its place among them - and writes each line in `lines`
    into its cell there and then, so the line is read in its cell's place.
    """

    def __init__(self, pdf: _Sheet, lines: dict[tuple[int, int], tuple[Line, float]]) -> None:
        self._pdf = pdf
        self._lines = lines
        self.tops: dict[int, tuple[int, float]] = {}

    def cell_style_getter(self, row_idx: int, col_idx: int, col_pos: int,
                          num_heading_rows: int, num_rows: int, num_col_idx: int,
                          num_col_pos: int) -> TableCellStyle:
        if row_idx >= num_heading_rows:
            body_row = row_idx - num_heading_rows
            if col_idx == 0:
                self.tops[body_row] = (self._pdf.page, self._pdf.y)
            if (body_row, col_idx) in self._lines:
                line, width = self._lines[body_row, col_idx]
                _a_line_in_a_cell(self._pdf, line, width)

        under_the_headings = num_heading_rows > 0 and row_idx == num_heading_rows - 1
        return TableCellStyle(
            left=False,
            right=False,
            top=row_idx > 0 and row_idx != num_heading_rows,
            bottom=(TableBorderStyle(thickness=0.26, color=_INK) if under_the_headings
                    else row_idx < num_rows - 1))


def _a_table(pdf: _Sheet, headings: Sequence[str] | None, rows: Sequence[Sequence[_Cell]],
             widths: Sequence[float], align: Sequence[str] | None = None,
             landings: Sequence[str | None] = ()) -> None:
    """A table ruled across between its rows, its headings small and
    capitalised over an ink rule and repeated on every page it runs onto - or
    a table with no headings where `headings` is `None`. `widths` are in
    millimetres; `align` sets each column, left where it is not given;
    `landings` is the label each row goes by, `None` for a row without one.

    A cell given as a line is left empty, as tall as the line needs, and the
    line written into it as its row is drawn."""
    pdf.set_font(_BODY, "", _TABLE_PT)
    pdf.set_text_color(*_INK)
    pdf.set_draw_color(*_RULE)
    pdf.set_fill_color(255, 255, 255)
    pdf.set_line_width(0.26)
    aligned = list(align) if align else ["L"] * len(widths)
    layout = _RuledAcross(pdf, {(place, column): (cell, widths[column])
                                for place, cells in enumerate(rows)
                                for column, cell in enumerate(cells)
                                if isinstance(cell, Line)})
    with pdf.table(col_widths=tuple(widths), width=sum(widths), align="LEFT",
                   text_align="LEFT", v_align="TOP", line_height=_CELL_LINE,
                   borders_layout=layout, padding=_CELL_PADDING,
                   first_row_as_headings=headings is not None,
                   headings_style=FontFace(family=_BODY, emphasis="BOLD", size_pt=_TINY_PT,
                                           color=_MUTED)) as table:
        if headings is not None:
            heading_row = table.row()
            for heading, side in zip(headings, aligned, strict=True):
                heading_row.cell(heading.upper(), align=side)
        for cells in rows:
            row = table.row(min_height=max(
                (_cell_height(pdf, cell.said, width)
                 for cell, width in zip(cells, widths, strict=True) if isinstance(cell, Line)),
                default=None))
            for cell, side in zip(cells, aligned, strict=True):
                if isinstance(cell, Line):
                    row.cell("", align=side)
                else:
                    text, style, address = cell
                    row.cell(text, style=style, link=address, align=side)

    for place, label in enumerate(landings):
        if label is not None:
            pdf.lands_at(label, *layout.tops[place])
    pdf.ln(1.5)


def _cell_lines(pdf: _Sheet, text: str, width: float) -> list[str]:
    """`text` broken into the lines a table cell `width` wide breaks it into,
    in the font in force."""
    lines = pdf.multi_cell(width, _CELL_LINE, text, max_line_height=_CELL_LINE,
                           padding=_CELL_PADDING, dry_run=True, output="LINES")
    assert isinstance(lines, list)
    return lines


def _cell_height(pdf: _Sheet, text: str, width: float) -> float:
    """How tall a table cell `width` wide is with `text` in it, in body text."""
    pdf.set_font(_BODY, "", _TABLE_PT)
    height = pdf.multi_cell(width, _CELL_LINE, text, max_line_height=_CELL_LINE,
                            padding=_CELL_PADDING, dry_run=True, output="HEIGHT")
    assert isinstance(height, float)
    return height


def _a_line_in_a_cell(pdf: _Sheet, line: Line, width: float) -> None:
    """A line written in body text into the cell the table left for it, from
    the cell's top left corner where the page is now: broken where the table
    would have broken it, and set run by run, so a citation in it is a link.
    The page is left where it was found."""
    x, top = pdf.x, pdf.y
    pdf.set_font(_BODY, "", _TABLE_PT)
    text = line.said
    runs: list[tuple[int, Run]] = []
    start = 0
    for run in _cited(pdf, line.runs):
        runs.append((start, run))
        start += len(run.text)

    # The table sets a cell's text in from the left by the cell margin, there
    # being no padding on that side; each piece here is set flush against the
    # one before it.
    left, margin = x + pdf.c_margin, pdf.c_margin
    pdf.c_margin = 0
    cursor = 0
    for place, wrapped in enumerate(_cell_lines(pdf, text, width)):
        begins = text.find(wrapped, cursor)
        ends = cursor = begins + len(wrapped)
        pdf.set_xy(left, top + _CELL_PADDING.top + place * _CELL_LINE)
        for at, run in runs:
            piece = text[max(at, begins):min(at + len(run.text), ends)]
            if not piece:
                continue
            pdf.set_text_color(*(_LINK if run.role is Role.CITATION else _INK))
            pdf.cell(pdf.get_string_width(piece), _CELL_LINE, piece, link=_link(pdf, run))
    pdf.c_margin = margin
    pdf.set_text_color(*_INK)
    pdf.set_xy(x, top)


def _the_summary(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    if rendered.summary is not None:
        _a_paragraph(pdf, rendered.summary)
    elif rendered.summary_absent:
        _quiet(pdf, rendered.summary_absent)


def _the_impact(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    impact = rendered.impact
    _tiles(pdf, impact.cards)
    for said in (impact.finding, impact.unobserved):
        if said:
            _quiet(pdf, said)


def _the_cause(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    cause = rendered.cause
    if cause.root_cause is not None:
        _a_paragraph(pdf, cause.root_cause)

    _a_subheading(pdf, cause.chain_heading)
    if cause.chain_absent:
        _quiet(pdf, cause.chain_absent)
    for link in cause.chain:
        _a_link_in_the_chain(pdf, link.place, link.claim.runs,
                             cause.evidence_label, link.evidence)

    _a_subheading(pdf, cause.factors_heading)
    if cause.factors_absent:
        _quiet(pdf, cause.factors_absent)
    for factor in cause.factors:
        _a_factor(pdf, factor.text.runs, factor.addressed_by)


def _a_link_in_the_chain(pdf: _Sheet, place: str, claim: Sequence[Run], evidence_label: str,
                         evidence: Sequence[str]) -> None:
    """One step: its place in a quiet column of its own, the claim beside it,
    and what it rests on on its own line under the claim."""
    left, label_width = pdf.l_margin, 16.0
    pdf.set_x(left)
    pdf.set_font(_BODY, "", _TABLE_PT)
    pdf.set_text_color(*_MUTED)
    pdf.cell(label_width, _LINE, place)
    pdf.set_left_margin(left + label_width)
    _runs(pdf, claim, _TEXT_PT, _LINE)
    pdf.ln(_LINE)
    if evidence:
        pdf.ln(0.4)
        pdf.set_x(left + label_width)
        pdf.set_text_color(*_MUTED)
        pdf.set_font(_BODY, "B", _SMALL_PT)
        pdf.write(3.8, f"{evidence_label} ")
        pdf.set_font(_BODY, "", _SMALL_PT)
        pdf.write(3.8, "; ".join(evidence))
        pdf.ln(3.8)
    pdf.ln(2.2)
    pdf.set_left_margin(left)
    pdf.set_text_color(*_INK)


def _a_factor(pdf: _Sheet, text: Sequence[Run], addressed_by: Line | None) -> None:
    """A contributing factor as a bulleted item, the items that answer it set
    after it in the face the action-items table names them in - each a link to
    its row there."""
    left = pdf.l_margin
    pdf.set_x(left)
    pdf.set_font(_BODY, "", _TEXT_PT)
    pdf.set_text_color(*_MUTED)
    pdf.cell(4.2, _LINE, _BULLET)
    pdf.set_left_margin(left + 4.2)
    _runs(pdf, text, _TEXT_PT, _LINE)
    if addressed_by is not None:
        pdf.set_x(pdf.get_x() + 1.5)
        pdf.set_font(_MONO, "", _SMALL_PT)
        for run in _cited(pdf, addressed_by.runs):
            pdf.set_text_color(*(_LINK if run.role is Role.CITATION else _MUTED))
            pdf.write(_LINE, run.text, link=_link(pdf, run))
    pdf.ln(_LINE + 1.0)
    pdf.set_left_margin(left)
    pdf.set_text_color(*_INK)


def _the_hypotheses(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    """Each candidate under the label the prose cites it by, then what it
    said, how confident the ranking was and what became of it."""
    hypotheses = rendered.hypotheses
    if hypotheses.absent:
        _quiet(pdf, hypotheses.absent)
        return

    _a_table(pdf, hypotheses.headings,
             [[(row.label, _NUMBER, None), (row.summary, None, None),
               (row.confidence, _TIME, None), (row.result, None, None)]
              for row in hypotheses.rows],
             widths=(13, 91, 26, 44), landings=[row.label for row in hypotheses.rows])


def _the_trigger(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    trigger = rendered.trigger
    if trigger.line is not None:
        _a_paragraph(pdf, trigger.line)
    elif trigger.absent:
        _quiet(pdf, trigger.absent)


def _the_resolution(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    taken = rendered.actions_taken
    if taken.person is not None:
        _a_paragraph(pdf, taken.person)

    steps = [*taken.steps, *([taken.fix] if taken.fix else [])]
    if steps:
        rows: list[list[_Cell]] = []
        for step in steps:
            address = next((run.address for run in step.action.runs if run.address), None)
            rows.append([(step.at, _TIME, None),
                         (step.action.said, _LINKED if address else None, address),
                         (step.by, None, None), (step.kind, None, None),
                         (step.outcome, None, None)])
        _a_table(pdf, taken.headings, rows, widths=(18, 54, 24, 37, 41),
                 landings=[step.label for step in steps])
    elif taken.absent:
        _quiet(pdf, taken.absent)


def _the_detection(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    detection = rendered.detection
    if detection.line is not None:
        _a_paragraph(pdf, detection.line)
    elif detection.absent:
        _quiet(pdf, detection.absent)


def _the_action_items(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    items = rendered.action_items
    if items.absent:
        _quiet(pdf, items.absent)
    else:
        rows: list[list[_Cell]] = []
        for row in items.rows:
            address = row.tracking.runs[0].address
            rows.append([(row.number, _NUMBER, None), row.text,
                         (row.type, None, None),
                         (row.owner, _UNOWNED if row.unassigned else None, None),
                         (row.tracking.said, _LINKED if address else None, address),
                         (row.status, _DONE if row.status == "done" else None, None)])
        _a_table(pdf, items.headings, rows, widths=(13, 48, 17, 21, 62, 13),
                 landings=[row.number for row in items.rows])

    if items.recommended is not None:
        _a_paragraph(pdf, items.recommended)


def _the_lessons(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    """The three lists side by side, so what went well is weighed against what
    went wrong at a glance."""
    if pdf.will_page_break(30):
        pdf.add_page()

    gap = 3.2
    width = (_WIDTH - 2 * gap) / 3
    top = pdf.get_y()
    bottom = top

    for place, lessons in enumerate(rendered.lessons):
        left = _SIDE + place * (width + gap)
        pdf.set_left_margin(left)
        pdf.set_right_margin(_PAGE_WIDTH - left - width)
        pdf.set_xy(left, top)
        _a_subheading(pdf, lessons.heading, space_above=0)
        if lessons.absent:
            _quiet(pdf, lessons.absent)
        for lesson in lessons.items:
            _an_item(pdf, lesson.runs, size=_TABLE_PT, indent=3.4)
        bottom = max(bottom, pdf.get_y())

    pdf.set_left_margin(_SIDE)
    pdf.set_right_margin(_SIDE)
    pdf.set_xy(_SIDE, bottom)


def _the_timeline(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    timeline = rendered.timeline
    if timeline.absent:
        _quiet(pdf, timeline.absent)
        return

    _a_table(pdf, None,
             [[(row.at, _TIME, None), (row.marker or "", _MARKER, None),
               (" ".join(part for part in (row.who, row.text.said) if part), None, None)]
              for row in timeline.rows],
             widths=(31, 24, 119), align=("R", "L", "L"),
             landings=[row.label for row in timeline.rows])


def _the_leads(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    """Each lead as an item, what the investigation made of it and what it
    changed close under it."""
    for lead in rendered.leads:
        _an_item(pdf, lead.said.runs, after=0.6)
        _beneath(pdf, lead.weighing.runs, indent=4.2, colour=_INK)
        if lead.effect is not None:
            _beneath(pdf, lead.effect.runs, indent=4.2, colour=_MUTED)
        pdf.ln(3.0)


def _the_cost(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    _tiles(pdf, rendered.cost)


def _the_supporting_information(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    """A reference list, as the agreed layout sets it: what each source is in a quiet
    column, and the source beside it - an address in a face a reader can
    copy from paper. Each line's words up to its first colon are its label,
    and the assumptions are the list's last entry."""
    supporting = rendered.supporting
    for line in supporting.links:
        opening, *rest = line.runs
        label, _, remainder = opening.text.partition(": ")
        value = [Run(text=remainder), *rest] if remainder else rest
        _a_reference(pdf, label, [value])

    assumptions = [[*assumption.runs] for assumption in supporting.assumptions]
    if supporting.assumptions_absent:
        assumptions = [[Run(text=supporting.assumptions_absent)]]
    _a_reference(pdf, supporting.assumptions_heading, assumptions)


def _a_reference(pdf: _Sheet, label: str, values: Sequence[Sequence[Run]]) -> None:
    left, label_width, height = pdf.l_margin, 32.0, 4.4
    pdf.set_x(left)
    pdf.set_font(_BODY, "", _TABLE_PT)
    pdf.set_text_color(*_MUTED)
    pdf.cell(label_width, height, label)
    pdf.set_left_margin(left + label_width)
    for place, runs in enumerate(values):
        if place:
            pdf.ln(height + 1.0)
            pdf.set_x(left + label_width)
        for run in _cited(pdf, runs):
            if run.role is Role.LINK:
                pdf.set_font(_MONO, "", 7.1)
                pdf.set_text_color(*_LINK)
            else:
                pdf.set_font(_BODY, "B" if run.role is Role.STATUS else "", _TABLE_PT)
                pdf.set_text_color(*(_LINK if run.role is Role.CITATION else _INK))
            pdf.write(height, run.text, link=_link(pdf, run))
    pdf.ln(height + 1.1)
    pdf.set_left_margin(left)
    pdf.set_text_color(*_INK)


def _the_review(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    """Each check: its mark in a column of its own, the criterion at the body's
    size, and what the mark means set quiet at the right margin, read as a
    status rather than as part of the criterion."""
    review = rendered.review
    if review.absent:
        _quiet(pdf, review.absent)
    for row in review.rows:
        y = pdf.get_y()
        pdf.set_font(_BODY, "", _LABEL_PT)
        pdf.set_text_color(*_MUTED)
        pdf.set_xy(_SIDE + _WIDTH - 40, y)
        pdf.cell(40, _LINE, row.meaning, align="R")
        pdf.set_xy(_SIDE, y)
        pdf.set_font(_FALLBACK, "B", _TEXT_PT)
        pdf.set_text_color(*(_GREEN if row.met == "yes" else _RED))
        pdf.cell(5, _LINE, row.mark)
        pdf.set_font(_BODY, "", _TEXT_PT)
        pdf.set_text_color(*_INK)
        pdf.multi_cell(_WIDTH - 5 - 42, _LINE, row.criterion, align="L",
                       new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1.2)


# How each section is printed, by the key `render` names it by.
_SECTIONS: Final[dict[str, Callable[[_Sheet, RenderedPostmortem], None]]] = {
    "summary": _the_summary,
    "impact": _the_impact,
    "cause": _the_cause,
    "hypotheses": _the_hypotheses,
    "trigger": _the_trigger,
    "resolution": _the_resolution,
    "detection": _the_detection,
    "action-items": _the_action_items,
    "lessons": _the_lessons,
    "timeline": _the_timeline,
    "leads": _the_leads,
    "response-cost": _the_cost,
    "supporting": _the_supporting_information,
    "review": _the_review
}
