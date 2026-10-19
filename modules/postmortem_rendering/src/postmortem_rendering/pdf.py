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
from contextlib import contextmanager
from itertools import accumulate, pairwise
from pathlib import Path
from typing import Final, NamedTuple

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
# The smallest a row of figures is set at to keep each on one line.
_SMALLEST_FIGURE_PT: Final = 8.0
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
        self.addresses = rendered.supporting.revision_addresses
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

        with self._from_the_side():
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
        # Under the header at the body's own margin, so a block the page broke
        # inside goes on at its indent.
        self.set_y(_BELOW_THE_HEADER)

    def footer(self) -> None:
        with self._from_the_side():
            self.set_y(-15)
            self._rule(self.get_y(), _RULE, 0.26)
            self.set_y(-13.5)
            self.set_font(_BODY, "", 7.1)
            self.set_text_color(*_MUTED)
            self.cell(_WIDTH / 2, 4, self._written)
            self.cell(_WIDTH / 2, 4, f"Page {self.page_no()} of {{nb}}", align="R")

    @contextmanager
    def _from_the_side(self) -> Iterator[None]:
        """Sets what is written inside it from the page's side margin. A page
        breaks wherever the body is, and the footer closing it and the header
        opening the next are written then - with the body's margin in force,
        which inside an indented block is the indent."""
        left = self.l_margin
        self.set_left_margin(_SIDE)
        try:
            yield
        finally:
            self.set_left_margin(left)

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
    row it names, and every revision it names as a link to where it opens."""
    for run in runs:
        yield from (run.with_references(pdf.labels, pdf.addresses) if run.role is Role.PROSE
                    else (run,))


def _link(pdf: _Sheet, run: Run) -> str | int:
    """Where a run leads: a citation to its row, a link to its address, and
    anything else nowhere."""
    if run.role is Role.CITATION and run.address:
        return pdf.citation(run.address)
    return run.address or ""


def _runs(pdf: _Sheet, runs: Sequence[Run], size: float, height: float) -> None:
    """Runs written inline, wrapping at the margins in force, each set in what
    its role looks like."""
    _written(pdf, height, [(run, _the_look_of(run, size)) for run in _cited(pdf, runs)])
    pdf.set_text_color(*_INK)


class _Look(NamedTuple):
    """How a run is set inline: its face, style, size and colour, and its
    words as they are written."""

    family: str
    style: str
    size: float
    colour: tuple[int, int, int]
    text: str


def _the_look_of(run: Run, size: float) -> _Look:
    """A run of body text as its role looks at `size` points."""
    match run.role:
        case Role.CODE:
            return _Look(_MONO, "", size * 0.9, _INK, run.text)
        case Role.STRONG | Role.TO_STATE | Role.STATUS:
            return _Look(_BODY, "B", size, _INK, run.text)
        case Role.FROM_STATE:
            return _Look(_BODY, "S", size, _MUTED, run.text)
        case Role.QUOTE:
            return _Look(_BODY, "", size, _INK, f"“{run.text}”")
        case Role.LINK | Role.CITATION:
            return _Look(_BODY, "", size, _LINK, run.text)
        case Role.PLAIN | Role.PROSE | Role.NARRATION | Role.MOMENT:
            return _Look(_BODY, "", size, _INK, run.text)


def _written(pdf: _Sheet, height: float, runs: Sequence[tuple[Run, _Look]]) -> None:
    """Runs written inline, wrapping at the margins in force, each in its own
    look - and a word that does not fit what is left of a line starting the
    next one, whole.

    fpdf2 wraps a run at the spaces in it, and a word it cannot break before -
    the first of a run, or one going on into the next run - it cuts wherever
    the line runs out: "(A" on one line and "I-2)" on the next. So each such
    word is measured where it begins, across every run it goes on into and
    each in its own face, as `_where_the_lines_lie` measures a word: a soft
    hyphen takes no room and a non-breaking space joins rather than parts. A
    word wider than a whole line is left to fpdf2 to cut."""
    said = "".join(look.text for _, look in runs)
    begins = list(accumulate((len(look.text) for _, look in runs), initial=0))

    for place, (run, look) in enumerate(runs):
        start, end = begins[place], begins[place + 1]
        # Where a word fpdf2 cannot break before begins in this run: at its
        # start, and after its last break where the word goes on past it.
        last = max(said.rfind(each, start, end) for each in _BREAKS) + 1
        checks = [at for at in {start, last}
                  if start <= at < end and _a_word_begins_at(said, at)
                  and (at == start or _the_end_of_the_word(said, at) > end)]

        written = start
        for at in [*sorted(checks), end]:
            if at > written:
                _set_as(pdf, look)
                pdf.write(height, said[written:at], link=_link(pdf, run))
            if at < end:
                _room_for(pdf, height,
                          _how_wide(pdf, runs, begins, at, _the_end_of_the_word(said, at)))
            written = at


def _a_word_begins_at(said: str, at: int) -> bool:
    return said[at] not in _BREAKS and (at == 0 or said[at - 1] in _BREAKS)


def _the_end_of_the_word(said: str, at: int) -> int:
    """Where the word beginning at `at` ends: at the next break, or the end."""
    ends = [found for each in _BREAKS if (found := said.find(each, at)) != -1]
    return min(ends, default=len(said))


def _how_wide(pdf: _Sheet, runs: Sequence[tuple[Run, _Look]], begins: Sequence[int],
              start: int, end: int) -> float:
    """How wide the words from `start` to `end` are set, each piece in the
    look of the run it is in, a soft hyphen taking no room."""
    wide = 0.0
    for place, (_, look) in enumerate(runs):
        piece = look.text[max(start, begins[place]) - begins[place]:
                          min(end, begins[place + 1]) - begins[place]]
        if piece:
            _set_as(pdf, look)
            wide += pdf.get_string_width(piece.replace(_SOFT_HYPHEN, ""))
    return wide


def _room_for(pdf: _Sheet, height: float, wide: float) -> None:
    """A new line where a word `wide` does not fit what is left of this one
    and would fit a whole one."""
    left, right = pdf.l_margin, pdf.w - pdf.r_margin
    if pdf.get_x() > left + _LEEWAY and wide > right - pdf.get_x() and wide <= right - left:
        pdf.ln(height)


# How far into a line the writing has to be before a word is moved off it:
# less, and it is at the line's start already, where moving it gains nothing.
_LEEWAY: Final = 0.01


def _set_as(pdf: _Sheet, look: _Look) -> None:
    pdf.set_font(look.family, look.style, look.size)
    pdf.set_text_color(*look.colour)


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
             indent: float = 4.2, mark: str = _BULLET) -> None:
    """A bulleted item: a muted bullet - or `mark`, where the item goes by a
    label - at the body's size in its own column, then the runs with a
    hanging indent."""
    left = pdf.l_margin
    pdf.set_x(left)
    pdf.set_font(_BODY, "", _TEXT_PT)
    pdf.set_text_color(*_MUTED)
    pdf.cell(indent, _LINE, mark)
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
        pdf.set_text_color(*(_LINK if run.role in (Role.CITATION, Role.LINK) else colour))
        pdf.write(height, run.text, link=_link(pdf, run))
    pdf.ln(height + after)
    pdf.set_left_margin(left)
    pdf.set_text_color(*_INK)


def _tiles(pdf: _Sheet, cards: Sequence[Card]) -> None:
    """The figures across in bordered tiles, each above what it is, and under
    that, quieter, its note - every tile as tall as the tallest, each part
    wrapping inside it."""
    gap, pad_x, pad_y = 2.1, 2.4, 1.9
    width = (_WIDTH - gap * (len(cards) - 1)) / len(cards)
    inside = width - 2 * pad_x
    # Each part's face, size, leading and colour, in the order a card says them.
    looks = ((_MONO, _figures_size(pdf, cards, inside), 5.6, _INK), (_BODY, 7.1, 3.4, _MUTED),
             (_BODY, 6.4, 3.1, _MUTED))
    said = [(card.value, card.label, card.note or "") for card in cards]

    depths = []
    for part, (face, size, leading, _) in enumerate(looks):
        pdf.set_font(face, "", size)
        depths.append(max(_lines_needed(pdf, inside, parts[part], leading) for parts in said)
                      * leading)
    height = 2 * pad_y + sum(depths)
    if pdf.will_page_break(height + 2):
        pdf.add_page()

    top = pdf.get_y()
    pdf.set_draw_color(*_RULE)
    pdf.set_line_width(0.26)
    for place, parts in enumerate(said):
        x = _SIDE + place * (width + gap)
        pdf.rect(x, top, width, height)
        y = top + pad_y
        for text, (face, size, leading, colour), depth in zip(parts, looks, depths, strict=True):
            if text:
                pdf.set_xy(x + pad_x, y)
                pdf.set_font(face, "", size)
                pdf.set_text_color(*colour)
                pdf.multi_cell(inside, leading, text, align="L")
            y += depth
    pdf.set_text_color(*_INK)
    pdf.set_xy(_SIDE, top + height + 2)


def _figures_size(pdf: _Sheet, cards: Sequence[Card], width: float) -> float:
    """The largest size, down to a floor, at which every card's figure fits
    `width` on one line - one size for the row, so the figures read as a set,
    and each whole, since "0.899 to" over "0.459" reads as two figures. Past
    the floor a figure wraps rather than shrinking out of reading."""
    # The width a cell sets text in, inside the margin fpdf keeps at each side.
    room = width - 2 * pdf.c_margin
    size = _FIGURE_PT
    while size > _SMALLEST_FIGURE_PT:
        pdf.set_font(_MONO, "", size)
        if all(pdf.get_string_width(card.value) <= room for card in cards):
            break
        size -= 0.25
    return max(size, _SMALLEST_FIGURE_PT)


def _lines_needed(pdf: _Sheet, width: float, text: str, leading: float) -> int:
    """How many lines `text` wraps to at `width` in the font in force - none
    for no text."""
    if not text:
        return 0
    lines = pdf.multi_cell(width, leading, text, dry_run=True, output="LINES")
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

    A row that goes on from the one above it (`going_on`) - the rest of a row
    no page holds - has no rule between it and that one.
    """

    def __init__(self, pdf: _Sheet, lines: dict[tuple[int, int], tuple[Line, float]],
                 going_on: frozenset[int] = frozenset()) -> None:
        self._pdf = pdf
        self._lines = lines
        self._going_on = going_on
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
        body_row = row_idx - num_heading_rows
        return TableCellStyle(
            left=False,
            right=False,
            top=row_idx > 0 and row_idx != num_heading_rows and body_row not in self._going_on,
            bottom=(TableBorderStyle(thickness=0.26, color=_INK) if under_the_headings
                    else row_idx < num_rows - 1 and body_row + 1 not in self._going_on))


