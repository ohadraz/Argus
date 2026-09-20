"""Everything about an incident that is a number, read before anything is asked
of a model.

One function, because the figures are not independent: the loss is a
subtraction between two windows, both windows are dated from the same instant,
and the currency the answer is published in is a property of the table that
converted them. Measured separately they could disagree with each other, and a
document whose duration and whose loss describe different incidents is worse
than one carrying neither.

Which is why recovery is found here, once, and every window below is bounded
by what it says. It is a property of the incident like the onset beside it,
and it is a fact about the service rather than about Argus: the walk stays
open through the verification wait, the code-fix attempt and the write-up, so
a figure measured to the close describes a service that was mostly fine. A
duration measured to recovery beside a rise measured to the close would be the
two-incidents-on-one-page failure this function exists to prevent.

Two clocks leave here, named as two. How long the service was broken is a fact
about the fault; how long Argus held the incident is a fact about the
response, and the second never stands in for the first.

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

from argus_core import parse_iso
from argus_core.anomaly import AnomalyThresholds, find_recovery
from argus_core.models import MetricBucket
from pydantic import BaseModel

from agent_postmortem.estimate import (
    BASELINE_WINDOW,
    BASELINE_WINDOW_HOURS,
    ErrorRates,
    duration_in_hours,
    error_rates_over,
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

    # How long the service was broken - onset to recovery, both read off the
    # metrics. Not how long the walk stayed open: that clock runs through the
    # verification wait, the code-fix attempt and the write-up, and an impact
    # figure measured over it describes a service that was mostly fine.
    duration_in_hours: float
    # The minute the service came back, and `None` where it had not come back
    # by the last minute of metrics read. `None` is an answer rather than a
    # missing one: every figure above is then a lower bound, and whatever
    # renders them has to say so rather than quietly presenting a bound read
    # as a measurement.
    recovered_at: datetime | None
    # How long Argus held the incident - the alert to the close. The one
    # figure on the page measuring the responder rather than the fault, which
    # is why it is kept and why it never stands in for the duration above. One
    # field answering both questions is the defect all of this came from.
    time_to_close_in_hours: float
    # What the error rate did, at the three levels worth reporting, or `None`
    # where the metrics could not be read. Nothing rests on it: it is what the
    # model is told about what happened, and no figure is computed from it.
    error_rates: ErrorRates | None
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
    # Read once, and every window below bounded by what it says. Computed here
    # rather than per figure because it is a property of the incident, like
    # the onset beside it: a duration measured to recovery and a rise measured
    # to the close would be two incidents on one page, which is the failure
    # this function exists to prevent.
    metrics = sources.metrics(began - BASELINE_WINDOW, evidence.ended_at)
    recovered_at = _when_the_service_came_back(metrics, sources.thresholds)
    # The read has to end somewhere even when nothing says the service came
    # back, so it ends at the close - the boundary a query needs. What must
    # not happen is the substitution going unmarked, and `recovered_at` is the
    # mark: absent, and every figure below is a lower bound.
    measured_until = recovered_at or evidence.ended_at
    duration = duration_in_hours(began, measured_until)
    rates = sources.rates()
    taken_before = sources.revenue(began - BASELINE_WINDOW, began)
    taken_during = sources.revenue(began, measured_until)
    baseline_revenue, left_out = _as_one_figure(
        taken_before, rates, sources.reporting_currency)
    revenue_during, _ = _as_one_figure(
        taken_during, rates, sources.reporting_currency)
    loss = (_loss(baseline_revenue, revenue_during, duration)
            if evidence.onset_at is not None else None)
    engaged = sources.engagement(evidence.incident_id)
    bands = sources.bands()

    return Measurements(
        duration_in_hours=duration,
        recovered_at=recovered_at,
        # From the alert rather than from the onset. The minutes before the
        # alert are the fault's, not the responder's - nobody had been told
        # yet - and charging them to the response would price Argus for a
        # delay in somebody else's monitoring.
        time_to_close_in_hours=duration_in_hours(
            evidence.started_at, evidence.ended_at),
        # The recovery itself, not the bound the read fell back to. Where the
        # service never came back there is no first well minute to stop at,
        # and every minute read is part of the incident.
        error_rates=error_rates_over(metrics, began, recovered_at),
        loss=loss,
        currency=sources.reporting_currency if loss is not None else None,
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
                   rates: RateTable | None,
                   reporting_currency: str) -> tuple[Decimal | None, list[str]]:
    """What the service took, stated in the one currency the document reports
    in, and whatever could not be stated there at all.

    A quiet window took nothing, and nothing is a measurement: an empty mapping
    is zero rather than an unanswered question. Only an unread provider leaves
    no figure, because only it leaves no takings to state.

    A table nobody could read is a table with no rates in it, which the
    arithmetic already knows how to answer: whatever needed no conversion is in
    the figure, and every currency that did is named as missing from it. The
    currency this is reported in comes from the configuration either way - it is
    what the table was asked to quote against - so it is not a guess, and losing
    the money that needed no rate at all would be the worse answer.
    """
    if taken is None:
        return None, []

    if rates is None:
        return _only_the_money_needing_no_rate(taken, reporting_currency)

    return in_the_reporting_currency(taken, rates)


def _only_the_money_needing_no_rate(
        taken: Mapping[str, Decimal],
        reporting_currency: str) -> tuple[Decimal, list[str]]:
    """The takings already in the reporting currency, and every other currency.

    The same shape `in_the_reporting_currency` returns for a currency the table
    does not cover, because it is the same finding: money that was taken, and
    no rate to state it with.
    """
    return (
        taken.get(reporting_currency, Decimal(0)),
        [currency for currency in taken if currency != reporting_currency]
    )


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


def _when_the_service_came_back(metrics: list[MetricBucket],
                                thresholds: AnomalyThresholds) -> datetime | None:
    """The instant the incident ended, or `None` where the metrics never said.

    Read off the series by the same rule Mitigation asks recovery by, so the
    two cannot come to disagree about one window - the postmortem must not
    date recovery at a minute Mitigation refused to confirm a mitigation on.
    Never from the moment an action was applied, and never from the verdict
    that confirmed it: those say when Argus acted, and a service does not
    recover because somebody acted on it.

    As an instant rather than the `bucket_id` the detector answers with,
    because everything here subtracts it from another instant.
    """
    recovered = find_recovery(metrics, thresholds)

    return parse_iso(recovered) if recovered is not None else None


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
