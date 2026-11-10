Every behaviour task is TDD: the test is proposed in chat as a whole file, the
user adds it, then the code is written against it. Nothing in the postmortem's
document, row, prompt or output changes; its code changes only by task 4.0.

## 1. Model and storage

- [x] 1.1 `ExecutiveSynopsis` and its per-title row in `argus_core.models`
- [x] 1.2 `executive_synopsis` table in revision `001`; propose tests for its repository in `argus_incidents`; implement

## 2. Per-title cost

- [x] 2.1 Propose tests for grouping by title beside `responder_cost` (people and minutes per title, order of first response, no-title row, unpriced title keeps people and minutes, rows add up to `responder_cost` to the cent); rounding for display is 6.1's
- [x] 2.2 Implement it in a new file
- [x] 2.3 Propose tests for the check against the stored postmortem (people, minutes, midpoint, minimum, maximum to the cent, currency; a sub-cent difference matches; a moved band: totals only, said)
- [x] 2.4 Implement it

## 3. Resolution list

- [x] 3.1 Propose tests: each step in the postmortem Resolution's words, then a pull request left for review, then a recommendation not taken
- [x] 3.2 Implement it in `postmortem_rendering`, from the page's own actions-taken and action-items sections

## 4. The overview call

- [x] 4.0 Propose tests for a public function that runs the four figure rules and returns each rule's faults under its own name; implemented as `agent_postmortem.figure_rules`, with `checking`'s four private rules calling it under their own names and messages, unchanged
- [x] 4.0a Propose tests for `postmortem_rendering.synopsis_figures`: the figures the overview may name, each as the page writes it, only where the record holds it; implement it
- [x] 4.1 Propose tests for the prompt and the tool (figures by name, required only where held; pay by name with no amount; symptom, cause, resolution list; sizing words and claims beyond the list forbidden)
- [x] 4.2 Implement them
- [x] 4.3 Propose tests for the checks: written-out figure refused through the public function, required figure missing refused only where held
- [x] 4.4 Implement them
- [x] 4.5 Propose tests for the conversation: one refusal sent back through the tool result, given up after the second or on a model error
- [x] 4.6 Implement it

## 5. The step

- [x] 5.0 `ExecutiveSynopsisWritten` and `ExecutiveSynopsisWithheld` in `argus_core.events`, carrying no figure, tested through 5.1
- [x] 5.1 Propose tests for `write_executive_synopsis` (written whatever is configured; written: row and `ExecutiveSynopsisWritten`; given up: row without overview and `ExecutiveSynopsisWithheld` with the reason; a resolution reported later writes nothing)
- [x] 5.2 Implement it, and put it on the graph after the postmortem, under a policy of its own with no postmortem brief
- [x] ~~5.2a Propose an integration test: one incident written up with the step and without it stores the same `postmortem` row~~ dropped: the synopsis step writes only its own table, so there is nothing for it to catch
- [x] 5.3 Narration lines for the two events in `argus_narration`

## 6. Rendering

- [x] 6.1 Propose tests for the synopsis's lines in `postmortem_rendering`: part order, UTC, the impact cards as the page has them, a disproven alarm's alert and close, the per-title table with range, total and basis, a shared page said, no loss-plus-cost figure, the postmortem's address or no link
- [x] 6.2 Implement them
- [x] 6.3 Propose tests for `as_markdown`
- [x] 6.4 Implement it

## 8. Slack

- [x] 8.1 Setting `EXECUTIVE_SYNOPSIS_SLACK_TO` in `argus_core`; `.env.example` with the responder and private-channel warnings; the local `.env` with `EXECUTIVE_SYNOPSIS_SLACK_TO=<user slack member id>`
- [x] 8.2 Propose tests for the `BRIEFED` register: `ExecutiveSynopsisWritten` is briefed, and nothing else is
- [x] 8.3 Propose tests for the chat relay: a briefed event posts once to each configured Slack id, never the war room, thread or postmortem channel; nothing with none configured or for a withheld synopsis; one refusal recorded without stopping the others
- [x] 8.4 Implement them

## 9. Stack and recordings

- [x] 9.1 `e2e`, `record` and `e2e_replay(mode='both')` configure two Slack ids on the Slack double, a member's and a channel's (`e2e` posts to real Slack, so it sends to the ids in `.env`)
- [x] 9.2 Propose an e2e case: the synopsis reaches the Slack double's member and channel; no `argus_web` route and no war-room, thread or postmortem-channel post carries a responder cost figure
- [x] 9.3 `--synopsis-only` in `scripts/record_incident.py`, refusing a case whose postmortem requests diverge
- [x] 9.4 Price the 34 `both` synopsis exchanges and ask before any recording
- [x] 9.5 Record them, then judge every overview (sizing words, claims beyond the resolution list)
- [x] 9.6 `e2e_replay(mode='both')` green

## 10. Docs and checks

- [x] 10.1 `docs/spec-and-architecture.md`: §7.5, §7.6, §21.3, `INTEGRATION_CONFIG` (`spec-doc-style` skill)
- [x] 10.2 `lint`, `typecheck`, `guard_layering`, `test_all`, `integration` green