def _a_table(pdf: _Sheet, headings: Sequence[str] | None, rows: Sequence[Sequence[_Cell]],
             widths: Sequence[float], align: Sequence[str] | None = None,
             landings: Sequence[tuple[str, ...]] = ()) -> None:
    """A table ruled across between its rows, its headings small and
    capitalised over an ink rule and repeated on every page it runs onto - or
    a table with no headings where `headings` is `None`. `widths` are in
    millimetres; `align` sets each column, left where it is not given;
    `landings` are the labels each row goes by, none for a row without one.

    A cell given as a line is left empty, as tall as the line needs, and the
    line written into it as its row is drawn.

    The fill colour is put back to the default first, because the table fills
    every cell in any other: it takes the colour in force as its own, and the
    fill comes after the line written into the cell, painting it out.

    A table draws no row across two pages, and refuses one taller than a page,
    so a row that tall is set as rows that go on from one another
    (`_as_the_pages_hold_them`), its labels landing on the first."""
    pdf.set_font(_BODY, "", _TABLE_PT)
    pdf.set_text_color(*_INK)
    pdf.set_draw_color(*_RULE)
    pdf.set_fill_color(pdf.DEFAULT_FILL_COLOR)
    pdf.set_line_width(0.26)
    aligned = list(align) if align else ["L"] * len(widths)
    pieces = _as_the_pages_hold_them(pdf, rows, widths, headings is not None)
    starts = list(accumulate((len(each) for each in pieces[:-1]), initial=0))
    rows = [piece for each in pieces for piece in each]
    layout = _RuledAcross(pdf, {(place, column): (cell, widths[column])
                                for place, cells in enumerate(rows)
                                for column, cell in enumerate(cells)
                                if isinstance(cell, Line)},
                          going_on=frozenset(start + later
                                             for start, each in zip(starts, pieces, strict=True)
                                             for later in range(1, len(each))))
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
                (_A_ROW + _CELL_LINE * _how_many_lines(pdf, cell, width)
                 for cell, width in zip(cells, widths, strict=True) if isinstance(cell, Line)),
                default=None))
            for cell, side in zip(cells, aligned, strict=True):
                if isinstance(cell, Line):
                    row.cell("", align=side)
                else:
                    text, style, address = cell
                    row.cell(text, style=style, link=address, align=side)

    for place, labels in enumerate(landings):
        for label in labels:
            pdf.lands_at(label, *layout.tops[starts[place]])
    pdf.ln(1.5)


