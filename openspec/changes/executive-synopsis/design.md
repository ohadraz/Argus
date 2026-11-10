## Context

The postmortem is written once, at the incident's end, in the walk
(`orchestrator.gathering.write_postmortem_for` calling `agent_postmortem`): code
measures, one model call writes the prose, and the walk stores the document and
publishes `PostmortemWritten`. The Communicator's chat relay reads the event log
on a cursor of its own. The postmortem's words for a reader - page and PDF - are
worked out once in `postmortem_rendering`.

The responder cost's totals (midpoint, minimum, maximum, currency) and its basis
are on the `postmortem` row and shown nowhere. Per-responder minutes are not
stored: the postmortem step holds them in memory and keeps only the total.

Constraints this design keeps:
- **The postmortem is not changed**: not its document, row, prompt or output,
  and nothing that would re-record it. Its code changes in one place only, by
  the user's ruling: the core of its four figure rules moves to
  `figure_rules.py`, public and over plain sentences, and `checking.py`'s
  rules call it under their own names with the same words.
- The walk may not send anything (the fence); people are told through the log.
- `argus_web` installs no agent, and serves nothing of the synopsis.
- A model never supplies a figure.

## Goals / Non-Goals

**Goals:**
- An overview that reads like a person wrote it, with every figure from code.
- Pay shown only to the configured Slack members and channels.
- Only the synopsis's own exchange is recorded and judged.

**Non-Goals:**
- Email, a PDF of the synopsis, or a synopsis page in `argus_web`.
- Resending when a person reports a resolution later.
- Checking that the configured members are not themselves responders, or that a
  configured channel is private. The privacy holds only while both are true;
  `.env.example` says so.
- Pricing tokens.

## Decisions

### A walk step after the postmortem
`write_executive_synopsis` (new, in `agent_postmortem`) runs as a graph step of
its own after the postmortem step, on every ending that wrote one, so a
synopsis that fails cannot have the postmortem written again. The orchestrator
reads the stored `postmortem` row and the incident's alert, words the figures
and the resolution through `postmortem_rendering`, and hands them over; the
step reads what the row does not hold, asks the model for the overview, and the
walk stores an `executive_synopsis` row and publishes `ExecutiveSynopsisWritten`
or `ExecutiveSynopsisWithheld`. Neither event carries a figure.

The overview is asked under a policy of its own (`synopsis_policy`): the
postmortem's model and effort, and no brief - the postmortem's brief asks for a
tool this call does not offer.

Rejected: an overview field on `submit_postmortem`, or a second call inside
`write_postmortem`. Both change the postmortem's code; the first changes its
request too.

### Per-title cost: read again, checked against the postmortem
The step reads each responder's minutes and their titles' bands through the
same `Sources` reads the postmortem uses, and prices them with the existing
`responder_cost` arithmetic, grouped by title (new code beside it; the existing
function is not changed). The rows' people, minutes, midpoint, minimum and
maximum must sum to the stored postmortem's - amounts compared to the cent,
since grouping adds the same Decimals in another order - and their currency
must be the stored one; otherwise the synopsis shows the postmortem's totals, no
rows, and says the breakdown could not be matched. The postmortem's totals are
what the synopsis shows as totals in every case, the overview's
`{responder_cost}` included. Nobody paged, or an on-call source the postmortem
could not read, has nothing to break down and says which.

Where the on-call page also covered other incidents, the synopsis carries the
postmortem's own line saying so, taken whole from its assumptions.

Rejected: handing the postmortem step's measurements to the synopsis step. It
matches by construction but changes the postmortem's code.

### Figures in the postmortem page's words
The impact tiles are `postmortem_rendering`'s own impact cards, over the stored
document. The overview names figures (`{duration}`, `{customer_loss}`,
`{responder_cost}`, `{engineer_minutes}`, `{responders}`), and code writes each
in as prose says its tile's figure - "7 minutes 12 seconds" for "7m 12s", "at
least" kept, and the responders' minutes with what they count. Words the
overview already says beside a figure's name - its "at least" before, its "so
far" after - are written once, in the overview's spelling. The ask keeps the
tiles' wording. The written-out-figure check is the postmortem's own
four rules, run by the same code (`figure_rules`). The required-names check is
new and asks only for figures the record holds.

