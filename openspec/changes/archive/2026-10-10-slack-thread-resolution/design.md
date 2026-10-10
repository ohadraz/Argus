## Context

A person can report an incident resolved through two channels today: the Argus
UI and PagerDuty. Both end in
`resolve_incident(id, Report(by, channel, note), connections, publisher)`, a
guarded UPDATE that publishes `StatusChanged(reported=...)` only when the row
moved. The walk learns of it through `ended_by_a_person_via`. Spec §16 says
such a report is the fact, never tested.

What Argus has for Slack:

- **Outbound only.** The relay (`python -m agent_communicator.watching`)
  follows `incident_event` through `event_cursor` (reader `slack`), decides each
  event's register (`policy.how_it_is_said`), and posts with `slack_sdk`
  (`slack.post_message`, text only). The first post opens the thread, and its
  `ts` is kept in `slack_thread`, keyed `(incident_id, channel)`.
- **No inbound.** Nothing receives an event or an interaction from Slack.
- **Inbound precedents in `argus_web`:** `/webhooks/github/push` and
  `/webhooks/oncall` both verify a signature over the raw body, answer `401` on
  a mismatch and `202` otherwise. The on-call one sits behind a port
  (`OnCallPlatform`) whose adapter only `argus_web.app` builds.
- **Async work** moves through tables polled by long-lived processes: runs via
  `incident_run`, and the relay via `event_cursor`. There is no LISTEN/NOTIFY.
- **The Anthropic double is one FIFO queue** that never reads the request, and
  only the worker is pointed at it. A model call in any other process would
  reach the real API, and a second caller sharing the worker's queue would take
  the walk's answers.

Slack facts (docs.slack.dev, checked 2026-10-10):

1. Events and interactions are both signed: `X-Slack-Signature: v0=<hex
   HMAC-SHA256(secret, "v0:{X-Slack-Request-Timestamp}:{raw body}")>`. Slack
   recommends rejecting timestamps more than five minutes from local time.
2. Both must be answered with a 2xx within three seconds. Events are retried up
   to three times (`X-Slack-Retry-Num`).
3. Setting the Events URL sends `{"type": "url_verification", "challenge"}`,
   which is answered with the challenge.
4. `message.channels` needs `channels:history`, and is delivered for public
   channels the app is in. `users.info` needs `users:read` and returns
   `user.real_name` and `user.profile.display_name`.
5. A button press arrives as `application/x-www-form-urlencoded` with a JSON
   `payload` of type `block_actions`, carrying `user.id`, `channel.id`,
   `message.ts`, `message.thread_ts`, and `actions[].action_id` and `.value`.
   A posted message can be changed with `chat.update`.

## Goals / Non-Goals

**Goals:**
- A person who writes in an incident's Slack thread that it is over, and then
  confirms, resolves the incident: credited by their Slack name, through Slack,
  with their own words as the note.
- Every message a person writes in the thread is recorded on the incident and
  classified, so the next two changes only have to act on a meaning, not
  ingest it.
- The chat platform sits behind a port, as the on-call platform does.
- One fact, one owner: an incident's thread is one of its references.
- Without a signing secret configured, nothing is ingested and nothing changes.

**Non-Goals:**
- Answering questions, or taking new information to a running walk. Those are
  parts 2 and 3. Their meanings are recorded here and acted on there.
- Moving the Communicator's posting behind the new port. It keeps its own
  `slack.py`. The port carries what inbound needs and nothing more.
- Private channels (`groups:history`), direct messages, edits and deletions.
  Only a new reply in a public incident thread is ingested.
- Exposing Argus publicly. The tunnel PagerDuty's webhook needs serves Slack
  as well.

## Decisions

### D1. Two endpoints on `argus_web`, behind a `ChatPlatformReads` port

`POST /webhooks/slack/events` and `POST /webhooks/slack/interactions`. Both
are `async`, read the raw body, and pass it with the headers to
`ChatPlatformReads.parse_delivery(body, headers) -> Delivery`. The port is a
`Protocol` in a new module, `chat_platform`, and `Slack` is its one adapter.
`Delivery` is a closed union in Argus's words:

