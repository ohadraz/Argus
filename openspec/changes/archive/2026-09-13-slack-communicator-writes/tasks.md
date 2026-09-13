Tests are the user's to write throughout (`AGENTS.md`): each task below that
names a test means proposing it whole in chat, having it added, watching it
fail, and only then writing the code under it. `modules/slack_double` is
test-support code and off-limits to Claude for the same reason
`anthropic_double` is - propose it whole in chat.

## 1. The double

- [x] 1.1 `modules/slack_double`: a server accepting the Web API methods the
      Communicator calls, answering in Slack's shapes, dev-only and in
      `EXCLUDED_FROM_TESTS`.
- [x] 1.2 The control seam: reset, and seeding the next answer - a refusal, a
      rate limit, an unknown channel.
- [x] 1.3 The recording it exposes: what was posted, to which channel, and what
      it was a reply to.

## 2. The adapter

- [x] 2.1 Propose the test: a message posted through the adapter arrives at the
      double with the channel and text it was given.
- [x] 2.2 The Slack client in `agent_communicator`, reached by base URL, with
      the bot token and the two channel names in `argus_core.config` and
      `.env.example`.
- [x] 2.3 Test: a refusal and an unreachable workspace are both survived, and
      neither is raised out of the Communicator.
- [x] 2.4 The failure path itself - recorded on the timeline, the walk
      continuing. Deferred to after 4.3: recording against an incident needs an
      incident, and the adapter posts without one. A refusal is read for
      whether trying again could end differently: a throttle or an unreachable
      workspace keeps the line's place in the relay, and anything else is
      written on the incident as `communication-failed` and passed over.

## 3. The narration, lifted

Slack is a projection of the event log, not a set of calls inside the walk:
`agents -> events -> [outbox] -> relay -> policy -> renderer -> channels`. The
account a reader follows already exists, in `argus_web`; it is rendered once
and read by every destination rather than written twice.

- [x] 3.1 `modules/argus_narration`: the event-to-sentence renderer moved out of
      `argus_web/views/` whole - `narrating.py` and the helpers it reads events
      with (clock, findings, flags, logs, metrics, prose) - depending on
      `argus_core` and nothing else. Behaviour-preserving; `argus_web`'s own
      suite is what says so.
- [x] 3.2 The page's decoration stays in `argus_web`: the CSS class on the
      emphasised word and the anchors a line links to are the page's, derived
      there from the line rather than carried out of the shared renderer. The
      line keeps the minute it is about, which is a fact rather than a link;
      `argus_web/views/decorating.py` turns that into an anchor.
- [x] 3.3 The two narrations told apart as part of the lift -
      `publishing.narrate` writes an event down, `narrating.build_narration`
      renders one. One of them is renamed so the shared module has one meaning.

## 4. The relay

- [x] 4.1 Propose the test: events written for an incident reach the war-room
      channel as the same sentences the dashboard shows, in the order they were
      published.
- [x] 4.2 `events.get_since(seq)` on the events repository - the read a cursor
      needs, ordered by `seq`, across incidents rather than within one.
- [x] 4.3 The relay in `agent_communicator`: a loop over `incident_event`
      holding a durable cursor of its own, at-least-once, outside the walk and
      unable to fail it. A duplicate message is accepted; a silent miss is the
      thing this exists to prevent.
- [x] 4.4 The delivery policy - event kind to whether a human hears it and in
      which register. Retrievals stay out; onset, candidates, actions, verdicts
      and transitions go in.
- [x] 4.5 Test: the first message for an incident opens its thread and later
      ones reply to it, across two runs of the relay.
- [x] 4.6 The correlation stored where the integration is -
      `slack_thread(incident_id, channel, ts)` - so `incident` never learns
      Slack exists and a second channel adds a mapping rather than a column.
- [x] 4.7 Test: an incident reaching a terminal status is announced in the
      channel, naming the status; the postmortem is posted to its own channel
      and the closing message links to it; an incident without one is still
      announced. The link is to Argus's own postmortem page - `ARGUS_BASE_URL`,
      configured as it is for anything that links into itself - and the war
      room is told where the write-up went only where that is somewhere else.
- [x] 4.8 Postmortem delivery moved into the Communicator, with the Postmortem
      agent left producing the document and nothing else. The walk publishes
      `postmortem-written` beside the row it stores; a new register, `FILED`,
      is what sends it to the postmortem channel rather than the war room.

## 5. Running the thing

- [x] 5.1 `post_update` and `page` deleted from the walk, with the graph's
      seams removed: what they said is now said by the relay, off the events
      they were called beside.
- [x] 5.2 The relay and the double join `_LOCAL_SERVICES` in `noxfile.py` and
      the compose stack, with `e2e_replay` pointing the relay at the double.
- [x] 5.3 The `print()` is deleted. `PYTHONIOENCODING` stays: it is set beside
      `PYTHONUNBUFFERED` for every service the stack starts, and what it guards
      is a redirected stdout on Windows rather than anything the Communicator
      used to write.
- [x] 5.4 Test: the replayed e2e stack walks an incident with no Slack
      credential present, and the double holds the messages a human would have
      seen.

## 6. Against the real thing

- [x] 6.1 Propose the contract test: the success shape and the refusal, against
      the real workspace and the double alike.
- [x] 6.2 Split `nox -s contract` so the free check can run without the paid
      one - the Slack contract selectable on its own, the Anthropic contract
      staying where it is.
- [x] 6.3 The workspace's bot token as a repository secret, read by
      `nightly.yml` and named in `.env.example`; in no push-triggered job.
- [x] 6.4 The Slack contract runs in the nightly, and reports rather than skips
      where the credential is absent.
- [x] 6.5 A run of it against the real workspace.

## 7. Closing out

- [x] 7.1 `lint`, `typecheck`, `test_all`, `integration`, `e2e_replay`.
- [x] 7.2 Spec §7.5 updated for what the Communicator now does, per the
      `spec-doc-style` skill. §12.1 and the integration table go with it: no
      outbound message passes through either MCP server, because telling a
      person something changes nothing in the environment being fixed.
- [x] 7.3 One-line commit, approved before it is made, and the archive as a
      second commit.