Pay goes to the model by name, never by value: the request reaches the model's
provider and its `.request.json` is committed. Sizing words are forbidden
anyway, so the model needs only where `{responder_cost}` goes.

### Sizing words and resolution claims are the judge's
"A brief outage" or "the fix resolved it" pass every check. The prompt forbids
both and gives the model the resolution list; judging each recorded overview
checks both.

### Resolution by code
Built from the stored document's Resolution steps, in the words
`postmortem_rendering` shows them in, then the pull request left for review and
the recommended action not taken.

### Rounding
The total shown is the stored total to the cent, everywhere. Each row is
rounded to the cent and the cents left over by plain rounding go to the rows
with the largest remainders, so the rows shown always add up to the total
shown.

### Written whatever is configured
The step writes the synopsis on every ending that writes a postmortem, whatever
is configured: one flow, and one exchange in every recorded walk. With no Slack
id configured, the chat relay posts nothing. The cost is one model call per
incident that nobody may receive.

### Slack: the chat relay, a register of its own
`ExecutiveSynopsisWritten` is said in a new register, `BRIEFED`: said only to the
people the synopsis is for, never in the war room, a thread or the postmortem
channel. The chat relay reads the stored synopsis and postmortem, and posts once
to each configured Slack id - a member's opens a direct message, a channel's
posts in the channel; `chat.postMessage` takes either, so one list holds both.
No new Slack permission: `chat:write` covers both, the channel once the app is
invited to it - Slack's `chat.postMessage` reference, read 2026-11-09. The
message is one `Line`: the overview as its text, the synopsis's other parts as
its aside in Markdown (`as_markdown`), and the postmortem's address as its link.
No file. A withheld synopsis posts nothing; the timeline says why. A post Slack
refuses is recorded as any line that did not land, and the others still go.

Rejected: a Slack relay of its own. The chat relay already reads the log, posts
through `ChatPlatformWrites` and records what did not land.

### Where things live
- `agent_postmortem`: the step, its prompt, policy, tool, checks and per-title
  grouping, in new files.
- `argus_core.models`: `ExecutiveSynopsis` and its per-title row; `argus_core.events`:
  the two events.
- `argus_incidents`: the `executive_synopsis` repository.
- `orchestrator`: the step on the graph, and the gathering that words its
  figures and resolution.
- `postmortem_rendering`: the synopsis as lines, and `as_markdown` over them.
- `agent_communicator`: the `BRIEFED` register and its posts.

### Configuration
`.env`: `EXECUTIVE_SYNOPSIS_SLACK_TO` (comma-separated Slack ids, members and
private channels alike: `chat.postMessage` takes either as its channel). The
local `.env` holds the user's member id. `INTEGRATION_CONFIG.exec_summary_recipients`
in the spec gives way to the setting.

### The Slack double for every suite that brings up the stack
`e2e`, `e2e_replay(mode='both')` and `record` configure two Slack ids - a
member's and a channel's - on the Slack double, which takes any channel, so the
e2e case sees both posts and that nothing of the synopsis reached the war room.

### Recording synopsis-only, with a proof the postmortem did not move
`record_incident.py` gains `--synopsis-only`: it replays each walk and its
postmortem from their recordings and records only the synopsis's exchange. It
refuses to record a case whose postmortem requests diverge from their
recordings, which is the check that this change left the postmortem's input
alone; every `both` case carries a `.request.json` for each of its postmortem
exchanges to compare against. 33 cases, `both` mode only. Priced for free with
`count_tokens` on the synopsis's request before anything is recorded.

## Risks / Trade-offs

- [Sizing words pass the checks] → Forbidden in the prompt, checked in judging.
- [The re-read differs from the postmortem's] → Checked against the stored
  totals; on mismatch, totals only, and said.
- [Recording cost unknown] → Priced with `count_tokens`, asked before any spend.
- [Pay reaches a responder among the members] → Said in `.env.example`; not
  checked.
- [The Slack channel is public] → Said in `.env.example`; not checked.
- [A model call per incident nobody receives] → Accepted for one flow.
- [A duplicate post after a crash] → At-least-once, as the chat relay is.

## Migration Plan

Revision `001` is edited in place for the new table, and the schema is
reapplied (`nox -s schema`). CI replays fail once the walk makes the new call
until every case has its exchange recorded, so the recordings land in the same
push as the code.

## Open Questions

None.