- `Handshake(challenge)`: answered with the challenge.
- `Written(thread: Reference, message: Reference, person_id, text)`.
- `Pressed(thread: Reference, person_id, message: Reference)`, where `message`
  is the message the offer was made about.
- `Irrelevant(why)`: a top-level message, a bot's (`bot_id`), any `subtype`
  (edits, joins, deletions), or an action that isn't Argus's.

A signature mismatch, a stale timestamp, or an empty secret raises
`ChatDeliveryUnverified`, answered `401`. With no Slack configured at all, both
routes answer `404`, as `/webhooks/oncall` does. Otherwise the answer is `200`,
which Slack requires for interactions; events take any 2xx.

The port also carries `person_named(person_id) -> str | None` (`users.info`:
`real_name`, then `profile.display_name`, else `None`), and its `channel`,
`ReportChannel.SLACK`.

*Alternatives:*
- Code in `argus_web` that knows Slack directly. That breaks the
  ports-and-adapters rule the on-call platform set, and `agent_intent` needs
  `person_named` too.
- Socket Mode. One process would hold a WebSocket open, and Slack keeps Socket
  Mode apps out of its Marketplace. Settled with the user.

### D2. The thread is an `incident_reference`; `slack_thread` goes

- The Communicator records `Reference("slack", "chat-thread", "<channel>/<ts>")`
  when it opens the war room, and finds the thread through the incident's
  references. `repository/threads.py` and its table are removed from revision
  `001`.
- A delivery's `thread` is the same reference built from `channel` and
  `thread_ts`, so `get_incident_by_values("chat-thread", [...])` finds the
  incident, the lookup PagerDuty already uses.
- **The one-thread guard stays.** A unique index,
  `(incident_id, source, kind, split_part(value, '/', 1)) WHERE kind = 'chat-thread'`,
  keeps one thread per incident per channel. `ON CONFLICT DO NOTHING` then
  leaves the first thread standing, as `slack_thread`'s primary key did.
- A person's message is recorded as
  `Reference("slack", "chat-message", "<channel>/<ts>")` in the same
  transaction as its event. A retried delivery finds the reference already held
  and publishes nothing. `references.claim(...) -> bool` is `add` that says
  whether it wrote.

*Alternative:* keep `slack_thread` and add a reverse index. That leaves two
tables recording what another tool calls an incident, and keeps it in an
agent's repository where `argus_web` cannot read it.

### D3. Ingest fast, understand later: the intent agent follows the event log

`argus_web` does no model call and no Slack read inside the three seconds. For
`Written` it finds the incident by thread, claims the message reference, and
records `PersonWrote` (an `argus_core.events` event carrying the person's id,
the text and the message reference), all in one transaction. Recorded rather
than published: an event that could fail to be written after the claim would
be a message claimed and never understood. An unknown thread is logged and
answered `200`.

The new agent, `agent_intent`, runs as its own process
(`python -m agent_intent.watching`) and follows `incident_event` through
`event_cursor` under the reader name `intent`, as the relay does. For each
`PersonWrote` it:

