Every behaviour task is TDD: propose the failing test in chat (the user applies
it), see it red for the right reason, then implement. Bottom-up: module,
renderer, page, route, e2e.

## 1. Module

- [x] 1.1 Scaffold `modules/postmortem_rendering/` (`new-module` skill); add to
      `root_packages`; forbidden contract: no `argus_incidents`, no `psycopg`,
      no agent (D1)
- [x] 1.2 Add `fpdf2` and the typefaces (Source Serif 4, Public Sans,
      JetBrains Mono, DejaVu Sans) with their licences as package data; confirm with fonttools that the review checklist's tick
      and cross are carried, and how fpdf2 2.8.x prints a glyph no font has
      (D6)
- [x] 1.3 Move `as_money`, `as_span`, `as_revision` and the UTC clock out of
      `argus_web/formatting.py`; `argus_web` re-registers them as filters (D4)

## 2. The wording, as values (D2, D3)

- [x] 2.1 Runs and lines: a piece of text and its role
- [x] 2.2 The head: title (symptom and confirmed trigger, or the alert), ID,
      incident line, date line, status (Draft/Final, items done), written by,
      ended by (a person's resolution, else the last step)
- [x] 2.3 Impact cards and the alert's finding; the unobserved note
- [x] 2.4 Root cause, causal chain with its evidence, contributing factors
- [x] 2.5 Hypotheses considered
- [x] 2.6 Trigger sentence: flag or deployment, suspected or confirmed, states,
      time, actor; none established
- [x] 2.7 Resolution: the person's resolution, the steps, the proposed fix
- [x] 2.8 Detection sentence
- [x] 2.9 Action items and the recommended action
- [x] 2.10 Lessons, timeline (date where the day changes, markers), leads
- [x] 2.11 Cost of the response, supporting information (links in full from
      the incident's address), assumptions, review checklist
- [x] 2.12 The person's resolution taken from the events (moves from
      `argus_web/views/postmortems.py`)

## 3. The PDF (D5-D7)

- [x] 3.1 `as_pdf(rendered) -> bytes`: every section in order, its words as the
      values hold them (text read back with `pypdf`)
- [x] 3.2 Times say UTC; addresses in full; money to the cent
- [x] 3.3 Em dash and Cyrillic printed; a glyph no font carries does not fail
- [x] 3.4 Tables repeat their headings across a page break
- [x] 3.5 The layout of the agreed mock (artifact 3Jp9XdPuqg9YTBmajDTHnA): logo
      masthead, teal rules and section markers, serif headings, figure tiles,
      ruled tables, running header and footer, reference list
- [x] 3.6 A label the prose cites leads to its row, as on the page: one rule
      for which words are labels (`Run.with_citations`) and which have rows
      (`RenderedPostmortem.labels`); the hypotheses table keeps its label column

## 4. The page

- [x] 4.1 `postmortem.html` reads the values: one macro writes a line's runs;
      every `data-*` attribute kept; `with_references` stays the page's
- [x] 4.2 Download button in the document head, only where there is a document

## 5. The route (D8)

- [x] 5.1 `GET /incidents/{id}/postmortem.pdf`: PDF, attachment named
      `argus-postmortem-<id>.pdf`; 404 for no incident and for no postmortem

## 6. End to end

- [x] 6.1 None: the route adds no new path through the system. The page's e2e
      cases already carry a real walk's postmortem through `render`, and
      `as_pdf` and the route are covered by their own suites

## 7. Close

- [x] 7.1 Spec §7.6: the postmortem's two forms, one wording
- [x] 7.2 Review agents over the diff: stale comments, test gaps
- [x] 7.3 Cleanup: comments, docstrings, jargon, logs and docs aligned; no test
      missing, redundant or weak; design and specs match what was built.
- [x] 7.4 Gates: module suites, typecheck, lint, layering
- [x] 7.5 `e2e_replay(mode='both')` agrees with the run before the change
- [ ] 7.6 Specs synced on archive
