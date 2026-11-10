## Why

An incident's postmortem is written for the engineers who own the system, and
deliberately shows no pay: its readers are the people it would price. Leadership
needs something else - what happened, for how long, what it cost the business
and the people who answered it, and how it was fixed - in a few lines they can
read in a minute. The responder cost is already measured "for the executive
report" and shown nowhere; nothing yet says it to the people it is for.

Called the **executive synopsis** throughout, because the postmortem already has
a field called `executive_summary` - a code-written paragraph for engineers and
the chat - and a "report" is already a person telling Argus how an incident
ended. One word for two things is a defect.

## What Changes

- **A new walk step, after the postmortem step**, writes the executive synopsis.
  The postmortem step, its document, its row, its prompt and its output are not
  changed, and none of its recordings is re-recorded. The synopsis reads the
  stored postmortem; what the postmortem does not store, the synopsis reads
  itself.
- **The synopsis holds**, in order: an overview in plain, human prose; when the
  incident began and ended and how long it lasted, in UTC; impact tiles; the
  resolution as a short list; the human cost; and a link to the full postmortem.
- **The overview is written by the model in the step's own call.** It names
  figures (`{duration}`) rather than writing them, and code writes each in, in
  the words the postmortem page uses. The answer is refused for a figure written
  out or a required figure left unnamed (only where the record holds it). The
  prompt forbids claiming anything about the resolution beyond the resolution
  list, and judging checks it.
- **The resolution is written by code**, in the words the postmortem's own
  Resolution section uses.
- **The human cost is shown per title**: for each title, how many responders
  held it, their minutes, and their cost at the band's midpoint with its range,
  with a total row and the basis the cost was computed on. No figure adds the
  customer loss to the responder cost.
- **The synopsis is posted in Slack, and nowhere else**: one message to each
  Slack id configured - a member's as a direct message, a private channel's in
  that channel - carrying the synopsis and the postmortem's link, and no file.
  `argus_web` never serves it. Argus has no authentication, and the synopsis
  shows pay.
- **The synopsis is written on every ending that writes a postmortem**, whatever
  is configured; with no Slack id configured, nothing is posted.
- **If the overview cannot be written, nothing is posted**, and the timeline
  says so.
- **The Slack ids are configured in `.env`** as one list, documented in
  `.env.example`. Slack needs no new permission: the app's `chat:write` posts a
  direct message to a member's id and to a private channel it has been invited
  to.

## Capabilities

### New Capabilities

- `executive-synopsis`: what the synopsis says, who writes each part, the checks
  the overview must pass, and that the postmortem is not changed by it.
- `executive-synopsis-slack`: who receives the synopsis in Slack, in what form,
  and when it is posted and when it is not.

### Modified Capabilities

None. The postmortem and the responder cost are read, not changed.

## Impact

- `agent_postmortem`: the synopsis step (new files only), reusing the
  postmortem's engagement and band reads as they are.
- `orchestrator`: the step on the graph, after the postmortem.
- `argus_core`: the synopsis model and its table (revision `001` edited in
  place); the written and withheld events; the setting for the Slack ids.
- `postmortem_rendering`: the synopsis's lines and their Markdown, reusing the
  postmortem's impact cards and formatting.
- `agent_communicator`: the chat relay posts the synopsis to the configured
  Slack ids.
- `noxfile.py`: `e2e`, `e2e_replay` and `record` configure Slack ids on the
  Slack double.
- `.env.example` and the local `.env`.
- `docs/spec-and-architecture.md`: §7.5, §7.6, §21.3 and `INTEGRATION_CONFIG`.
- `agent_postmortem.checking`: the figure rules become one public function,
  with no change in what the postmortem's checks do - the postmortem suites and
  the replays are the proof.
- **Recordings**: no existing recording changes. Each of the 33 `both`-mode
  walks gains one exchange, recorded synopsis-only, with the walk and the
  postmortem replayed. Priced for free with `count_tokens` and asked before any
  spend.