1. makes one model call with a submit tool (the postmortem's pattern): the
   message and what the incident is, answered with one meaning from
   `resolve`, `question`, `information`, `withdraw` and `other`;
2. publishes `MessageUnderstood(message, meaning)`;
3. on `resolve`, if the incident still accepts a resolution, names the person
   (`person_named`) and publishes
   `ResolutionOffered(message, person_id, person_name, said)`.

A failed model call is retried once, then recorded as `other` with a warning,
because a message that is never classified would block the cursor.

*Why a new agent, not the Communicator:* the Communicator says what happened,
and this reads what a person meant. They are separate responsibilities with
separate failure modes. `agent_intent` joins the agent-independence contract,
and it never posts. What it decides reaches Slack as an event, through the
relay, like everything else Argus says.

*Why a process of its own, not the worker:* the worker runs walks from
`incident_run`. A message is not a run, and classifying one must not wait
behind a walk or lease an incident.

### D4. The offer: a button only its addressee can press

- `policy.how_it_is_said`: `ResolutionOffered` is `FOLLOWED`. `PersonWrote` and
  `MessageUnderstood` stay `UNSAID`, because repeating a person's own words
  back into their thread is noise. Both are on the page.
- The relay posts the offer as a thread reply with blocks: the sentence ("Mark
  this incident resolved, as <name> said?") and one button, `action_id`
  `resolve-incident`, `value` the ts of the person's message. It records
  `Reference("slack", "chat-offer", "<channel>/<ts>")`, so the button can be
  found later.
- On `Pressed`, `argus_web` finds the incident by thread and reads its
  `ResolutionOffered` for that message reference:
  - **Pressed by someone else:** logged at info. Nothing changes.
  - **No such offer:** logged at warning. Nothing changes.
  - **Otherwise:** `resolve_incident(id, Report(by=person_name, channel=SLACK,
    note=said))`. An incident that has already ended does not move, and
    nothing is published: a stale press is a no-op.
  - **An expired offer (D11):** logged at info. Nothing changes.
- **The button is retired** by the relay. On a `StatusChanged` to a status that
  no longer accepts a resolution (`resolved`, `withdrawn`, `disproven`), it
  `chat.update`s each of the incident's `chat-offer` messages to say who ended
  it and through which channel, or what status it ended in. `mitigated`,
  `escalated` and `recommended` still accept one, so their offers keep the
  button. A refused update is recorded as `CommunicationFailed`, as a refused
  post is.

*Alternatives:*
- "Reply yes". That needs a second classification, of an ambiguous reply.
- `response_url`, which would need a Slack client in `argus_web`, and a reply
  that isn't the relay's.

### D5. Who resolved it

The person's Slack id is kept on `ResolutionOffered`, and their name is read
once, when the offer is made. The id is what the press is checked against; the
name is what the report and the postmortem say. If the read fails, the offer
still stands, addressed to "whoever wrote it", and the resolution credits the
person by their Slack id. The new bot scopes are `users:read` and `channels:history`.

### D6. `ReportChannel.SLACK`

`"slack"`, named for the place a reader goes to find the person, as
`PAGERDUTY` is. Narration adds "from Slack", and the note is the person's
message, verbatim.

### D7. The classifier's answers in tests

- **A second Anthropic double** serves only the intent agent, on its own port, so
  its answers never interleave with a walk's FIFO. The noxfile starts it beside
  the first and points the intent agent's `ANTHROPIC_BASE_URL` at it. The e2e case
  seeds it by recording name, through the existing control seam.
- **One recording**, `intent-resolve`, of the classifier answering the e2e
  case's message. `scripts/record_classification.py <name> <message>` runs the
  intent agent's classifier once against the real API through the double in record
  mode. It is a single small paid call, run by the user.
- The walks' recordings are untouched. The walk makes no new call, and the
  resolution reaches it as it does from the UI.
- Settings: `intent_model` and `intent_effort` (the kernel's defaults), and
  `intent_poll_seconds`.

### D8. `slack_double`

It gains three things:
- `users.info`, answering with a person staged through
  `POST /double-control/user`, and `user_not_found` otherwise;
- `chat.update`, recorded beside the posts;
- `blocks`, kept on every posted message.

It stays scenario-blind (double-seeding-style). Inbound deliveries are not the
double's job: the e2e case signs and POSTs them to `argus_web` itself, with the
fixture signing secret the noxfile gives the stack. The double is off-limits,
so the whole file is proposed in chat. `tests/contract/slack` gains
`users.info` and `chat.update` (the user writes them).

### D9. Layering

- `chat_platform` knows only `argus_core`. It is Slack's one adapter, in both
  directions: the port is split as the deployment platform's is, into
  `ChatPlatformReads` (deliveries, a person's name) and `ChatPlatformWrites`
  (post, rewrite). The Communicator's own Slack module goes; it posts through
  `ChatPlatformWrites`, handing the port an `Offer` rather than blocks, so the
  button's action id and value are spelled only in the adapter that also reads
  the press.
- `argus_web`, `agent_intent` and `agent_communicator` may import
  `chat_platform`, and only their composition roots (`argus_web.app`,
  `agent_intent.watching`, `agent_communicator.watching`) may import
  `chat_platform.slack`; a contract holds that.
- `agent_intent` knows `argus_core` (including `argus_core.llm`, newly opened
  to it), `argus_incidents` and `chat_platform`. It joins the agent-independence
  contract.
- Both new modules join `root_packages`.

### D10. e2e

One new case, which the user writes, in `test_resolving_an_incident.py`. It is
ordered, not timed: nothing in it waits for Argus to reach a point before
something else does.
1. feature-flag-toggle; the intent agent's double seeded with `intent-resolve`,
   a person staged in `slack_double`, and the walk's double told to hold
   (`POST /double-control/hold`);
2. the alert fires, and the investigator's first call waits at the double;
3. POST a signed message event into the incident's thread, read from the
   double's posts. `argus_web` stores it before answering;
4. seed the walk's double with `less_code_fix=True`, which releases the held
   call. The investigator finishes, and the walk waits (D11);
5. wait for the offer, whose button is in the posted blocks;
6. POST a signed press by that person.

It asserts the incident is `resolved`, there's a postmortem, no fix was looked
for, the account names the person, "Slack" and their words, and the offer has
been updated to say who resolved it. It does not check the flag: that a
resolution leaves Argus's changes in place is the page case's claim, and the
same for every channel.

*Why not wait for the flag, as the page case does:* the person then has to
write, be offered and press inside mitigation's verification, which is the
stack's clock against several polls. It lost that race by 0.2 seconds.

`anthropic_double` gains the hold: after `POST /double-control/hold`, a call
with nothing queued waits until the next seed or `POST /double-control/release`.
Without a hold, an empty double refuses at once, as it always has. Off-limits,
so the whole file is proposed in chat.

### D11. A walk waits for the press

Once a person has written in the thread, the walk starts no new step until
each message is answered:
- understood as anything but `resolve`; or
- offered, and the offer pressed; or
- 5 minutes past the message, on the stack's clock.

A step already running finishes. A press still ends the walk as it does today,
whatever it is doing. Nothing is cut off halfway.

At 5 minutes, an offer still standing expires. The walk publishes
`OfferExpired(message)`, and the relay `chat.update`s the offer to "Not
confirmed in time; Argus carried on", without the button. The walk then
carries on. The expiry is narrated, so it is on the page and in the
postmortem. A person who still wants it over writes again, and is offered
again.

The wait starts from the message, not the offer, so a walk cannot pass the
point between a message stored and its offer posted. A walk that is not
running waits for nothing, and its offers keep their buttons (D4).

*Why wait at all:* Argus has asked a person whether the incident is over. A
step started before they answer is work they may be about to make pointless,
and it is a change made while a person is about to report the incident over.

*Alternative:* don't wait, and let the press end the walk wherever it is. That
is what was built first. A walk's progress then depends on how fast a person
answers, and nothing could be asserted about what Argus did meanwhile.

## Risks / Trade-offs

- [A misread message offers a resolution nobody meant] → Nothing changes until
  the person who wrote it presses the button.
- [The intent agent lags or is down] → Messages wait on the cursor and are
  understood when it returns. Nothing is lost, and nothing resolves without a press.
  A walk waits up to 5 minutes for it (D11), then carries on.
- [A walk waits 5 minutes holding its run] → The worker renews the run's claim
  for as long as the walk runs, waiting included, so nobody takes it back.
- [A model outage] → One retry, then `other` with a warning. The person can
  still resolve from the UI.
- [A retried event delivery] → The message reference is claimed once (D2).
- [A replayed signed request] → Timestamps older than five minutes are refused.
  A replayed press is idempotent anyway.
- [Two Slack code paths: the Communicator's `slack.py` and the adapter] →
  Accepted for now (Non-Goals). Both use `slack_sdk`, and both are checked by
  the Slack contract suite.
- [The index's `split_part` assumes no `/` in a channel id] → Slack channel ids
  are alphanumeric.

## Migration Plan

Revision `001` is still the whole chain: `slack_thread` is dropped from it and
the partial unique index is added, and `nox -s schema` recreates the schema.
Threads opened before the change are lost with the drop, as every row is.

The Slack app needs the following, set by the user:
1. scopes `channels:history` and `users:read`, then reinstall;
2. Event Subscriptions on, URL `<tunnel>/webhooks/slack/events`, bot event
   `message.channels`;
3. Interactivity on, URL `<tunnel>/webhooks/slack/interactions`;
4. the signing secret into `.env` as `SLACK_SIGNING_SECRET`.

## Open Questions

None.
