"""What an incident cost, in money (spec §21.3).

The ports the money is read through and the settings read with them, in
`sources`; what the outage cost the business, read off the takings and
converted at the day's rates, in `loss`; what the response cost, priced at the
bands published for each title, in `responder_cost`; and the steps that price
rests on, said one line each, in `response_cost_basis`.
"""

from __future__ import annotations

from incident_cost.loss import LossEstimate, estimate_loss, weeks_back_for
from incident_cost.responder_cost import ResponderCost, responder_cost
from incident_cost.response_cost_basis import (
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
    response_cost_basis,
)
from incident_cost.sources import (
    EngagedResponder,
    MoneySources,
    PayBand,
    PayBands,
    Rates,
    RateTable,
    Revenue,
)

__all__ = [
    "PAY_BANDS_UNAVAILABLE_ASSUMPTION",
    "PAY_BAND_ASSUMPTION_LABEL",
    "UNPRICED_TITLE_ASSUMPTION_LABEL",
    "WORKING_YEAR_ASSUMPTION_LABEL",
    "EngagedResponder",
    "LossEstimate",
    "MoneySources",
    "PayBand",
    "PayBands",
    "RateTable",
    "Rates",
    "ResponderCost",
    "Revenue",
    "estimate_loss",
    "response_cost_basis",
    "responder_cost",
    "weeks_back_for"
]
