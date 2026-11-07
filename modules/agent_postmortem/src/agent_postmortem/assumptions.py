"""What the document admits to having assumed rather than measured.

Every figure in a postmortem is a measurement, but a measurement is only as
honest as the steps between the source and the page: a rate applied, a
currency left out, a shortfall within what the shop varies by. Each of those is
stated here in the reader's own terms, so a number can be argued with rather
than trusted.

An absence gets a line too. A figure that is missing and a figure that is zero
look the same on a page unless the document says which one it is, and each
absence has its own sentence - "nobody responded" and "the on-call system could
not be reached" are different findings that would otherwise leave the same
blank.

Nothing here reads a source. Everything was read while the incident was being
measured, so a disclosure describes the same read that produced the figure it
sits beside.

The wording is here too, as a constant per disclosure. The document and anything
reading it back have to agree on the phrasing, and two spellings would leave a
disclosed assumption looking undisclosed - so the sentence and the code that
decides to say it are kept in one file rather than one apiece.
"""

from __future__ import annotations

from datetime import timedelta

from argus_core.models import said_as_money

from agent_postmortem.estimate import Unmeasured, weeks_back_for
from agent_postmortem.measuring import Measurements
from agent_postmortem.prompting import SubmittedPostmortem
from agent_postmortem.sources import EngagementAnswer, NotPaged

# How a conversion announces itself in the assumptions. A constant rather than
# a phrase written at each end, because the document and anything reading it
# have to agree on the wording, and two spellings would leave a disclosed
# assumption looking undisclosed. Money taken abroad
# reaches the estimate through a rate, and a figure converted at a rate nobody
# can see is a figure nobody can check.
EXCHANGE_RATE_ASSUMPTION_LABEL = "Exchange rate"

# How money left out of the figure announces itself. A shop can be paid in a
# currency the rate source prices nothing for, and the estimate then covers
# some of what was taken rather than all of it - which is a real answer, but
# only while the document says which part is missing.
EXCLUDED_CURRENCY_ASSUMPTION_LABEL = "Excluded currency"

# Why that currency was left out. Two reasons rather than one, because they
# send a reader to two different places: a provider that publishes no rate for
# a currency is a fact about the currency, and a table nobody could fetch is a
# fact about the read. Told the first when the second happened, a reader goes
# hunting for a currency the provider covers perfectly well.
NO_RATE_PUBLISHED_REASON = "no rate was published for it"
RATES_UNAVAILABLE_REASON = "the exchange rate source could not be read"

# How a zero that is the shop's own variation announces itself. Takings that
# fell short by less than two calm stretches differ by on their own are no loss
# anyone can tell from an ordinary day - and a zero beside an incident that
# plainly took less reads as a figure nobody computed unless both amounts are
# said.
NORMAL_VARIATION_ASSUMPTION_LABEL = "Normal variation"

# Said when a figure is missing because nobody could answer, so that the gap
# reads as an unanswered question rather than as a measurement of nothing.
#
# Only the takings can cost the document its estimate. A rate table that never
# arrived leaves the money that needed no rate, which is a partial figure and
# not an absent one - so it is disclosed a currency at a time, above.
REVENUE_UNAVAILABLE_ASSUMPTION = "No loss estimate: the revenue source could not be read"
ONSET_UNKNOWN_ASSUMPTION = (
    "No loss estimate: no minute departed from the baseline, so there is no "
    "measured incident to attribute a loss to"
)
# The same absence where no minute of the metrics could be read at all: "no
# minute departed" says of a window nobody saw that it was looked at and calm.
NOTHING_READ_ASSUMPTION = (
    "No loss estimate: no minute of the service's metrics could be read, so there "
    "is no measured incident to attribute a loss to"
)
ENGAGEMENT_UNAVAILABLE_ASSUMPTION = (
    "No engineer minutes: no source could say when a person engaged"
)
# Said when nobody was paged at all, which is neither of the absences above or
# below: the on-call source answered, and no incident of its own was this one.
NOT_PAGED_ASSUMPTION = (
    "No engineer minutes: no on-call incident was linked to this one, so nobody "
    "was paged to respond"
)
# How a response shared with other incidents announces itself. One on-call
# incident can be about several of Argus's, and its minutes are then reported
# in full on each - not split, because nothing says how the people on it divided
# their attention - so a reader adding the documents up counts them twice
# unless each says so.
SHARED_PAGE_ASSUMPTION_LABEL = "Shared page"


