"""The Postmortem agent (spec §7.6): the last thing said about an incident.

What the incident cost, who it took, and one piece of prose describing it -
assembled in `writing`, out of figures measured in `estimate` and disclosures
listed in `assumptions`. The model is asked once, in `conversation`, and for
nothing but words.
"""

from __future__ import annotations

from agent_postmortem.document import (
    ENGAGEMENT_UNAVAILABLE_ASSUMPTION,
    EXCHANGE_RATE_ASSUMPTION_LABEL,
    EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
    ONSET_UNKNOWN_ASSUMPTION,
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    REVENUE_UNAVAILABLE_ASSUMPTION,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
    PostmortemDocument,
)
from agent_postmortem.evidence import IncidentEvidence
from agent_postmortem.sources import Sources
from agent_postmortem.writing import write_postmortem

__all__ = [
    "ENGAGEMENT_UNAVAILABLE_ASSUMPTION",
    "EXCHANGE_RATE_ASSUMPTION_LABEL",
    "EXCLUDED_CURRENCY_ASSUMPTION_LABEL",
    "ONSET_UNKNOWN_ASSUMPTION",
    "PAY_BANDS_UNAVAILABLE_ASSUMPTION",
    "PAY_BAND_ASSUMPTION_LABEL",
    "REVENUE_UNAVAILABLE_ASSUMPTION",
    "UNPRICED_TITLE_ASSUMPTION_LABEL",
    "WORKING_YEAR_ASSUMPTION_LABEL",
    "IncidentEvidence",
    "PostmortemDocument",
    "Sources",
    "write_postmortem",
]
