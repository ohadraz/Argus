Tests are the user's to write throughout (`AGENTS.md`): each task below that
names a test means proposing it whole in chat, having it added, watching it
fail, and only then writing the code under it.

## 1. What the shop took

- [x] 1.1 Propose the test: a window with two succeeded charges and one refund,
      answered as one amount in one currency.
- [x] 1.2 `modules/revenue_source/`, scaffolded per the `new-module` skill,
      depending on `stripe` and on nothing of Argus's but `argus_core`.
- [x] 1.3 The sum: succeeded charges less refunds, per currency, over a listing
      the caller supplies.
- [x] 1.4 Test: a failed charge and a pending one are absent from the figure.
- [x] 1.5 Test: a window with no charge answers "nothing taken", and an
      unreachable provider answers "could not be read" - distinguishably.

## 2. The estimate reaches the page

Merged with what was a walking skeleton wired to a fixed listing. That step
would have published an estimate resting on money nobody paid - the one
failure this change exists to prevent - and the real listing is a single call
behind the seam the tests above already use.

- [x] 2.1 The listing: `StripeClient` aimed by `base_addresses`, charges over
      the window, paged to the end, the vendor's errors raised as
      `RevenueUnavailable`.
- [x] 2.2 The Stripe key and base address in `argus_core.config`,
      `.env.example` and `docker-compose.yml`, the key absent by default.
- [x] 2.3 `orchestrator/postmortem.py` wires the adapter into the `Revenue`
      port in place of the function returning `None`.
- [x] 2.4 Test: no credential configured means the source reports it could not
      answer, and no request is sent.
- [x] 2.5 Test: a revenue source that cannot be read still leaves the estimate
      absent with its reason. Already covered - the agent's
      `test_a_revenue_source_that_cannot_be_read_estimates_nothing_rather_than_zero`
      for the document, and the adapter's own tests for the translation.

## 3. The shop pays

- [x] 3.1 A Stripe-shaped charges endpoint on the Target Service, over the
      checkouts it already simulates: a window filter, paging, and the fields
      the SDK's `Charge` carries. Written code-first, per the demo app's rule.
- [x] 3.2 A minority of those charges taken in a second currency, so that
      conversion is exercised by something other than a unit test.
- [x] 3.3 The endpoint's own regression tests, in the demo repo, after the code.
- [x] 3.4 Test: the e2e stack produces a postmortem carrying a loss estimate
      rather than an absence.

## 4. Two currencies

- [x] 4.1 Test: a window paid in two currencies answers with both amounts,
      each named, and no total across them.
- [x] 4.2 `Revenue` in `agent_postmortem.sources` answers an amount per
      currency rather than a bare `Decimal`, and the port's own tests follow.

## 5. The rate

- [x] 5.1 Propose the test: a figure in a second currency converted at a stated
      rate, with the rate and its date recorded in the assumptions.
- [x] 5.2 `modules/exchange_rate_source/`, scaffolded per the `new-module`
      skill: one call to Frankfurter, the whole table for a base currency.
- [x] 5.3 The rate table in `argus_core.schema` - `CREATE TABLE` only, one row
      per currency per date.
- [x] 5.4 Fetch on first use, keyed by date; a second read the same day makes
      no second request.
- [x] 5.5 Test: the provider unreachable and an earlier day's rates held - the
      earlier rates are used and their date is what gets disclosed.
- [x] 5.6 Test: the provider unreachable and nothing held - no conversion, and
      the reason recorded.
- [x] 5.7 The rate provider's base URL in `argus_core.config`, `.env.example`
      and `docker-compose.yml`.

## 6. One figure

- [x] 6.1 The reporting currency setting, defaulting to USD, in
      `argus_core.config` and `.env.example`.
- [x] 6.2 `estimate.py` reduces the per-currency amounts to the reporting
      currency, and the revenue rate is computed from the reduced figure.
- [x] 6.3 Test: takings in a currency the rate source publishes nothing for are
      excluded, and the exclusion is recorded rather than the estimate lost.
- [x] 6.4 The assumptions carry the rate, its date, and any exclusion; the
      estimate names its currency.
- [x] 6.5 Test: the answer checker still rejects a currency amount in the
      executive summary that is not Argus's own figure, now that the figure
      exists.
- [x] 6.6 The e2e of 3.4 tightened: the estimate is in the reporting currency
      and converted from what the shop actually took.

## 7. Closing out

- [x] 7.1 `lint`, `typecheck`, `test_module` for each touched module, then
      `test_all`.
- [x] 7.2 `integration`, and `e2e_replay` in the background.
- [x] 7.3 Spec §21.3 updated to say the estimate names its currency and
      discloses the rate it was converted at, per the `spec-doc-style` skill.
- [ ] 7.4 One-line commit, approved before it is made. The Target Service's
      change is its own commit in its own repo.

## 8. The loss is measured, not modelled

The estimate stops being a formula with a judgement in it. What the shop takes
in a calm hour before the onset, normalised to the length of the incident, less
what it actually took during the incident, is the loss - both terms money the
payment provider reported. The error-rate delta was a proxy for exactly that
number and the impact weight was a guess at it; neither survives a measurement.

- [x] 8.1 The onset reaches the document. It is already measured and published
      as `OnsetDetected`, so `gather_evidence` reads it and `IncidentEvidence`
      carries it. The alert time is when Argus was told, and the minutes before
      it are the ones that poisoned the baseline.
- [x] 8.2 Test: a shop that took less during the incident than its calm hour
      predicts has lost the difference, normalised to the incident's length.
- [x] 8.3 `estimate.py` computes that, and the revenue port is asked twice -
      once for the baseline window, once for the incident itself.
- [x] 8.4 Test: a window in which the shop took more than the baseline predicted
      is no loss rather than a negative one.
- [x] 8.5 The impact weight leaves the prompt, the submit tool, the required
      fields, the checker and the assumptions. A measured figure multiplied by
      a judgement is no longer measured.
- [x] 8.6 Test: the document still refuses a summary naming a figure Argus did
      not compute, with the weight gone.
- [x] 8.7 The e2e of 3.4 and 6.6 holds: the estimate is positive, in the
      reporting currency, and discloses the rate it was converted at.
