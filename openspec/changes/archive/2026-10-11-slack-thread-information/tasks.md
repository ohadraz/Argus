Every behaviour task is TDD: propose the failing test in chat (the user applies
it), see it red for the right reason, then implement. Bottom-up: kernel, the
record, the refactor onto it (proved by the existing suites before anything new
lands), then leads through each agent, narration and relay, e2e.

## 1. Kernel

- [x] 1.1 Migration `001`: the `thread_message` table, keyed by the message's
      reference (D1)
- [x] 1.2 `Standing` (supported, refuted, unverified) and `Weighing` in
      `argus_core.models`; a lead is a `ThreadMessage` (D3, D4)
- [x] 1.3 Event `LeadWeighed(message, standing, reason)`, round-tripping
      through the event log

## 2. The record

- [x] 2.1 `argus_incidents.repository.conversation`: write on ingest; meaning;
      offer; expiry; standing; `get` by reference, `get_all_by_incident`,
      `get_leads_by_incident`, `get_not_understood` (D1)
- [x] 2.2 Ingestion writes the row with `PersonWrote` in one transaction, in
      place of the reference claim; `references.claim` removed

## 3. Off the event log (D2)

- [x] 3.1 The intent agent writes meaning and offer to the row, then publishes
      their events
- [x] 3.1a The intent agent finds unclassified messages on the table, oldest
      first; its cursor reader retired
- [x] 3.2 The wait reads the rows; expiry sets `offer_expired`, then publishes
      `OfferExpired`; the same rows with no events give the same answer
- [x] 3.3 The press finds its offer on the row
- [x] 3.4 Nothing in `src` decides on `PersonWrote`, `MessageUnderstood`, an
      offer or `OfferExpired`; resolution and withdrawal e2e cases still green
      under replay

## 4. The walk

- [x] 4.1 `leads` seam bound in `graph.py` beside `still_wanted`, over
      `conversation.get_leads_by_incident`; handed to the Investigator and
      Code-Fix (D3)
- [x] 4.2 Standings returned by the Investigator are written to their rows,
      then `LeadWeighed` published (D5)

## 5. Investigator (D3, D4)

- [x] 5.1 Leads in the opening message, labelled `L1`, `L2`, … with any
      earlier standing
- [x] 5.2 Leads understood since the last turn ride on the next tool result
- [x] 5.3 `weigh_lead(lead, standing, reason)`, offered from the turn the first
      lead is shown; a walk with no leads sends today's requests unchanged
- [x] 5.4 `final_answer` refused while a lead shown is unweighed; the later of
      two weighings stands
- [x] 5.5 What each standing allows: carried by the `weigh_lead` description
      and the leads section, not `BRIEF` (so no-lead walks send today's brief);
      pinned by `tools/test_weighing.py`

## 6. Code-Fix (D6)

- [x] 6.1 Leads in the opening message with their standing, or unweighed
- [x] 6.2 Leads understood mid-loop ride on the next tool result

## 7. Postmortem (D8)

- [x] 7.1 Evidence gains the leads, from the record
- [x] 7.2 A labelled section in the prompt
- [x] 7.3 `PostmortemDocument.leads`; `submit_postmortem` gains `lead_effects`;
      a lead left out is refused
- [x] 7.4 The postmortem page shows each lead, its standing and what it changed

## 8. Narration and relay (D5)

- [x] 8.1 A line for `LeadWeighed`
- [x] 8.2 The relay follows it and posts it in the thread

## 9. Spec and docs

- [x] 9.1 `docs/spec-and-architecture.md`: §7.2 and §7.4 (leads in, standings
      out), §7.5 (the standing in the thread), §7.5a (a lead), §7.6 (the
      section), §7.9 (the press reads the record), §11 (the conversation table)
      and §21 (scenario 7 on `competing-flag-changes`)
- [x] 9.2 `events.py` docstring re-read against what reads events; true as it
      stands

## 10. Verification

- [x] 10.1 Record `intent-information` (user runs; one small paid call)
- [x] 10.2 Verify for free that record mode honours the double's hold; if not,
      propose the double's change in chat
- [x] 10.3 e2e cases (user writes them): the lead before the walk, and the lead
      mid-investigation through the hold (D9)
- [x] 10.4 Record both walks, in every mode the replay runs (user runs; paid) -
      `both` recorded; `grep` and `meaning` deferred by the user, the nightly
      fails the two cases in those modes until they are
- [x] 10.5 Eval pair in `tests/eval/test_investigator_eval.py` (user writes
      it): `competing-flag-changes` with and without the lead (paid) - written
      and collected, not run; the shop logs the renderer split for the decoy
      scenario so the evidence holds both readings
- [x] 10.6 Cleanup: comments, docstrings, jargon, logs and docs aligned; no
      test missing, redundant or weak; design and specs match what was built
- [x] 10.7 Module suites, typecheck, lint, guard_layering green
- [x] 10.8 `e2e_replay(mode='both')` green, in the background
- [x] 10.9 Specs synced on archive
