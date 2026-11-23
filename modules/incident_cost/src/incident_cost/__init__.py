"""What an incident cost, in money (spec §21.3).

The ports the money is read through and the settings read with them, in
`sources`; what the outage cost the business, read off the takings and
converted at the day's rates, in `loss`; each responding title's band converted
into the reporting currency, in `bands_reported`; what the response cost, title
by title at those bands, in `responder_cost`; the steps that price rests on,
said one line each, in `response_cost_basis`; and how a conversion is said,
for both figures, in `conversion_said`.
"""

from __future__ import annotations

from incident_cost.bands_reported import BandsReported, bands_reported
from incident_cost.conversion_said import (
    EXCHANGE_RATE_ASSUMPTION_LABEL,
    NO_RATE_PUBLISHED_REASON,
    RATES_UNAVAILABLE_REASON,
    a_conversion_said,
)
from incident_cost.loss import LossEstimate, estimate_loss, weeks_back_for
from incident_cost.responder_cost import (
    PricedMinutes,
    ResponderCost,
    TitleShare,
    responder_cost,
)
from incident_cost.response_cost_basis import (
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
    response_cost_basis,
)
from incident_cost.sources import (
    MoneySources,
    PayBand,
    PayBands,
    Rates,
    RateTable,
    Revenue,
)

__all__ = [
    "EXCHANGE_RATE_ASSUMPTION_LABEL",
    "NO_RATE_PUBLISHED_REASON",
    "PAY_BANDS_UNAVAILABLE_ASSUMPTION",
    "PAY_BAND_ASSUMPTION_LABEL",
    "RATES_UNAVAILABLE_REASON",
    "UNPRICED_TITLE_ASSUMPTION_LABEL",
    "WORKING_YEAR_ASSUMPTION_LABEL",
    "BandsReported",
    "LossEstimate",
    "MoneySources",
    "PayBand",
    "PayBands",
    "PricedMinutes",
    "RateTable",
    "Rates",
    "ResponderCost",
    "Revenue",
    "TitleShare",
    "a_conversion_said",
    "bands_reported",
    "estimate_loss",
    "response_cost_basis",
    "responder_cost",
    "weeks_back_for"
]
