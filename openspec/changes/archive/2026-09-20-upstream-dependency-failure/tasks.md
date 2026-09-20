## 1. The shop calls a provider it does not own

- [x] 1.1 Add the payment-provider client to `io_shop` - the shopper's stored card, fetched through a seam the caller supplies, raising an error that names the provider's host and the status it answered with
- [x] 1.2 Call it from `serve_account_page`, with no retry, no fallback and no degradation, so the failure reaches the request boundary the way every other one does
- [x] 1.3 Cover both in the demo app's own suite (written after the code, as that repo's tests are): a healthy provider leaves the page as it was, a failing one fails it and names the provider

## 2. The generator stages the outage

- [x] 2.1 Give the generator an upstream timeline beside the flag one - when the provider began failing, and when it stopped - and hand the failing state into the rendered sample
- [x] 2.2 Raise the minute's latency while the provider is failing, leaving memory at its baseline, so the scenario's signature is errors *and* latency with nothing changed
- [x] 2.3 Keep every existing scenario's figures exactly where they are - draws are seeded per minute, so anything inserted before an existing draw shifts all of them
- [x] 2.4 Emit the failure lines for the window, naming the provider's host and status
- [x] 2.5 Add `upstream-dependency-failure` to the scenario registry: seeded by failing the provider, cleared only by reset, touching no flag and no deploy record
- [x] 2.6 Cover the scenario in the demo app's suite - seeded signature, reset restores baseline, a restart changes nothing
- [x] 2.7 Offer it in the operator console rather than leaving it seedable by id alone: it is a scenario worth watching, and the console is where an audience stages one. (`resource-leak` is hidden on the same terms and is the next change's to fix, not this one's.)

## 3. Argus names the mode

- [x] 3.1 Add `UPSTREAM_DEPENDENCY_FAILURE = "upstream-dependency-failure"` to `FailureMode`, with the comment saying why it is named at this level
- [x] 3.2 Leave `DEFAULT_STRATEGIES` without an entry for it, and say in the mapping's own words that the absence is the decision
- [x] 3.3 Extend the Investigator's prompting so the mode is one it can determine, without naming the demo's scenario or its provider
- [x] 3.4 Propose the `agent_mitigation` test updates in chat. Nothing for `agent_investigator`: the mode reaches the model through the tool schema's enum, which is generated from `FailureMode`, and what changed in the brief is prose the eval suite measures rather than a unit test

## 4. The refusal says which silence it is

- [x] 4.1 Add `Refusal.NOTHING_ANSWERS_THIS_MODE` and the sentence its row reads as
- [x] 4.2 Expose from `agent_mitigation` the question the gate asks - whether any generic mitigation answers a given mode - so the gate holds no second copy of the set
- [x] 4.3 Give the refusal at the gate when the hypothesis names a mode nothing answers, leaving `NO_MITIGATION_PROPOSED` for an action nobody could identify
- [x] 4.4 Render both refusals in `argus_narration`, and check how each reads on the incident page and in Slack
- [x] 4.5 Propose the gate and narration test updates in chat

## 5. End to end

- [x] 5.1 Propose the e2e case in chat: the scenario seeded, the incident diagnosed as an upstream failure, escalated with a postmortem, no flag touched and no restart taken
- [x] 5.2 Record it against the real API. `both` only: that is the mode CI replays, and `grep` holds the walks Code-Fix took before retrieval by meaning existed. 13 answers captured, ~7.6k output tokens, six minutes
- [x] 5.3 `nox -s lint`, `typecheck`, `guard_layering`, `guard_e2e_boundary`, `test_all`, `integration`, then `e2e_replay(mode='both')` green

## 6. The documents catch up

- [x] 6.1 Update `docs/spec-and-architecture.md` §15.3's row for this scenario, and §7.3's escalation wording, as a specification rather than a note
- [x] 6.2 Mark FM-01 as built in `docs/failure-modes-backlog.md`, and correct the two lines that still call the memory leak the one being built

## 7. The other silence

- [x] 7.1 A gate case for a candidate that determined no mode at all: it reads as `NO_MITIGATION_PROPOSED`, since there was nothing to look a mitigation up by
