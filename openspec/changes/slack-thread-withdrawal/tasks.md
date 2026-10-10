Every behaviour task is TDD: propose the failing test in chat (the user applies
it), see it red for the right reason, then implement. Bottom-up: kernel,
incident record, the port, the web, the intent agent, the relay, e2e.

## 1. Kernel

- [x] 1.1 `IncidentStatus.accepts_withdrawal()`: every non-terminal status;
      `incidents.withdraw` guards with it (D2)
- [x] 1.2 Event `WithdrawalOffered(message, person_id, person_name, said)`,
      round-tripping through the event log;
      `type Offered = ResolutionOffered | WithdrawalOffered`
- [x] 1.3 Reference kinds: `CHAT_OFFER` renamed `CHAT_RESOLUTION_OFFER`
      (`chat-resolution-offer`); `CHAT_WITHDRAWAL_OFFER`
      (`chat-withdrawal-offer`), with its `a_chat_withdrawal_offer` builder

## 2. Incident record

- [x] 2.1 The wait (D6): a withdrawal offer is waited on as a resolution offer
      is; an offer whose ending the current status no longer accepts is not
      waited on (`status_of` injected)

## 3. The port

- [x] 3.1 `chat_platform`: the action id `confirm-offer` is posted and the
      only one read as a press

## 4. Web

- [x] 4.1 `_confirm`: a press on a `WithdrawalOffered` by its person withdraws
      with `Report(name or id, SLACK, said)`; someone else, an expired offer,
      or an incident that no longer accepts a withdrawal changes nothing, each
      logged (D5)
- [x] 4.2 `ChatRecord.offer_about` answers either offer; `ChatRecord.withdraw`
      calls `withdraw_incident`

## 5. The intent agent

- [x] 5.1 `understand` takes `status_of`; on `withdraw` it names the person
      and offers where the status accepts a withdrawal, and does nothing more
      otherwise (D3)
- [x] 5.2 `watching._understanding` wires `status_of`

## 6. Narration

- [x] 6.1 A line for `WithdrawalOffered`; `OfferExpired` no longer says
      "to resolve";
      `asks_to_confirm` set for both offers; `leaves_nothing_to_withdraw` (D8)

## 7. The relay (`agent_communicator`)

- [x] 7.1 `WithdrawalOffered` is `FOLLOWED`
- [x] 7.2 The withdrawal offer is posted with "Stand Argus down" and recorded
      as `chat-withdrawal-offer`; the resolution offer as
      `chat-resolution-offer`
- [x] 7.3 Retirement by kind (D7): an ending that refuses a resolution retires
      both; any other terminal status retires withdrawal offers only; an
      expiry retires both

## 8. Spec and docs

- [x] 8.1 `docs/spec-and-architecture.md` §7.5 (two offers, retired by what
      they offer), §7.5a (the Intent Agent offers a withdrawal; the wait), §7.9
      (a press ends the incident as its offer offered) and §10 (a withdrawal
      reaches Argus from the page and the thread)

## 9. Verification

- [x] 9.1 Record `intent-withdraw` (user runs; one small paid call)
- [x] 9.2 e2e case (user writes it): withdrawn from Slack after the
      investigation, nothing changed (D9)
- [x] 9.3 Cleanup: comments, docstrings, jargon, logs and docs aligned; no
      test missing, redundant or weak; design and specs match what was built
- [x] 9.4 Module suites, typecheck, lint, guard_layering green
- [x] 9.5 `e2e_replay(mode='both')` green, in the background
- [ ] 9.6 Specs synced on archive
