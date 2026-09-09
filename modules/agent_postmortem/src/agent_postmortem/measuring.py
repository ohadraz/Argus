"""Everything about an incident that is a number, read before anything is asked
of a model.

One function, because the figures are not independent: the loss is a
subtraction between two windows, both windows are dated from the same instant,
and the currency the answer is published in is a property of the table that
converted them. Measured separately they could disagree with each other, and a
document whose duration and whose loss describe different incidents is worse
than one carrying neither.

Two costs, and they are the same kind of thing: what the outage cost customers,
and what the response cost the business. Both are money, both come from ports,
and both are reported side by side on the page.

Every source is asked once and what it answered is kept, because the sentences
the document discloses are written from the same reads that produced the
figures. A disclosure that went back to the rate table for the rate it is about
could name a rate the figure was not converted at.

`None` is never zero here. A source that could not be read leaves its figure
absent, and the absence carries as far as the page - an unreadable payment
provider must not become a postmortem reporting that the incident cost nothing.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel

from agent_postmortem.estimate import (
    BASELINE_WINDOW,
    BASELINE_WINDOW_HOURS,
    duration_in_hours,
    error_rate_delta,
    in_the_reporting_currency,
    loss_between,
)
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.responder_cost import ResponderCost, responder_cost
from agent_postmortem.sources import (
    EngagementAnswer,
    PayBand,
    RateTable,
    Sources,
)


class Measurements(BaseModel):
    """One incident, as far as it can be counted.

    Both the figures and what they were read from. The reads are here because
    nothing downstream may go back to a source: a document is written after the
    incident, sources move, and a second read is a second answer.

    The instant it was dated from travels too. A duration means nothing without
    it - an incident measured from its onset and one measured from its alert
    are different measurements, and only one of them can be compared with
    another incident's.
    """

    duration_in_hours: float
    # The rise above the service's own calm rate, or `None` where the metrics
    # could not be read. Nothing rests on it: it is what the model is told
    # about what happened, and no figure is computed from it.
    error_rate_delta: float | None
    loss: Decimal | None
    # What the loss is stated in, and `None` wherever there is no loss to
    # state. A currency beside an absent figure is a label for nothing.
    currency: str | None
    baseline_revenue: Decimal | None
    # What the calm window took, per currency, before any of it was converted.
    # The conversions are disclosed one line each, and a line naming a currency
    # needs the currencies rather than the total.
    baseline_takings: Mapping[str, Decimal] | None
    rates: RateTable | None
    currencies_left_out: list[str]
    onset_at: datetime | None
    engaged: EngagementAnswer | None
    cost: ResponderCost | None
    bands: Mapping[str, PayBand] | None


def measure(evidence: IncidentEvidence, sources: Sources) -> Measurements:
    """Read every source once, and count what they said.

    The incident is dated from its onset rather than from the alert. Those two
    differ by however long the alert took to fire, and counting those minutes
    as calm trade would raise the baseline using the very minutes the service
    was already failing in.
    """
    # The alert's own time where nothing measured an onset. It is the wrong
    # instant to cost an incident from - which is why no loss is published
    # without an onset, below - but it is the right one to describe it from,
    # and the duration is the model's context rather than a published figure.
    began = evidence.onset_at or evidence.started_at
    duration = duration_in_hours(began, evidence.ended_at)
    rates = sources.rates()
    taken_before = sources.revenue(began - BASELINE_WINDOW, began)
    taken_during = sources.revenue(began, evidence.ended_at)
    baseline_revenue, left_out = _as_one_figure(taken_before, rates)
    revenue_during, _ = _as_one_figure(taken_during, rates)
    loss = (_loss(baseline_revenue, revenue_during, duration)
            if evidence.onset_at is not None else None)
    engaged = sources.engagement(evidence.incident_id)
    bands = sources.bands()

    return Measurements(
        duration_in_hours=duration,
        error_rate_delta=error_rate_delta(
            sources.metrics(began - BASELINE_WINDOW, evidence.ended_at),
            began,
            evidence.ended_at),
        loss=loss,
        currency=rates.base if rates is not None and loss is not None else None,
        baseline_revenue=baseline_revenue,
        baseline_takings=taken_before,
        rates=rates,
        currencies_left_out=left_out,
        onset_at=evidence.onset_at,
        engaged=engaged,
        cost=_what_the_response_cost(engaged, bands, sources.working_hours_a_year),
        bands=bands
    )


def _as_one_figure(taken: Mapping[str, Decimal] | None,
                   rates: RateTable | None) -> tuple[Decimal | None, list[str]]:
    """What the service took, stated in the one currency the document reports
    in, and whatever could not be stated there at all.

    A quiet window took nothing, and nothing is a measurement: an empty mapping
    is zero rather than an unanswered question.

    Everything else needs the table, because the table is what says which
    currency this document is written in. Without it there is no figure to
    publish even where only one currency was taken - naming that currency would
    be a guess, and a guess about which money this is would be a worse failure
    than an absent estimate.
    """
    if taken is None or rates is None:
        return None, []

    return in_the_reporting_currency(taken, rates)


def _loss(baseline_revenue: Decimal | None,
          revenue_during: Decimal | None,
          duration: float) -> Decimal | None:
    """The estimate, or nothing when either window went unread.

    Nothing, never zero: an unreadable revenue source and a service that lost
    no money are different findings, and only one of them is a measurement.
    Both windows are needed, because a loss is the difference between them -
    one alone is half a subtraction.
    """
    if baseline_revenue is None or revenue_during is None:
        return None

    return loss_between(baseline_revenue, BASELINE_WINDOW_HOURS,
                        revenue_during, duration)


def _what_the_response_cost(engaged: EngagementAnswer | None,
                            bands: Mapping[str, PayBand] | None,
                            working_hours_a_year: float) -> ResponderCost | None:
    """What the people on the incident cost, or nothing where either half is
    missing.

    Both halves have to be there: minutes nobody could measure and bands nobody
    could read are different failures with the same consequence, and each is
    disclosed separately. The pricing itself declines any response it cannot
    price in full, so nothing here inspects the responders.
    """
    if engaged is None or bands is None:
        return None

    return responder_cost(engaged.engaged, bands, working_hours_a_year)