def _as_the_pages_hold_them(pdf: _Sheet, rows: Sequence[Sequence[_Cell]],
                            widths: Sequence[float],
                            under_headings: bool) -> list[list[list[_Cell]]]:
    """Each row as the rows the pages hold it in: itself, where it fits on the
    page it begins on or on a fresh one, and otherwise cut - its first piece
    as many lines as the room left where it begins, so whatever is set above
    it is not left alone at the foot of a page, and each piece after it as
    many as a fresh page holds below the running header and the headings the
    table repeats there.

    Where each row begins is followed down the pages as the table will set
    them, a row going to a fresh page where it does not fit the room left. A
    first piece with room for too few lines is not begun there: the row
    starts on the next page instead."""
    headings = _A_ROW + _CELL_LINE if under_headings else 0.0
    bottom = pdf.h - pdf.b_margin
    fresh = _BELOW_THE_HEADER + headings
    most = _lines_in(bottom - fresh)
    at = pdf.y + headings
    placed = []

    for cells in rows:
        tall = _A_ROW + _CELL_LINE * max((_how_many_lines(pdf, cell, width)
                                          for cell, width in zip(cells, widths, strict=True)),
                                         default=1)
        if at + tall <= bottom:
            at += tall
            placed.append([list(cells)])
            continue
        if tall <= bottom - fresh:
            at = fresh + tall
            placed.append([list(cells)])
            continue

        room = _lines_in(bottom - at)
        first = room if room >= _FEWEST_LINES_BEGUN else most
        cut = [_cut(pdf, cell, width, first, most)
               for cell, width in zip(cells, widths, strict=True)]
        pieces = [[parts[place] if place < len(parts) else _NOTHING for parts in cut]
                  for place in range(max(len(parts) for parts in cut))]
        last = max(_how_many_lines(pdf, cell, width)
                   for cell, width in zip(pieces[-1], widths, strict=True))
        at = fresh + _A_ROW + _CELL_LINE * last
        placed.append(pieces)

    return placed


