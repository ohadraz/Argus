## Context

The postmortem is stored as one row (`argus_core.models.Postmortem`) and shown
by `argus_web` through `postmortem.html`. The template does more than lay the
row out: it composes the title from the symptom and the trigger, words the
trigger as a flag going from one state to another or a service running a
revision, chooses Draft or Final, writes who ended the incident, and so on.
`argus_web/formatting.py` writes money, spans and revisions. The person's
resolution comes from the incident's events (`build_resolution_view`).

Two layering contracts decide where shared wording can live: `argus_web` may
not install an agent, and no agent may import another - so neither the page
nor the Communicator (which will post the file to Slack later) can reach into
`agent_postmortem`.

## Goals / Non-Goals

**Goals:** one place that says what a postmortem says; a PDF and the page both
reading it; a download route and button.

**Non-Goals:** posting the PDF to Slack; storing the PDF; changing what the
document holds or what the model is asked; right-to-left or CJK shaping.

## Decisions

### D1. A new module, `postmortem_rendering`

It holds the postmortem as a reader reads it - values, worked out from the row
- and the PDF made from them. Not `agent_postmortem` (the contracts above).
Not `argus_web` (the Communicator could not reach it). Not `argus_narration`:
narration says one recorded event in words, and a whole document's layout is a
different job with a different dependency (fpdf2) that every narration
consumer would then install. Depends on `argus_core` and `argus_narration`
(`where_a_report_came_from`) only. It reads no
database: a forbidden contract keeps `argus_incidents` and `psycopg` out.

### D2. Typed sections made of runs, not a generic block tree

`render(...)` returns a `RenderedPostmortem`: one typed value per section
(`Head`, `ImpactSection`, `TriggerSection`, `ActionsTakenSection`, ...), each
holding its lines. A line is a sequence of runs, each a piece of text and its
role (`Role`) - plain, the model's prose, a citation cut out of it, Argus's
narration, code, strong, state-from, state-to, status, link, quote, moment. The
words, including the
joining ones ("went from", "ran", "later"), are all in the runs; the roles
are what each renderer turns into markup or a font.

- A generic tree (`Paragraph`, `Table`, `List`) was rejected: the template
  would become one loop that lost the per-section markup, classes and
  `data-*` attributes the page's styles and its e2e assertions read.
- Plain strings per line were rejected: the page shows a subject in code and a
  state struck through, and a renderer would have to split the sentence again
  to do so - a second place deciding where its words begin and end.

The template keeps its structure and its attributes, and writes each line
through one macro that turns runs into spans. A label the prose cites leads to
the row it names, on the page and in the file alike: `RenderedPostmortem.labels`
says which labels have a row, and `Run.with_citations` cuts each one out of the
prose as a citation. The page makes it an anchor link; the PDF makes it a link
inside the file, landed where the table draws the row, and keeps the label
column in the hypotheses table so the row shows the name it was cited by.

### D3. Inputs are values

`render(postmortem, alert, events, incident_address)`: the row, the
incident's alert, its recorded events (from which the person's
resolution is taken, so the PDF carries one that arrived after the document),
and the incident page's absolute address, from which every link is written in
full. `argus_web` reads these as it does today and hands them over.

### D4. Formatting moves with the wording

`as_money`, `as_span`, `as_revision` and the UTC clock move from
`argus_web/formatting.py` to the module, so every amount is written one way
on the page and in the file. The page keeps only the UTC clock as a filter,
for the times its other pages show; every figure the postmortem shows arrives
already written in the values.

### D5. fpdf2, over the alternatives

- **WeasyPrint** renders the page's own HTML, but needs Pango and its native
  stack - a native install on every platform, and a Smart App Control risk on
  this one.
- **Headless Chromium** renders it exactly, at the price of a browser in
  `argus_web`'s image and a process per download.
- **Browser print** (`window.print()` with a print stylesheet) costs nothing,
  but leaves no file on the server, and the Slack posting needs bytes.
- **reportlab** would do; fpdf2 is smaller, its `table()` repeats headings
  across page breaks, and it was the choice already named in the
  `postmortem-template` change.

fpdf2 2.8.x is pure Python over `fonttools`, `defusedxml` and `Pillow` (already
in the lock). LGPL-3.0, used unmodified as a library.

### D6. The agreed layout, and the faces it is set in

The PDF follows the layout agreed as a mock (artifact `3Jp9XdPuqg9YTBmajDTHnA`):
Argus's mark, 32 mm, framed in the cloak's teal in the first page's top-right
corner; a teal rule under the masthead and under the running header that
names Argus, the title and the incident ID on every later page; a footer with
the writing time and the page count; a teal square before each section
heading; figures in bordered tiles; tables ruled across, never boxed, their
headings small and capitalised. The mark is the web page's own, cropped square
and sized for print (`assets/argus.jpg`), so every download does not carry
the full photograph.

fpdf2's core fonts are Latin-1 only, and the model writes em dashes. The
mock's faces ship as package data with their OFL licences: Source Serif 4 for
the title and headings, Public Sans for the body, JetBrains Mono for anything
copied. Public Sans has no Cyrillic and no ticks, so DejaVu Sans stands behind
all three as fpdf2's fallback. A character none of them carries (CJK, for one)
is left out of the line, and fpdf2 logs a warning naming it; the download does
not fail.

### D7. Made on request, not stored

The PDF is produced per download from the current row and events. A stored
file would go stale the moment a person resolved the incident, and producing
it is milliseconds.

### D8. The route and the button

`GET /incidents/{id}/postmortem.pdf`: `application/pdf`,
`Content-Disposition: attachment; filename="argus-postmortem-<id>.pdf"`. 404 for no
incident, and for no postmortem - unlike the page, which answers absence with
a sentence, a download of nothing has nothing to send. The file is made from
the stored postmortem each time it is asked for and never stored itself, so it
says what the page would say now. The button sits in the document head, only
where there is a document.

### D9. Tests read the PDF's text

The module's tests extract the text with `pypdf` (a dev dependency) and assert
words and their order. The route's test asserts the headers and that the body
is a PDF. No e2e case is added: the route opens no new path through the
system, and the page's cases already carry a real walk's postmortem through
`render`.

## Risks / Trade-offs

- [Rewriting the template moves wording the page's e2e assertions read] → the
  template keeps every `data-*` attribute; the free `e2e_replay` runs before
  and after, and must agree.
- [Hebrew or Arabic names print in the wrong order without shaping] → out of
  scope; fpdf2's `set_text_shaping` with `uharfbuzz` is the later fix, and
  the download does not fail meanwhile.
- [A new LGPL dependency] → unmodified library use; recorded here.
- [Bundled fonts add about 2.5 MB to the repo] → accepted; they are the only
  way to print what the model writes in the agreed faces.
- [Section order differs from the mock's] → the mock put Detection, Trigger and
  Resolution before the cause; the page and the `postmortem-template` spec put
  the cause first, and the PDF says what the page says.