def assumptions_of(answer: SubmittedPostmortem,
                   measured: Measurements,
                   working_hours_a_year: float) -> list[str]:
    """Everything the document assumed, in the order a reader meets it.

    The conversions come first - they stand between the money the provider
    reported and the figure published, with the comparison against how much
    the shop varies on its own - then a response shared with other incidents,
    then whatever the model says it assumed in its prose, then the absences,
    each saying which question went unanswered.

    Nothing of how the response was priced: the document is read by the people
    it would price, and that is kept apart, in `response_cost_basis`.
    """
    assumptions: list[str] = []

    if measured.onset_at is None:
        assumptions.append(NOTHING_READ_ASSUMPTION
                           if measured.error_rates_unmeasured is Unmeasured.NOTHING_READ
                           else ONSET_UNKNOWN_ASSUMPTION)

    assumptions.extend(_rates_applied(measured))
    assumptions.extend(_currencies_left_out_of(measured))
    assumptions.extend(_within_the_shop_s_variation(measured))

    assumptions.extend(_a_response_shared_with_others(measured))

    assumptions.extend(answer.assumptions)

    # The takings rather than the figure they became: a figure is also absent
    # where the money was read and no rate could be, and that is a partial
    # estimate disclosed a currency at a time rather than an unread provider.
    # Only where there was an onset to count a loss from: without one the
    # takings are never asked for, which the line above says.
    if measured.onset_at is not None and measured.baseline_takings is None:
        assumptions.append(REVENUE_UNAVAILABLE_ASSUMPTION)
    if measured.engaged is None:
        assumptions.append(ENGAGEMENT_UNAVAILABLE_ASSUMPTION)
    if isinstance(measured.engaged, NotPaged):
        assumptions.append(NOT_PAGED_ASSUMPTION)

    return assumptions


def _within_the_shop_s_variation(measured: Measurements) -> list[str]:
    """The line saying a shortfall was the shop's own variation, where it was.

    Only where something fell short and the figure is zero for it: a loss
    published in full needs no apology for its baseline, and a shop that took
    more has no shortfall to explain.
    """
    shortfall, variation = measured.shortfall, measured.variation

    if measured.loss != 0 or shortfall is None or variation is None or shortfall <= 0:
        return []

    weeks = weeks_back_for(timedelta(hours=measured.duration_in_hours)) // timedelta(weeks=1)
    earlier = f"{weeks} week{'s' if weeks != 1 else ''} earlier"

    return [f"{NORMAL_VARIATION_ASSUMPTION_LABEL}: takings fell "
            f"{said_as_money(shortfall, measured.currency)} short of the same hours "
            f"{earlier}, no more than the {said_as_money(variation, measured.currency)} "
            f"those hours differ by from the same hours {earlier} again, so no loss is "
            f"reported"]


def _currencies_left_out_of(measured: Measurements) -> list[str]:
    """Every currency missing from the figure, each with why it is missing.

    The reason is read from whether a table arrived at all rather than from the
    currency, because that is what distinguishes the two: with a table in hand,
    a currency is left out because the provider prices nothing for it; with no
    table, every currency is left out for the same reason, and it is not the
    currency's.

    Only where there is a figure for them to be missing from.
    """
    if measured.loss is None:
        return []

    reason = (RATES_UNAVAILABLE_REASON if measured.rates is None
              else NO_RATE_PUBLISHED_REASON)

    return [
        f"{EXCLUDED_CURRENCY_ASSUMPTION_LABEL}: takings in {currency} are not in "
        f"the figure, because {reason}"
        for currency in measured.currencies_left_out
    ]


def _a_response_shared_with_others(measured: Measurements) -> list[str]:
    """The line saying the response was also other incidents', where it was."""
    engaged = measured.engaged
    if not isinstance(engaged, EngagementAnswer) or engaged.shared_with == 0:
        return []

    others = engaged.shared_with

    return [f"{SHARED_PAGE_ASSUMPTION_LABEL}: the on-call incident this one was paged "
            f"under was also about {others} other incident{'s' if others != 1 else ''}, "
            f"so the engineer minutes are its whole response rather than this "
            f"incident's share"]


def _rates_applied(measured: Measurements) -> list[str]:
    """Every conversion that went into the figure, one line each.

    Only the currencies actually taken, so a document about a service trading
    in dollars does not recite thirty rates it never used. A window needing no
    conversion says nothing, which is correct: there is no assumption to
    disclose. And only where a loss was computed: takings read with no figure
    made of them were converted into nothing.
    """
    taken, rates = measured.baseline_takings, measured.rates
    if taken is None or rates is None or measured.loss is None:
        return []

    return [
        f"{EXCHANGE_RATE_ASSUMPTION_LABEL}: {currency.upper()} converted at "
        f"{rates.per_unit[currency]} per {rates.base.upper()}, published "
        f"{rates.on.isoformat()}"
        for currency in taken
        if currency != rates.base and currency in rates.per_unit
    ]
