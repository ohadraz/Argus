## Why

The Communicator is the one agent that still only pretends to do its job: both
its functions write a line to stdout behind an `emit` seam left for "a real
Slack/email adapter". Everything an incident produces - the fact that Argus
picked it up, what it tried, how it ended, the postmortem it wrote - reaches a
human only by reading a log or the dashboard. A responder who is not already
watching learns nothing, which is the opposite of what §7.5 asks the
Communicator for, and a demo has nothing to show but a terminal.

## What Changes

- The Communicator posts to a real Slack workspace: an opening message in a
  war-room channel when an incident is accepted, its updates as replies in that
  message's thread, and a closing message in the channel when the incident
  reaches a terminal status.
- The channel messages that open and close an incident notify the channel; the
  thread updates do not, because a reply already reaches the people following
  that thread and nobody else.
- The Communicator delivers the postmortem the Postmortem agent produced to a
  separate postmortem channel, and the closing message links to it. The
  Postmortem agent keeps writing the document and gains no delivery
  responsibility.
- A Slack double stands in for the Slack API in dev, `e2e_replay` and CI, the
  same arrangement `anthropic_double` already has: the suites exercise the real
  adapter with no token and no workspace.
- A contract test checks the double still answers as Slack does, run nightly
  against the real workspace - never on a push, since a check that stands on a
  third party takes the push down with it when that party is down.

## Capabilities

### New Capabilities
- `slack-communication`: where an incident's messages go, what notifies a human
  and what does not, and what happens when Slack refuses or is unreachable.
- `slack-test-double`: the record/replay stand-in for the Slack API, and the
  control seam the suites drive it through.

### Modified Capabilities
- `incident-postmortem`: the document the Postmortem agent produces is
  delivered by the Communicator rather than existing only in the database.

## Impact

- `modules/agent_communicator`: the stdout stub becomes a real adapter behind
  the same seam; a third entry point for delivering a postmortem.
- New `modules/slack_double`, dev-only, alongside `anthropic_double` and
  excluded from test discovery for the same reason.
- `modules/argus_core.config`: the bot token, the two channel names, and the
  base URL the double is pointed at.
- `modules/orchestrator`: the call that opens an incident's war room, and the
  one that closes it.
- `noxfile.py`: the double joins the local services; `PYTHONIOENCODING` goes
  away with the `print()` that needed it.
- `.github/workflows`: the nightly gains the Slack workspace's token and runs
  the free contract check; no push-triggered job gains one, and the paid
  workflow is left alone.
- `tests/contract/`: a second external party beside the Anthropic API.