# A row's own height besides its lines: the cell's padding above and below.
_A_ROW: Final = _CELL_PADDING.top + _CELL_PADDING.bottom

# The fewest lines a row taller than a page begins with at the foot of one.
_FEWEST_LINES_BEGUN: Final = 3

# What a cell holds below its last piece, in a row that goes on from its own.
_NOTHING: Final[_Cell] = ("", None, None)


def _lines_in(room: float) -> int:
    """How many lines of a cell fit in `room` millimetres, with one to spare."""
    return max(1, int((room - _A_ROW - _CELL_LINE) // _CELL_LINE))


def _how_many_lines(pdf: _Sheet, cell: _Cell, width: float) -> int:
    """How many lines a cell `width` wide holds its text in: a line as it is
    written into its cell (`_where_the_lines_lie`), any other as the table sets
    it, in the face it is set in."""
    if isinstance(cell, Line):
        return len(_where_the_lines_lie(pdf, cell.said, width))

    text, style, _ = cell
    _set_in(pdf, style)
    lines = len(_cell_lines(pdf, text, width))
    pdf.set_font(_BODY, "", _TABLE_PT)
    return lines


def _cut(pdf: _Sheet, cell: _Cell, width: float, first: int, most: int) -> list[_Cell]:
    """A cell `width` wide as pieces: the first of at most `first` lines, each
    after of at most `most` - or itself, where it fits in the first. A run cut
    in two is two runs going where the one went.

    A line is cut between the lines it is written in. Any other cell the table
    sets itself, so each piece of it is the longest the table is measured to
    set in its lines, ending where a line may break - and the pieces put back
    together are the cell less the one space or line break between each two,
    whatever the table's lines make of the characters in them."""
    if isinstance(cell, Line):
        spans = _where_the_lines_lie(pdf, cell.said, width)
        if len(spans) <= first:
            return [cell]

        bounds = [0, *range(first, len(spans), most), len(spans)]
        return [_a_piece_of(cell, spans[start][0], spans[end - 1][1])
                for start, end in pairwise(bounds)]

    text = cell[0]
    pieces: list[_Cell] = []
    begins, fits = 0, first

    while _how_many_lines(pdf, rest := _a_piece_of(cell, begins, len(text)), width) > fits:
        ends = _the_most_that_fits(text, begins, len(text),
                                   _fitting(pdf, cell, width, begins, fits))
        pieces.append(_a_piece_of(cell, begins, ends))
        begins = ends + 1 if text[ends:ends + 1] in _BREAKS else ends
        fits = most

    return [*pieces, rest]


def _fitting(pdf: _Sheet, cell: _Cell, width: float, begins: int,
             fits: int) -> Callable[[int], bool]:
    """Whether the piece of a cell from `begins` to a place in it is set in
    `fits` lines or fewer."""
    return lambda ends: _how_many_lines(pdf, _a_piece_of(cell, begins, ends), width) <= fits


def _where_the_lines_lie(pdf: _Sheet, text: str, width: float) -> list[tuple[int, int]]:
    """Where in `text` each line a cell `width` wide writes it in, in body
    text, begins and ends: a line break ends one, and otherwise each is the
    longest measured to fit across the cell, ending before a space where one
    leaves it fitting.

    Measured rather than looked for: the lines fpdf2 hands back are not the
    text's own characters - a non-breaking space comes back a plain one, a
    soft hyphen dropped or a hyphen - and a line looked for by its characters
    is a line not found. Measured as wide as it is written, each piece its
    characters' widths added up. A line's height, where it is cut and what is
    written on each of its lines all come from here, so the three agree."""
    pdf.set_font(_BODY, "", _TABLE_PT)
    # The room across the cell as the table leaves it: less its padding, and
    # the cell margin on the left, the side with none.
    room = width - _CELL_PADDING.left - _CELL_PADDING.right - pdf.c_margin
    # How far across each place in the text is from its start: each character
    # measured once, so a piece is measured without being read again. A soft
    # hyphen takes no room, being left out where the line is written.
    wide = {character: 0.0 if character == _SOFT_HYPHEN else pdf.get_string_width(character)
            for character in set(text)}
    across = list(accumulate((wide[character] for character in text), initial=0.0))

    def fitting(begins: int) -> Callable[[int], bool]:
        return lambda ends: across[ends] - across[begins] <= room

    spans: list[tuple[int, int]] = []
    paragraph = 0
    for said in text.split("\n"):
        begins, ends_by = paragraph, paragraph + len(said)
        while not fitting(begins)(ends_by):
            ends = _the_most_that_fits(text, begins, ends_by, fitting(begins))
            spans.append((begins, ends))
            begins = ends + 1 if text[ends:ends + 1] == " " else ends
        spans.append((begins, ends_by))
        paragraph = ends_by + 1

    return spans


def _the_most_that_fits(text: str, begins: int, ends_by: int,
                        fitting: Callable[[int], bool]) -> int:
    """Where the longest piece of `text` from `begins`, and ending by
    `ends_by`, that is `fitting` ends: before the last space or line break
    that leaves it fitting, or - where a word alone is wider than the cell -
    wherever the measure says.

    The longest is found by doubling a reach until it no longer fits and then
    halving between the two, so a cell many pages long is measured in pieces
    near the size of one rather than whole at every step."""
    shortest, reach = begins + 1, _A_FIRST_REACH
    while begins + reach < ends_by and fitting(begins + reach):
        shortest, reach = begins + reach, reach * 2

    longest = min(begins + reach, ends_by)
    while shortest < longest:
        middle = (shortest + longest + 1) // 2
        if fitting(middle):
            shortest = middle
        else:
            longest = middle - 1

    if text[shortest:shortest + 1] in _BREAKS:
        return shortest

    space = max(text.rfind(each, begins, shortest) for each in _BREAKS)
    return space if space > begins else shortest


# How far a piece is first reached for, in characters, before the reach doubles.
_A_FIRST_REACH: Final = 256

# Where a cell is cut between pieces: a space or a line break, and never a
# non-breaking space, which is there to say its two sides stay together.
_BREAKS: Final = (" ", "\n")

# Where a word may be broken, and otherwise nothing. The font draws it as a
# hyphen, so a line written character by character leaves it out.
_SOFT_HYPHEN: Final = "\u00ad"


def _set_in(pdf: _Sheet, style: FontFace | None) -> None:
    """The face a plain cell is set in: its own style's, over the table's body."""
    if style is None:
        pdf.set_font(_BODY, "", _TABLE_PT)
        return

    pdf.set_font(style.family or _BODY,
                 style.emphasis.style if style.emphasis else "",
                 style.size_pt or _TABLE_PT)


def _a_piece_of(cell: _Cell, begins: int, ends: int) -> _Cell:
    """The part of a cell between two places in its text - a line's runs each
    kept with its role and address, and only where it has any of that part."""
    if not isinstance(cell, Line):
        text, style, address = cell
        return text[begins:ends], style, address

    runs = []
    at = 0
    for run in cell.runs:
        piece = run.text[max(begins - at, 0):max(ends - at, 0)]
        if piece:
            runs.append(run.model_copy(update={"text": piece}))
        at += len(run.text)

    return Line(runs=tuple(runs))


def _cell_lines(pdf: _Sheet, text: str, width: float) -> list[str]:
    """`text` broken into the lines a table cell `width` wide breaks it into,
    in the font in force."""
    lines = pdf.multi_cell(width, _CELL_LINE, text, max_line_height=_CELL_LINE,
                           padding=_CELL_PADDING, dry_run=True, output="LINES")
    assert isinstance(lines, list)
    return lines


def _a_line_in_a_cell(pdf: _Sheet, line: Line, width: float) -> None:
    """A line written in body text into the cell the table left for it, from
    the cell's top left corner where the page is now: broken where the table
    would have broken it, and set run by run, so a citation in it is a link.
    The page is left where it was found."""
    x, top = pdf.x, pdf.y
    pdf.set_font(_BODY, "", _TABLE_PT)
    text = line.said
    spans = _where_the_lines_lie(pdf, text, width)
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
    for place, (begins, ends) in enumerate(spans):
        pdf.set_xy(left, top + _CELL_PADDING.top + place * _CELL_LINE)
        for at, run in runs:
            piece = text[max(at, begins):min(at + len(run.text), ends)].replace(_SOFT_HYPHEN, "")
            if not piece:
                continue
            # Code in the body face, as the line was measured in, and set apart
            # by its colour alone.
            pdf.set_text_color(*(_LINK if run.role in (Role.CITATION, Role.LINK)
                                 else _MUTED if run.role is Role.CODE else _INK))
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
                         evidence: Sequence[Line]) -> None:
    """One step: its place in a quiet column of its own, the claim beside it,
    and what it rests on under the claim, each item on a line of its own as
    the page sets them - each item's label leading to its row, and whatever
    its row links, linked."""
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
        pdf.write(3.8, evidence_label)
        for cited in evidence:
            pdf.ln(3.8)
            _written(pdf, 3.8, [(run, _Look(_BODY, "", _SMALL_PT,
                                            _LINK if run.role in (Role.CITATION, Role.LINK)
                                            else _MUTED, run.text))
                                for run in _cited(pdf, cited.runs)])
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
        _written(pdf, _LINE, [(run, _Look(_MONO, "", _SMALL_PT,
                                          _LINK if run.role is Role.CITATION else _MUTED,
                                          run.text))
                              for run in _cited(pdf, addressed_by.runs)])
    pdf.ln(_LINE + 1.0)
    pdf.set_left_margin(left)
    pdf.set_text_color(*_INK)


def _the_hypotheses(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    """Each candidate under the label the prose cites it by, then what it
    said - written run by run, so a revision it names opens its commit - how
    confident the ranking was and what became of it."""
    hypotheses = rendered.hypotheses
    if hypotheses.absent:
        _quiet(pdf, hypotheses.absent)
        return

    _a_table(pdf, hypotheses.headings,
             [[(", ".join(row.labels), _NUMBER, None), row.summary,
               (row.confidence, _TIME, None), (row.result, None, None)]
              for row in hypotheses.rows],
             widths=(18, 86, 26, 44), landings=[row.labels for row in hypotheses.rows])


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
            # The action as its line says it, so only what the line links is a
            # link - the fix's name, not the words saying what was done.
            rows.append([(step.at, _TIME, None),
                         step.action,
                         (step.by, None, None), (step.kind, None, None),
                         (step.outcome_in_the_table, None, None)])
        _a_table(pdf, taken.headings, rows, widths=(18, 54, 24, 37, 41),
                 landings=[(step.label,) if step.label else () for step in steps])
    elif taken.absent:
        _quiet(pdf, taken.absent)


def _the_detection(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    detection = rendered.detection
    if detection.line is not None:
        _a_paragraph(pdf, detection.line)
    elif detection.absent:
        _quiet(pdf, detection.absent)

    # What the alert said, a row as the supporting rows are, for a citation of
    # it to land on.
    if detection.said is not None:
        _a_subheading(pdf, detection.said_heading)
        _a_table(pdf, None, [[(detection.said.label, _NUMBER, None), detection.said.said]],
                 widths=(16, 158), landings=[(detection.said.label,)])


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
                 landings=[(row.number,) for row in items.rows])

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
    """Each line in a row: when, its marker, and who said what - written run by
    run, so a candidate the line names leads to its row."""
    timeline = rendered.timeline
    if timeline.absent:
        _quiet(pdf, timeline.absent)
        return

    _a_table(pdf, None,
             [[(row.at, _TIME, None), (row.marker or "", _MARKER, None),
               Line(runs=(*((Run(text=f"{row.who} "),) if row.who else ()), *row.text.runs))]
              for row in timeline.rows],
             widths=(31, 29, 114), align=("R", "L", "L"),
             landings=[(row.label,) if row.label else () for row in timeline.rows])


def _the_leads(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    """Each lead as an item under the label the prose cites it by, what the
    investigation made of it and what it changed close under it.

    Kept off the foot of a page before its landing is set, so a citation never
    lands on the page before the lead it names."""
    indent = 7.0
    for lead in rendered.leads:
        if pdf.will_page_break(2 * _LINE):
            pdf.add_page()
        pdf.lands_at(lead.label, pdf.page, pdf.get_y())
        _an_item(pdf, lead.said.runs, after=0.6, indent=indent, mark=lead.label)
        _beneath(pdf, lead.weighing.runs, indent=indent, colour=_INK)
        if lead.effect is not None:
            _beneath(pdf, lead.effect.runs, indent=indent, colour=_MUTED)
        pdf.ln(3.0)


def _the_cost(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    _tiles(pdf, rendered.cost)


def _the_supporting_information(pdf: _Sheet, rendered: RenderedPostmortem) -> None:
    """A reference list, as the agreed layout sets it: what each source is in a quiet
    column, and the source beside it - an address in a face a reader can
    copy from paper. Each line's words up to its first colon are its label,
    and the assumptions are the list's last entry.

    Between the two, the changes and the log messages read, what each
    deployment looked into changed and what Code-Fix read in the source, each
    a table of rows under the labels the prose cites them by - the last two
    only where there is any."""
    supporting = rendered.supporting
    for line in supporting.links:
        opening, *rest = line.runs
        label, _, remainder = opening.text.partition(": ")
        value = [Run(text=remainder), *rest] if remainder else rest
        _a_reference(pdf, label, [value])

    for heading, rows, absent in (
        (supporting.changes_heading, supporting.changes, supporting.changes_absent),
        (supporting.log_messages_heading, supporting.log_messages, supporting.log_messages_absent),
        (supporting.deployment_changes_heading, supporting.deployment_changes, None),
        (supporting.code_read_heading, supporting.code_read, None)
    ):
        if not rows and absent is None:
            continue
        _a_subheading(pdf, heading)
        if absent:
            _quiet(pdf, absent)
        else:
            _a_table(pdf, None,
                     [[(row.label, _NUMBER, None), row.said] for row in rows],
                     widths=(16, 158), landings=[(row.label,) for row in rows])
    pdf.ln(2.0)

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
    status rather than as part of the criterion. What a person would do to
    meet it is a sentence, set quiet under the criterion in the criterion's
    own column, where it wraps rather than running into the status."""
    review = rendered.review
    if review.absent:
        _quiet(pdf, review.absent)
    width = _WIDTH - 5 - 42
    for row in review.rows:
        y = pdf.get_y()
        pdf.set_font(_BODY, "", _LABEL_PT)
        pdf.set_text_color(*_MUTED)
        pdf.set_xy(_SIDE + _WIDTH - 40, y)
        pdf.cell(40, _LINE, row.meaning, align="R")
        pdf.set_xy(_SIDE, y)
        pdf.set_font(_FALLBACK, "B", _TEXT_PT)
        pdf.set_text_color(*{"yes": _GREEN, "left": _MUTED}.get(row.met, _RED))
        pdf.cell(5, _LINE, row.mark)
        pdf.set_font(_BODY, "", _TEXT_PT)
        pdf.set_text_color(*_INK)
        pdf.multi_cell(width, _LINE, row.criterion, align="L", new_x="LEFT", new_y="NEXT")
        if row.because:
            pdf.set_font(_BODY, "", _LABEL_PT)
            pdf.set_text_color(*_MUTED)
            pdf.multi_cell(width, 4.0, row.because, align="L", new_x="LEFT", new_y="NEXT")
            pdf.set_text_color(*_INK)
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
