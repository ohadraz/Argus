## Context

The `Engagement` port is already defined in `agent_postmortem.sources`: a
callable taking an incident id and answering `EngagementAnswer | None`, where
`None` means nobody could say. `orchestrator/postmortem.py` satisfies it with
`_no_engagement_source`, a function that returns `None` unconditionally, so
`engineer_minutes` and the responder count are absent from every postmortem
Argus has published.

The revenue work established the shape this follows: a module per external
party, the vendor's own SDK inside it, a base URL in configuration, and a
stand-in endpoint on the Target Service so the demo exercises the same code a
real account would. PagerDuty fits it - `pagerduty` is first-party, current
(it replaced `pdpyras`), built on httpx, and takes a `base_url` keyword.

Argus already knows when the incident began and ended from its own records.
What it cannot know is when a person picked it up, or who, and that is exactly
what an on-call provider holds.

## Goals / Non-Goals

**Goals:**
- The `Engagement` port answered by a real provider, aimed by configuration.
- The minutes reported are the minutes someone was actually engaged.
- The responders' job titles carried on the answer, read where the provider
  publishes them.
- An incident nobody acknowledged distinguishable from a provider that could
  not be read.

**Non-Goals:**
- Pricing the minutes. No rate, no currency, no HRIS. `engineer_minutes` stays
  a count of minutes, and §21.3's refusal to convert it stands until a change
  argues otherwise.
- Reading anything from PagerDuty but this incident's acknowledgements and the
  users behind them - no schedules, no escalation policies, no services.
- Writing to PagerDuty. The adapter is read-only, and the write tier is not
  involved.
- Matching a PagerDuty incident to an Argus incident by anything cleverer than
  the identifier Argus already holds.

## Decisions

**The port answers minutes, a count, and titles - not a list of people.**
`EngagementAnswer` gains the titles that responded, not names or emails. A
postmortem naming individuals is a document about people rather than about an
incident, and the identity is not what any consumer needs: the next change
needs a title to price, and a reader needs to know a senior engineer spent two
hours. Alternative considered: carrying the responders themselves and letting
the document decide what to show. Rejected - it puts personal data in a
document that gets emailed, to serve a decision nobody has asked for.

**Engagement is person-minutes.** Each responder's own acknowledgement to the
incident's end, summed. Two mistakes are ruled out by the same measure: the
minutes before anyone acknowledged belong to nobody, so counting from the
incident's start reports attention nobody paid; and two people on an incident
spent two people's time, so a single wall-clock span reports half of what the
response cost. It is also the shape a rate multiplies, whenever something comes
to price it. A responder's end is the incident's, since the provider publishes
an acknowledgement instant and no release instant - the one approximation here,
and it is stated rather than hidden.

**The user lookup is a second request, not an `include`.** PagerDuty's list
endpoint accepts `include[]=acknowledgers`, but the job title lives on the user
and the demo's stand-in is simpler for having two plain endpoints than one with
a conditional expansion. One request per distinct acknowledger, and an incident
has one or two.

**A responder whose user cannot be read still counts.** The count and the
minutes come from the acknowledgement itself; a title that could not be fetched
is absent from the titles rather than fatal to the answer. The alternative -
failing the whole answer because one lookup failed - turns a partial reading
into no reading, which is the failure mode the ports exist to avoid.

**`None` is for a provider that could not be read.** An incident with no
acknowledgements answers zero minutes, zero responders, no titles - a real
measurement of an incident nobody attended. Only an unreachable or
unauthenticated provider answers `None`. This is the distinction
`postmortem-evidence-sources` already requires of every source.

**The credential is one API key.** PagerDuty's REST API takes a token in an
`Authorization: Token token=...` header, which the SDK builds from the key it
is constructed with. No OAuth flow, no token endpoint - the same single string
in settings that `stripe_api_key` is, absent by default.

**The demo's endpoints answer from the scenario it already seeds.** The Target
Service knows when its own incident started; an authored acknowledgement a few
minutes later, by an authored user with a job title, is what makes the demo's
postmortem report a real span. It is a fixture, and it is allowed to be simple.

## Risks / Trade-offs

**The SDK is httpx-based and the stand-in must satisfy it** → The same risk
Stripe carried and the same mitigation: the endpoint answers PagerDuty's own
envelope, and the e2e stack is what proves the SDK is satisfied by it. A unit
test asserting a hand-written listing proves only the fake.

**PagerDuty's incident id is not Argus's** → The demo's endpoint accepts
Argus's incident id as the key, which a real deployment would not. The port
takes an incident id and the adapter is free to interpret it; a real account
would need a mapping, and that mapping is out of scope here rather than
pretended at.

**An acknowledged-then-reassigned incident overstates one person's engagement**
→ Accepted. The span is what the provider can support, and the document says it
is the acknowledged span rather than any individual's timesheet.

**Titles are free text** → PagerDuty's `job_title` is whatever an admin typed.
Nothing here parses it, and the change that prices minutes will have to match
it against an HRIS rather than assume a taxonomy. Naming that now stops this
change from inventing one.
