Every behaviour task is TDD: propose the failing test in chat (the user applies
it), see it red for the right reason, then implement. Bottom-up: kernel,
incident record, the port, the web, the intent agent, the relay, the double, e2e.

## 1. Kernel

- [x] 1.1 `ReportChannel.SLACK`
- [x] 1.2 Events `PersonWrote(message, person_id, text)`,
      `MessageUnderstood(message, meaning)` with a closed `Meaning`
      (`resolve`, `question`, `information`, `withdraw`, `other`), and
      `ResolutionOffered(message, person_id, person_name, said)`; each
      round-trips through the event log
- [x] 1.3 Reference kinds `CHAT_THREAD`, `CHAT_MESSAGE`, `CHAT_OFFER`, and the
      `"<channel>/<message>"` value built and read in one place (the kernel's
      `a_chat_thread`, `a_chat_message`, `a_chat_offer`, `the_place_of`)
- [x] 1.4 Settings: `slack_signing_secret` (default empty), `intent_model`,
      `intent_effort`, `intent_poll_seconds`

## 2. Incident record

- [x] 2.1 Revision `001`: drop `slack_thread`; add the partial unique index for
      one `chat-thread` per incident per channel
- [x] 2.2 `references.claim`: writes once, and says whether it wrote (real
      Postgres)
- [x] 2.3 A second `chat-thread` for the same incident and channel writes
      nothing; another channel writes (real Postgres)

## 3. The port and the Slack adapter (`chat_platform`, new module)

- [x] 3.1 Module scaffold (new-module skill), `root_packages`, the layering
      contract (D9)
- [x] 3.2 `ChatPlatformReads` Protocol, the `Delivery` union, `ChatDeliveryUnverified`
- [x] 3.3 Signature: `v0` HMAC over `v0:{timestamp}:{body}`, constant-time;
      a mismatch, a timestamp over five minutes from an injected clock, or an
      empty secret raises
- [x] 3.4 `parse_delivery` for events: the handshake; a reply in a thread;
      ignoring top-level messages, bots, every subtype
- [x] 3.5 `parse_delivery` for interactions: the form-encoded `payload`, the
      `resolve-incident` press, anything else irrelevant
- [x] 3.6 `person_named`: real name, then display name; unknown or unreachable
      means `None`, never raised
- [x] 3.7 The adapter declares `channel = ReportChannel.SLACK`; no Slack
      configured means no adapter is built

## 4. Web

- [x] 4.1 `POST /webhooks/slack/events`: `404` unconfigured, `401` unverified,
      the challenge answered, a reply recorded with its message reference
      claimed in one transaction, unknown threads and repeats acknowledged with
      nothing recorded
- [x] 4.2 `POST /webhooks/slack/interactions`: the offer's person resolves
      through `resolve_incident`, with `Report(name, SLACK, said)`; someone
      else, no matching offer, or an ended incident changes nothing, each logged
- [x] 4.3 Layering contract: `argus_web` may import `chat_platform`, and
      `argus_web.app` may import `chat_platform.slack`

## 5. The intent agent (`agent_intent`, new module)

- [x] 5.1 Module scaffold, `root_packages`, the agent-independence contract,
      `argus_core.llm` opened to it; the log-following seams (`cursors`,
      `Backlog`, `Place`) moved from `agent_communicator` to `argus_incidents`,
      since two agents now follow the log
- [x] 5.2 The classifier: one call with a submit tool, answered with a
      `Meaning`; one retry, then `other` with a warning
- [x] 5.3 Understanding a `PersonWrote`: publishes `MessageUnderstood`; on `resolve`
      for an incident that accepts a resolution, names the person and publishes
      `ResolutionOffered` (no name when unnamed); none on an ended
      incident
- [x] 5.4 Following the log under reader `intent`, and
      `python -m agent_intent.watching` (process logging, telemetry name)
- [x] 5.5 Noxfile: start the intent agent with the stack, and a second
      `anthropic_double` for it alone
- [x] 5.6 `scripts/record_classification.py <name> <message>`

## 6. The relay (`agent_communicator`)

- [x] 6.1 The war room is found and remembered through `incident_reference`;
      remove `repository/threads.py`
- [x] 6.2 `ResolutionOffered` is `FOLLOWED`; `PersonWrote` and
      `MessageUnderstood` stay `UNSAID`
