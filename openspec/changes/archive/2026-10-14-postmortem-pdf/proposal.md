## Why

The postmortem is the artefact a person takes away from an incident, and today
it exists only as a web page on the Argus dashboard. A manager should be able to
keep it, forward it and attach it - which a page behind a local dashboard
cannot be. The page also works out much of what the document says inside its
Jinja template (the title, who ended the incident, Draft or Final, the
trigger's wording), so a second rendering written beside it would say the same
things in a second place and drift.

## What Changes

- **A new module, `postmortem_rendering`**, holds the postmortem as a reader
  reads it: every section's wording, as values, worked out once from the
  stored row, the incident's alert, and a person's resolution. It also turns
  those values into a PDF (fpdf2), with its typefaces bundled. It
  sits outside `agent_postmortem` because `argus_web` may not install an agent,
  and the Communicator, which will one day post the file to Slack, may not
  import another agent.
- **The page reads the same values.** `postmortem.html` keeps its markup and
  loses its wording: the title, the header rows, the trigger sentence, the
  ended-by line and the rest come from the module. Money, spans and revisions
  are written by the module's formatting, which moves out of `argus_web`.
- **`GET /incidents/{id}/postmortem.pdf`** serves the document as a download,
  named for the incident; 404 where there is no such incident or no
  postmortem yet.
- **The postmortem page gets a download button** linking to it, shown only
  where there is a document to download.
- The PDF says what the page says, section for section, in the same order and
  the same words; times are in UTC only, since a file has no reader's clock;
  every address is written in full.

## Capabilities

### New Capabilities

- `postmortem-pdf`: the postmortem as a downloadable PDF - what it carries,
  that it agrees with the page, and how it is served.

### Modified Capabilities

None. `postmortem-template` already says what the document holds and in what
order; this change gives it a second form and does not change its content.

## Impact

- New module `modules/postmortem_rendering/` (depends on `argus_core`,
  `argus_narration`, `fpdf2`), joined to `[tool.importlinter] root_packages`
  and to the layer `argus_web` may depend on.
- New third-party dependency: `fpdf2` (LGPL-3.0; brings `fonttools` and
  `defusedxml`; `Pillow` is already in the lock). Bundled typefaces with their
  licences: Source Serif 4, Public Sans and JetBrains Mono (OFL) and DejaVu
  Sans (its own free licence).
- `argus_web`: `formatting.py` and the resolution view move to the module;
  `postmortem.html` rewritten to read the module's values; a new route.
- `docs/spec-and-architecture.md` §7.6.
- No re-recording: nothing the model is asked or answers changes.
- Out of scope, a later change: posting the PDF to the incident's Slack thread.
