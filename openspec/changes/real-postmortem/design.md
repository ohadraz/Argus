## Context

`agent_postmortem` is 20 lines returning fixed strings, called from
`graph.py` on the terminal transition. Everything it needs about the incident
is already persisted: the event stream, the ranked candidates with their
verdicts, the actions and whether they were reverted, and one replay-log row
per model completion and tool call.

Two figures have no source. `engineer_minutes` needs to know when a person
engaged, and nothing times human involvement - Slack is where the talking
happens, not where a state change is recorded. `customer_loss_estimate_usd`
needs a revenue rate, and no channel in the read tier knows about money.

The order was originally the reverse of this: build the two sources, then the
agent. Taking the agent first means the ports are defined by what the document
needs, and each adapter afterwards satisfies a seam that already exists rather
than one guessed in advance.

## Goals / Non-Goals

**Goals:**

- Every figure in the postmortem row is either measured from stored data or an
  estimate whose assumptions are stated in the document itself.
- The model contributes prose and one disclosed judgment; it never supplies a
  number that is presented as measured.
- The agent terminates on every path, including a model that answers badly
  twice.
- The two missing sources are ports with fakes, shaped by the agent's needs.

**Non-Goals:**

- Real revenue and responder adapters. Each is its own change.
- The Chroma memory write of spec §7.6 - its only consumer, the Investigator's
  retrieval of similar past incidents, does not exist.
- Sending anything anywhere. Distribution to `postmortem_recipients` and
  `exec_summary_recipients` is the Communicator's.
- Changing the postmortem page, its view or its repository.

## Decisions

**LLM-backed, not agentic.** No tool loop. By the time this runs, the evidence
is assembled and there is nothing left to go and fetch - except one metrics
re-read, below, which is a fixed call rather than a decision the model makes.
One `converse` call, and a second only when the checklist fails.

Alternative considered: give the Postmortem the Investigator's loop and let it
pull what it wants. Rejected - it would re-open questions the investigation
already answered, at the cost of a second investigation, on a path where
nothing is waiting for new evidence.

**The model supplies prose and `impact_weight`, nothing else.** Duration,
`tokens_spent`, `engineer_minutes`, responder count and the error-rate delta
are computed. `impact_weight` is the exception because it is not a measurement
in the first place: an account page failing costs no revenue and a checkout
failing costs all of it, and nothing declares which routes carry money. It is
written into the document as a stated assumption alongside the estimate.

Alternative considered: a configured route→weight table. Rejected for now - it
invents a taxonomy before anything knows what it needs, and a table maintained
by nobody is worse than a judgment that says it is one.

**The estimate is a revenue rate, not a user count.** Spec §21.3's
`affected_users × avg_revenue_per_user × duration × impact_weight` becomes:

```
loss ≈ baseline_revenue_per_hour × duration_hours × error_rate_delta × impact_weight
```

Both dropped terms are unobtainable and the substitution is exact where they
were guesses: revenue per window is a fact a payment provider can answer, while
revenue per *user* is not - Stripe's `customer` is null on guest checkouts.
Revenue-per-hour also already reflects real conversion, so the estimate stops
assuming every affected user would have bought.

**The metrics window is re-read, wider than the investigation's.** The
Investigator stops reading once it has a cause, so the minutes between the
mitigation landing and the incident ending were never fetched - and that is
precisely the recovery the duration covers. The logs are not re-read: their
only job here is to say which area broke, and the stored window already does.

**`incident.ended_at`, written at the transition that ends it.** Duration is
reported, so it should be recorded rather than inferred from the last row that
happened to be written. Derived duration would silently change whenever
something new is logged late.

**Two ports, defined in `agent_postmortem`, not in `argus_core`.** Nothing else
consumes them, and a shared abstraction with one consumer is a guess about the
second. When the adapters land, the typed client functions satisfy the
Protocols and the ports move only if a second consumer appears.

Both are asked a question the agent has, not one a provider offers:
*revenue taken between two times*, and *who responded to this incident and
when*. Neither mentions Stripe or PagerDuty.

**Unavailability is not zero.** A port that cannot answer leaves its field
null and says so in the assumptions. A revenue source that is down must never
become "$0 lost", which reads as a measured absence of impact.

**A figure in the prose that is not Argus's own sends the answer back.** The
document's columns are safe from the model by construction, but the executive
summary is published as written - so a model that says "approximately $1.2M"
about an incident Argus priced at $336 puts an invented number in front of the
one reader least able to check it. The summary is therefore scanned for
currency amounts, and any that is not within a small tolerance of the computed
estimate - or any at all, when there is no estimate - is treated exactly like a
missing field: one further call, naming the offence, then whatever comes back.

Alternatives considered: asking the model not to (what the tool description
already does, and not enforcement); forbidding figures in prose entirely
(a summary that cannot say "about $340" reads oddly for the audience it is
for); and writing the money sentence ourselves around the model's narrative
(strongest, and the least natural prose). Validation catches the failure and
costs a call only on the runs where it happens.

**The checklist is the agent's own output, checked once.** Required fields
missing → one more `converse` naming them → write whatever came back. There is
no third attempt: an incident that is over is not improved by an agent that
will not stop, and `checklist_complete` already exists to record that the
document is partial.

## Risks / Trade-offs

- **In production the two fields stay null until their adapters land.** →
  Accepted deliberately: they are null today too, and the arithmetic that
  consumes them is fully exercised against fakes with known numbers, so the
  adapters land into tested code rather than untested code.
- **`impact_weight` is a judgment sitting beside two measurements.** → It is
  labelled as an assumption in the document, and §21.3 grades postmortems on
  disclosure rather than numeric accuracy.
- **A model that returns prose contradicting the computed figures.** → The
  figures are written from the computation, never parsed back out of the prose;
  the worst case is a document whose wording is vaguer than its numbers.
- **One more model call per incident.** → It runs once per incident on a path
  with nothing waiting on it, and the replay log prices it like any other.

## Open Questions

- One `converse` call produces both bodies, as separate fields of one
  structured answer - so telling them apart is never a matter of splitting
  prose. The risk is one framing for two audiences: an executive summary
  written in the same breath as an engineering postmortem tends to inherit its
  vocabulary. If it reads too technical, the first remedy is the prompt and
  only then a second call, which costs twice and is not worth paying before a
  real output has been read.
