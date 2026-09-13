## Context

`agent_communicator` is two functions - `post_update` and `raise_page` - each
formatting a line and handing it to an injected `emit`, whose default writes to
stdout. The graph already calls them through injected seams (`PostUpdate`,
`RaisePage` in `graph.py`), so the call sites need no rearranging to reach a
real destination.

What is missing is everything around a single line of text: an incident has no
place of its own in Slack, no message that opens it, none that closes it, and
the postmortem it produces is written to the database and delivered nowhere.

Argus already has one external party stood in for by a double: the Anthropic
API, with `modules/anthropic_double` serving `POST /v1/messages` plus a
`/double-control/*` seam, dev-only, excluded from test discovery, and checked
against the real API by `tests/contract/`. Slack is the second such party, and
gets the same treatment rather than a new one.

## Goals / Non-Goals

**Goals:**
- An incident is visible in Slack to somebody who was not already watching.
- The messages that need to interrupt do, and the ones that do not, do not.
- The suites stay free and keyless: dev, `e2e_replay` and every push-triggered
  CI job run against the double.
- The postmortem reaches a human as a document, not a database row.

**Non-Goals:**
- Reading from Slack. A human replying in the thread, and Argus taking that as
  input, is the other direction and its own change.
- Email, or any second channel of delivery.
- Creating channels. The war room and postmortem channels exist and are named
  in configuration.
- Secret management beyond an environment variable, which is what every other
  credential here already is.

## Decisions

**One channel, a thread per incident.** The opening message is the incident's
war room; updates are replies to it; the closing message goes back to the
channel. A channel per incident was rejected: it needs channel-create scope,
leaves a workspace full of dead channels after a demo, and buries the one view
that shows several incidents at once. Flat posting into one channel was
rejected because two concurrent incidents interleave into nonsense.

**Notification follows from where a message goes, not from a flag.** A channel
message reaches the channel; a thread reply reaches the people following that
thread. So the open and the close notify, and the updates do not, without any
"quiet" parameter to decide - the behaviour is Slack's, and there is nothing to
get wrong.

**Slack is a projection of the event log, fed by a relay - not calls inside the
walk.** `agents -> events -> [outbox] -> relay -> policy -> renderer ->
channels`. Every step of a walk is already published as an event on the caller's
own connection inside a savepoint, which is a transactional outbox; a polling
relay holding a durable cursor over `incident_event.seq` is the publisher over
it. Delivery is at-least-once: a duplicate message is a nuisance, a silent miss
is the failure this exists to prevent. The alternative - a `post_update` call
beside every decision, threading a thread id through the walk - makes every
agent know about Slack and still reports only the steps somebody remembered to
call from.

**One account, rendered once.** The event-to-sentence renderer moves out of
`argus_web` into `argus_narration`, so the page, Slack, email and the postmortem
say the same thing in the same words. It already depends on nothing but
`argus_core` and pydantic, and its output is already channel-neutral; what stays
behind in the web is decoration - a CSS class, a page anchor.

**Which events reach a human is a policy in the delivery context**, not a
property of the event and not a judgement made where it was published. Onset,
candidates, actions, verdicts and transitions are heard; retrievals are not.

**The thread is identified by the parent message's timestamp, held in the
integration's own store** - `slack_thread(incident_id, channel, ts)`. Slack has
no thread id; a reply names the parent's `ts`. That value has to survive the
process that wrote it, so it is a row rather than anything held in memory - and
a row in the integration's own table rather than a column on `incident`, so that
the incident record never learns Slack exists and a second destination adds a
mapping rather than a column.

**An incident with no war room still gets its updates.** If the opening
message failed - Slack down, channel renamed - the incident has no `ts` to
reply to. The update goes to the channel instead of being dropped: a message in
the wrong shape is worth more than silence about an incident being worked.

**Slack failures never fail an incident.** A refused or unreachable Slack call
is recorded on the timeline and the walk continues. Communication is how an
incident is reported, not how it is resolved, and an incident that escalates
because Slack rate-limited it would be a worse outcome than one nobody saw.

**The Communicator delivers the postmortem; the Postmortem agent writes it.**
The document is produced as it is today and handed over. Delivery in the agent
that produced it would put two destinations - and eventually email - inside a
module whose subject is what a postmortem says.

**The double is a real HTTP server, pointed at by base URL.** Same shape as
`anthropic_double`: the Slack SDK is constructed against a base URL, which in
dev and CI is the double and in the demo is Slack. No branch in the adapter, no
"if testing" anywhere in production code.

**The contract test is what makes the double honest, and it runs nightly.** Not
in `paid-suites.yml`, where the Anthropic contract lives: that one is manual
because every run spends money, and Slack spends none. What it shares with no
free check is a dependency on somebody else's uptime, so it stays off the push
path - a merge blocked by a Slack outage is blocked for nothing about the code -
and a day is soon enough to learn the double has drifted.

This means `nox -s contract` splits: the free check has to be selectable without
the paid one, or the timer would spend money nightly and the manual run would
carry a check that did not need it.

## Risks / Trade-offs

- **A double that drifts from Slack** → the contract test, which is the whole
  reason the double is allowed to exist.
- **The token in a demo workspace is a real credential** → it is a bot token in
  a workspace holding nothing but this project's messages, kept in `.env` and
  in a repository secret, never in a push-triggered job.
- **A thread the incident lost** (message deleted, channel archived) → replies
  fall back to the channel rather than raising.
- **Rate limits during a fast walk** → updates are already sparse, one per
  refuted candidate; a 429 is recorded and the walk goes on.
- **The relay is one more long-running process**, on a stack whose processes are
  not dockerized yet → a cost, paid knowingly: the alternative is Slack seeing
  only the steps somebody remembered to call it from.
- **At-least-once means a message can be posted twice** → accepted. The cursor
  advances after the post, so a crash between the two repeats a line rather than
  losing it.
- **`PYTHONIOENCODING` goes away with the `print()`** → the encoding trap it
  worked around belongs to stdout, and nothing after this change writes model
  text there.
