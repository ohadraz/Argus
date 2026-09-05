## Context

`write_postmortem` already receives an `Engagement` source answering how many
people responded, what their titles were, and how many person-minutes they
spent between them - measured from each responder's own acknowledgement rather
than from the incident's length. PagerDuty supplies that. It carries nothing
about pay, and no on-call provider does.

BambooHR's Pay Grades & Bands API answers the missing half in one call.
`GET /api/v1/pay-grades-and-bands/job-titles` returns every compensation level
with its band - `min`, `mid`, `max`, `currencyCode` - and the job titles
assigned to that level. It takes no parameters and cannot be filtered, so the
whole structure is fetched and inverted into title -> band locally.

## Goals / Non-Goals

**Goals:**
- An incident's response has a cost, in the currency the loss estimate is in.
- The figure says how wide it is, because a band is a range and a midpoint
  alone implies a precision the source does not have.
- A title nobody priced is visible as unpriced.

**Non-Goals:**
- Anyone's actual salary. The employee compensation endpoints are not read, and
  no deployment of this needs access to them.
- A total combining customer loss and response cost. Worth having, worth having
  once both are here.
- Overtime, on-call premiums, or the difference between a Tuesday afternoon and
  a Sunday night. A band is what the title is worth; when it was worked is a
  refinement with no source behind it here.

## Decisions

**Bands, not salaries.** The band is a property of a level that titles are
assigned to, so pricing by it needs no identity at any point - the postmortem
keeps recording titles and never names, and Argus's HR credential never has to
be able to read a person's pay. Averaging individual salaries by title would
produce a similar number and require exactly the access this avoids.

**Midpoint headline, range beside it.** The midpoint is what makes the figure
comparable with the loss estimate; the range is what stops it being read as
measured to the dollar. Reporting only the range gives an exec summary two
numbers where it needs one; reporting only the midpoint hides that the same
incident costs a third more at the top of the band.

**One fetch, inverted locally.** The endpoint takes no parameters and answers
levels-with-titles. Every other shape - a lookup per title, a level resolved
first - would be this call plus arithmetic, done more times.

**A title outside the bands makes the whole figure absent.** The same rule the
loss estimate already follows: a cost covering two responders out of three is
not a smaller cost, it is a wrong one. The document names the title it could
not price, so the gap reads as a band that has not been configured rather than
as a bug.

**The working year is configuration, defaulting to 2080.** Forty hours by
fifty-two weeks is the convention an annual band is quoted against, and it is
the divisor that turns one into a per-minute rate. Configuration because it is
a fact about an organisation's working norms, not about this code, and stated
on the document because a figure derived from a divisor is only reproducible
with the divisor.

**A source module, like every other figure's.** `revenue_source`,
`exchange_rate_source` and `oncall_source` each own one external party and
answer one question. The HR source is the fourth, reached by base URL, with the
same double-in-dev arrangement.

**The demo seeds the bands.** The Target Environment already stands in for the
shop's Stripe, Argo CD and PagerDuty. Its HR data is the same kind of fixture,
and a scenario that pages a Senior SRE needs a band for one.

## Risks / Trade-offs

- **A title PagerDuty reports and the bands do not carry** (a contractor, a
  title renamed in one system) → the figure is absent and names it, which is a
  legible mismatch rather than a silent under-count.
- **Bands in a currency the incident is not reported in** → through the same
  rate table the takings already use; absent where the rate is.
- **A midpoint read as precision** → the range is published beside it, and the
  assumptions say it is a band.
- **The HR source down** → absent with its reason, as an unreadable revenue
  source already is. It never fails the walk: the incident is over by then.