- [x] 6.3 The offer is posted with its button, and its reference recorded
- [x] 6.4 A `StatusChanged` to a status that no longer accepts a resolution
      retires every offer through `chat.update`;
      a refusal is recorded as `CommunicationFailed`

## 7. Narration

- [x] 7.1 Lines for `PersonWrote`, `MessageUnderstood` and `ResolutionOffered`;
      "from Slack"

## 8. `slack_double` (off-limits: propose the whole file in chat)

- [x] 8.1 `users.info` with `POST /double-control/user`, forgotten on reset;
      `chat.update`; `blocks` kept
- [x] 8.2 `tests/contract/slack`: `users.info` and `chat.update` against the
      real workspace (user writes)

## 9. Spec and docs

- [x] 9.1 `docs/spec-and-architecture.md`:
      - §7: the Intent Agent;
      - §12: the chat platform port and the two endpoints;
      - §16: a report from the thread is the fact, like any other channel
- [x] 9.2 `.env.example`: `SLACK_SIGNING_SECRET`, `INTENT_*`, and the Slack
      app's scopes, event and interactivity URL

## 10. Verification

- [x] 10.1 Record `intent-resolve` (user runs; one small paid call)
- [x] 10.2 e2e case (user writes it): resolved from Slack after the flag is off
      (D10)
- [x] 10.2a Eval (`tests/eval`, user writes; paid, `nox -s eval`): the intent agent's
      classification scored against a labelled set of messages for each of the
      five meanings - the replay proves the plumbing, never the classification. Written,
      not run: nothing in this change spends on measuring it
- [x] 10.3 Cleanup: comments, docstrings, jargon, logs and docs aligned; no
      test missing, redundant or weak; no missing log or wrong log level.
      Design and specs to align with what was built: D5, an unnamed person is
      credited by their Slack id, not "could not say"; D4 and the
      slack-communication spec, offers are retired when the incident no longer
      accepts a resolution (`resolved`, `withdrawn`, `disproven`), not on every
      terminal status - `mitigated` still takes one
- [x] 10.3a One Slack adapter: posting moves from `agent_communicator/slack.py`
      into `chat_platform` (`slack_posting.py`), the port splits into
      `ChatPlatformReads`/`ChatPlatformWrites`, the Communicator hands it an
      `Offer`, and a layering contract keeps the vendor in the three
      composition roots; posting's suites move to `chat_platform` (user
      applies)
- [x] 10.3b One word, one meaning: the listener is the intent agent
      (`agent_intent`, `INTENT_*`, reader `intent`, recording
      `intent-resolve`); a webhook is received, a message ingested
      (`ingest_a_message`), a delivery parsed (`parse_delivery`, both ports),
      a message classified (`classifying.classify`) and understood; the
      Communicator says lines to a `Destination` (`saying.a_chat_destination`,
      reader `chat`); Slack's markup moves into the adapter (`Line`, `Link`);
      `the_place_of` takes a value; `ChatDeliveryUnverified` and
      `OnCallDeliveryUnverified`
- [x] 10.3c "interpreter" already meant the Python interpreter: the agent is
      the intent agent, and its loop `watching.watch_once`/`watch_forever`
- [x] 10.4 Module suites, typecheck, lint, guard_layering green
- [x] 10.5 `e2e_replay(mode='both')` green, in the background: 50 of 50 at
      17:42 on 2026-10-10, once section 11 made the Slack case ordered
- [ ] 10.6 Specs synced on archive

## 11. Argus waits for the press

- [x] 11.1 Design (D11): once a person's message is stored, the walk starts no
      new step until every message is understood and every offer answered,
      or 5 minutes pass on the stack's clock. A step already running
      finishes; a press still ends the walk as today
- [x] 11.2 An offer not pressed in time: its button is removed
      (`chat.update`, "Not confirmed in time; Argus carried on"), and the walk
      carries on. Logged, and in the postmortem
- [x] 11.3 Spec deltas for 11.1 and 11.2
- [x] 11.4 The wait in the walk (test-first)
- [x] 11.5 The expired offer in the relay and the narration (test-first)
- [x] 11.6 `anthropic_double`: `POST /double-control/hold` - calls wait until
      the test seeds or releases; without a hold, nothing changes (user writes)
- [x] 11.7 The Slack e2e case, ordered rather than timed: hold, alert, write,
      seed, press. No flag check - the page case holds that claim (user
      writes)
