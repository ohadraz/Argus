## Why

The people working an incident talk about it in its Slack thread, and when one
of them has ended it, that is where they say so. Argus already accepts a
resolution from its own UI and from PagerDuty, but it only writes to Slack -
nothing reads the thread. This change, the first of three for Slack inbound,
lets a person resolve the incident by saying so in its thread.

The other two parts are separate changes: answering questions in the thread
from the incident's own record, and taking new information from the thread as
a lead for a running walk.

## What Changes

- **Argus ingests its Slack threads.** Slack's Events API delivers each message
  posted in a channel Argus is in to a signed endpoint on `argus_web`, which
  verifies it, records it on the incident whose thread it was written in, and
  acknowledges inside Slack's three seconds. Messages outside an incident's
  thread, and Argus's own, are ignored.
- **A port for the chat platform, in both directions.** `ChatPlatformReads` and
  `ChatPlatformWrites`, named for the role, with Slack as their one adapter,
  named for the vendor: it verifies and reads deliveries, looks up a person's
  name, and posts and rewrites what Argus says. The Communicator's own Slack
  module goes. Above the port nothing knows Slack's envelopes, headers, field
  names or blocks.
- **A new agent reads what a person meant.** `agent_intent`, the
  Communicator's counterpart, follows the event log as the relay does, and puts
  each message a person wrote through one structured model call: `resolve`,
  `question`, `information`, `withdraw` or `other`. Only `resolve` acts in this
  change; the rest are recorded for the changes after it.
- **Argus asks before it acts.** On `resolve`, Argus replies in the thread with a
  button that only the person who wrote the message can press. Pressing it
  resolves the incident as the UI and PagerDuty do, credited to that person by
  their Slack name (or their Slack id, where it cannot be read), through Slack, with their own message as the note. There is
  no timeout: a press on an incident that has already ended does nothing, and
  when the incident ends, by any channel, the button is replaced by who ended
  it.
- **The incident's Slack thread becomes one of its references.**
  **BREAKING (schema)**: the `slack_thread` table is folded into
  `incident_reference`, so a thread message finds its incident through the same
  lookup PagerDuty uses, keeping the one-thread-per-channel guard.
- **`slack_double`** gains `users.info`, `chat.update`, and posted `blocks`.
  It is off-limits to Claude, so the change is proposed whole in chat.
- **Spec §16** says a person may report the incident over in its Slack thread,
  and that the report is the fact, as for every other channel.

## Capabilities

### New Capabilities

- `slack-thread-resolution`: a person resolves an incident by writing in its
  Slack thread and confirming. Covers which messages are ingested, signature
  verification, classification, the confirmation button and who may press it,
  and the account the resolution leaves.
- `chat-platform-port`: the chat platform behind a port, with Slack as its
  adapter - parsing deliveries, naming a person, and posting.

### Modified Capabilities

- `incident-references`: an incident's chat thread is one of its references,
  one per channel.
- `slack-communication`: the war room is found through the incident's
  references; the thread carries the confirmation button, and the button is
  retired once the incident can no longer be resolved.
- `slack-test-double`: `users.info` with a person staged by the test,
  `chat.update`, and posted `blocks` kept.

## Impact

- `argus_core`:
  - `ReportChannel.SLACK`;
  - events for a person writing in the thread, for the classification, and for
    the offer to resolve;
  - settings: `slack_signing_secret`, `intent_model`, `intent_effort`,
    `intent_poll_seconds`.
- `argus_core` migrations: revision `001` loses `slack_thread` and gains a
  unique index on `incident_reference` for one thread per incident per channel.
- `argus_incidents`: `references` gains the thread kind and the lookups it
  needs.
- New module `chat_platform`: the `ChatPlatformReads` and `ChatPlatformWrites`
  ports and the `Slack` adapter, which takes over posting from
  `agent_communicator/slack.py`.
- New module `agent_intent`: the classifier and its process,
  `python -m agent_intent.watching`.
- `agent_communicator`: the thread comes from `incident_reference`
  (`repository/threads.py` goes); it posts through `ChatPlatformWrites`
  (`slack.py` goes); the offer is posted with a button; the button
  is retired when the incident no longer accepts a resolution (`resolved`,
  `withdrawn`, `disproven`).
- `argus_web`: `POST /webhooks/slack/events` and
  `POST /webhooks/slack/interactions`.
- `argus_narration`: lines for the new events, and "from Slack".
- `pyproject.toml`: `root_packages` and the layering contracts gain both new
  modules; `argus_core.llm` opens to `agent_intent`.
- `noxfile.py`: the intent agent process, and a second `anthropic_double` instance
  serving only the intent agent, so its answers never interleave with a walk's.
- The Slack app (manual, the user's): scopes `channels:history` and
  `users:read`, the `message.channels` event, and the interactivity URL -
  through the same tunnel PagerDuty's webhook needs.
- e2e: one new case (the user writes it), resolved from Slack after the flag is
  off. The walks' recordings are unchanged; the classifier needs one recording
  of its own - a single small paid call.
- `docs/spec-and-architecture.md`: §7 (the Intent Agent), §12 (the chat port), §16.
