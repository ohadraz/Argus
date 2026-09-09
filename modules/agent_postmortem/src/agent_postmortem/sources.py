"""The two things the Postmortem needs that Argus cannot yet answer.

Both are stated as the question the agent has, not as anything a provider
offers: *what did the service take between these two times*, and *who
responded to this incident and for how long*. Neither mentions a payment
processor or an on-call tool, and nothing above these names one either.

They are ports rather than clients because no adapter exists yet. Defining
them here rather than in `argus_core` is deliberate: nothing else consumes
them, and a shared abstraction with one consumer is a guess about the second.

`None` from either is "could not be read", never "there was nothing". The
difference is the whole point of the type: a revenue source that is down must
not become a postmortem reporting that the incident cost nothing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from argus_core.models.metrics import MetricBucket
from pydantic import BaseModel

# What the service took between two instants, per currency, or `None` if
# nobody could say. A mapping rather than an amount because a shop paid in two
# currencies has two figures and no total: producing one needs a rate, a rate
# has a date, and both are disclosures this document has to make rather than
# something a source may fold in on the way past.
type Revenue = Callable[[datetime, datetime], Mapping[str, Decimal] | None]

class RateTable(BaseModel):
    """One day's exchange rates, and the currency they are quoted against.

    `base` is what the document reports in. It lives here rather than beside
    the reporting-currency setting because a rate only means anything against
    the currency it was quoted for, and holding the two apart would let a
    figure be converted at one anchor and published as another.

    `on` is the day the rates were published, never the day the incident
    happened: rates move, an estimate is written afterwards, and a reader
    checking the arithmetic needs to know which day's number was used.
    """

    base: str
    on: date
    # How many units of each currency one unit of `base` buys.
    per_unit: Mapping[str, Decimal]


# The rates to convert with, or `None` if none could be had - neither fetched
# now nor held from an earlier day.
type Rates = Callable[[], RateTable | None]

# Pre-aggregated service metrics over a window - the same channel the
# Investigator reads, asked for a wider window than it ever had reason to.
type Metrics = Callable[[datetime, datetime], list[MetricBucket]]


class EngagedResponder(BaseModel):
    """One person's own share of the response: their minutes, and what they
    were called.

    The unit anything pricing this response has to work in. A band belongs to a
    job title, so a total that has already added a senior engineer's hour to a
    junior's cannot be priced at all - and the pair has to stay together,
    because minutes are only worth what the person holding them was.

    `job_title` is absent where the source held none. Reporting the responder
    anyway is what lets a consumer decline to price the incident rather than
    quietly price it short.
    """

    minutes: int
    job_title: str | None


class PayBand(BaseModel):
    """What one job title's time is worth a year, as an HR source states it.

    Three figures rather than one: a band is a range, and a midpoint published
    alone claims a precision the source does not have. The currency travels
    with them because a figure without one is not a figure.

    Argus's own type rather than a vendor's: the postmortem states what it
    needs, and whichever HR system answers is mapped into this by its own
    adapter - the same arrangement `RateTable` has with the rate provider.
    """

    minimum: Decimal
    midpoint: Decimal
    maximum: Decimal
    currency: str


# What every job title an HR source prices is worth, or `None` if nobody could
# say. The whole table at once, because a source publishes it that way and an
# incident prices several titles from one read.
type PayBands = Callable[[], Mapping[str, PayBand] | None]


class EngagementAnswer(BaseModel):
    """How much human attention an incident took.

    Two numbers rather than one, because they answer different questions: how
    long the incident occupied someone, and how many someones it occupied. An
    exec summary says "three engineers, two hours"; a single total says
    neither.

    `minutes` is person-minutes - each responder's own engagement, added
    together - so a source answering it has already accounted for how many
    people were on it, and nothing above may multiply by the count again.

    The titles say what those people were, and never who. A document reporting
    that a senior engineer and an SRE spent the night is one a reader can act
    on; the same document with names is about people, and it gets emailed.
    Fewer titles than responders means one could not be read, which is a gap in
    the description rather than in the measurement.

    A type of its own rather than a member of the port below: a port that is a
    plain callable can be satisfied by any function, and a function carries no
    nested class - so hanging the answer off the port would mean no test double
    could ever be one.
    """

    minutes: int
    responders: int
    titles: list[str] = []
    # The same response, held per person rather than summed. Alongside the
    # total rather than instead of it: a reader wants the total, and anything
    # pricing the response cannot use it.
    engaged: list[EngagedResponder] = []


# Who responded to one incident and for how long, or `None` if nobody could
# say.
type Engagement = Callable[[str], EngagementAnswer | None]


@dataclass(frozen=True)
class Sources:
    """Everything the Postmortem reads and does not own.

    One value rather than five arguments and a setting, because that is what
    they are: a deployment configures them once, they are the same for every
    incident it writes about, and only the incident varies from call to call.
    Passed separately they would be five chances to hand one call a different
    world from the last.

    `working_hours_a_year` belongs with them despite being a number rather than
    a port. It is what the annual bands are divided by, so it is read from the
    same configuration at the same moment as the source that publishes them,
    and a figure computed under one working year and disclosed under another is
    the failure this keeps impossible.
    """

    revenue: Revenue
    rates: Rates
    engagement: Engagement
    bands: PayBands
    metrics: Metrics
    working_hours_a_year: float
