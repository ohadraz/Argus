---
name: judge-postmortem
description: Use when acting as the judge of a postmortem - a re-record, a held replay, or any incident Argus wrote one for - to rule whether it holds and list what needs fixing. Covers the eight questions, what to have captured before the stack goes down, the scripts that check links and run CLI draws, and where the verdict is written.
---

# judge-postmortem

## The prompt (the user's, binding)

You act as a judge.
You know the case. You have the code (what should happen), the recordings (what the
model answered), the database (what really happened) and the demo app (the ground truth).
Judge every place the postmortem is shown: page, PDF, walk, Slack.

1. Is it true - against the database and the demo app?
2. Is it wrong?
3. Is it missing important info?
4. Is it noisy (irrelevant or repeated info)?
5. Is it structured well?
6. Are the links true and working? (Structure only; the base URL is config, not judged.)
7. Is the reasoning correct?
8. Anything else you can judge, including regressions against the last verdict.

Start with the verdict: does it hold, and can it be committed?
List the issues that need fixing: first code fixes needing no re-record, then those
needing a model-input change and/or a new recording; within each, ordered by type
(wrong/missing/noisy/...).
Always look for the root cause(s), and have them handled first. Check every "wrong"
against the brief and the field descriptions before calling it a defect.
Every fix proposed to model input is measured before it is proposed: 5 CLI draws on the
current input, 5 on the fixed one.
List what was ruled not a defect, and why.

## Roles

The judge judges results and changes no code. The session that runs the stack edits,
records and commits. Design questions (wording, what a field asks) go to the user with a
recommendation - yes/no plus the exact wording - never to the other session.

## Before the stack goes down

Ask the running session to hold the stack after the replay and save into one folder:

- every table, one JSON file each (`postmortem`, `incident`, `incident_event`,
  `hypothesis`, `replay_log`, ...) and `write_up_request.json` (keys `tools`,
  `transcript`; `transcript[0].text` is the brief);
- `postmortem_page.html`, `walk_page.html`, `incident_page.html`, `postmortem.pdf`;
- `slack_posted.json` - the Slack double's `/double-control/posted`;
- `metrics_after.json` - the minute buckets from an hour before the onset to the incident's
  `ended_at`, read again through Argus's metrics source once the write-up is done, for
  `check_figures.py`.

Teardown destroys all of it; nothing is judged from memory. Captures are kept in
`.claude/local/captures/<case>/<short sha>/` (local, never committed), not in a session
scratchpad that can disappear.

## Regression on earlier cases

Not per case. Run it once, before the batch is checked in, and only if a fix since then
changed something every case shares: the brief or prompts, narration, the page or PDF
rendering, or Slack. The running session hold-replays each judged case on that HEAD and
captures it. Diff each one's page, PDF and Slack text against its last judged capture. A
change is a regression unless a fix explains it.

## Reading it

**One command judges a capture, and it is the only command the judge runs:**

    uv run python .claude/skills/judge-postmortem/scripts/judge_capture.py <capture> [<baseline>...]

from the repo root, paths as the only arguments, nothing else on the line - the user allowlisted
exactly that prefix, and every other command prompts them. `<capture>` is a captured test's own
folder; each `<baseline>` is the same test's folder in an earlier capture, last judged first. It
runs every step below and more (the model calls as text and masked against each baseline, the
diverged map, each diverged recording against what was asked, every answer's tool calls, the
record's clock, Slack whole, the PDF against the page, leaks, the change step of every recorded
write-up, cost) into `<capture>/judge/`, sums them up in `<capture>/judge-report.md`, and hashes the
recording set once as judged - a rerun after the recording commit is the commit check. Read the
results with Read and Grep, which need no permission; never sed, grep or python in a shell. Anything
the script doesn't do yet goes into it as a step before it is needed.

The scripts it runs are in `scripts/`; each also runs alone with `.venv/Scripts/python.exe -X utf8`
from the repo (`-I` drops PYTHONIOENCODING; `-X utf8` does not), but that prompts the user.

- `check_pages.py <capture dir> <out dir> [base url]` - each page as text, and every link:
  anchors to ids the page holds, ids unique and never "None", local routes 200 from the
  held stack (default `http://localhost:8000`).
- `check_pdf.py <capture dir> <out dir>` - the PDF as text, internal destinations resolved.
- `check_figures.py <capture dir>` - run on every capture: the times and the broken-stretch
  figures worked out again from the minutes and the stored events (onset, end and each marker
  against its minute; while broken, worst, failed, rule series), FLAG on any difference.
- `recording_exchange.py <out dir> <recording.json>...` - a recording and its
  `.request.json` as text: the brief, each answer, each refusal, thinking. The answer
  shows which figures were placeholders (`{T20.1 - alert_raised}`) - code-computed, so
  true by construction at replay time.

Then check, at least:

- one clock: `incident.created_at` is T1, `ended_at` the last status move, durations and
  gaps from the rows;
- every claim about the service against the demo app's generator, not only the rows;
- the Slack posts against the walk, line for line - a destination nobody reads is where
  defects hide;
- other agents' words (C rows, F rows) are theirs and marked: a claim there is a defect only
  if it was false when that agent made it.

## Measuring a fix to model input

1. `write_up_inputs.py <write_up_request.json> <input dir>` - `brief.txt`, `tool.json` and
   `system.txt` (HEAD's `STANDING_BRIEF`). A replay of a stale recording mixes revisions:
   edit `brief.txt` by hand so it says what a fresh run would, and say what you changed.
2. Copy the input dir, apply the fix to the copy.
3. `draws.py <input dir> <out dir> [n]` on each - 5 by default, in parallel, through the
   `claude` CLI on the subscription (never API credits, never subagents); about a minute.
   Not free: every draw spends the user's weekly subscription limit. None run without the
   user's explicit yes, asked as "N draws against your weekly limit", never as free.
   The CLI is not on PATH on Windows here: set `CLAUDE_CLI` to the VS Code extension's
   `resources/native-binary/claude.exe` (its version is in the folder name, so look it up).
4. Count the defect in each set by reading every draw, and report both counts.

A confound in the input (a stale line from an old recording) gets its own set with it cut
before any conclusion.

## Writing the verdict

The ledger is one file per case, `docs/postmortem-review/<case>.md`, indexed by
`docs/postmortem-review.md` (a row per case: status, last judged sha, open items) - none
of it staged or committed. A new case gets its own file and its row in the index. Each run gets
a heading in its case's file (`### Re-record N (date, answers, on <sha>)`), then: what was
captured and where, the eight answers, what holds, findings as `- [ ] **<case>-<A|B><n>**`
with A for model input/recording and B for code only, then what was ruled not a defect.
Tick a finding with its fixing sha when the fix is judged - at every place it is listed, the
run that first raised it included; an unticked first mention reads as still open.

Then message the running session: the verdict first, each finding with its fix, nothing
the ledger already says at length.
