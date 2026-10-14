"""The Postmortem agent (spec §7.6): the last thing said about an incident.

What the incident cost, who it took, what happened and why - assembled in
`writing`, out of figures measured in `estimate`, sections written from the
record in `sections`, disclosures listed in `assumptions`, and the review in
`reviewing`. The model is asked once, in `conversation`, and for nothing but
words - under the standing brief in `briefing`, which travels in the policy its
client is built with.
"""

from __future__ import annotations

from agent_postmortem.assumptions import (
    ENGAGEMENT_UNAVAILABLE_ASSUMPTION,
    EXCHANGE_RATE_ASSUMPTION_LABEL,
    EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
    NO_RATE_PUBLISHED_REASON,
    NORMAL_VARIATION_ASSUMPTION_LABEL,
    NOT_PAGED_ASSUMPTION,
    ONSET_UNKNOWN_ASSUMPTION,
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    RATES_UNAVAILABLE_REASON,
    REVENUE_UNAVAILABLE_ASSUMPTION,
    SHARED_PAGE_ASSUMPTION_LABEL,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
)
from agent_postmortem.briefing import STANDING_BRIEF, postmortem_policy
from agent_postmortem.evidence import ActionRecord, CandidateRecord, IncidentEvidence
from agent_postmortem.reviewing import (
    ANALYSIS_COMPLETE,
    IMPACT_ASSESSED,
    ITEMS_OWNED_AND_DATED,
    KEY_DATA_COLLECTED,
    REVIEWED_AND_SHARED,
)
from agent_postmortem.sources import (
    EngagedResponder,
    EngagementAnswer,
    NotPaged,
    PayBand,
    RateTable,
    Sources,
)
from agent_postmortem.writing import write_postmortem

__all__ = [
    "ANALYSIS_COMPLETE",
    "IMPACT_ASSESSED",
    "ITEMS_OWNED_AND_DATED",
    "KEY_DATA_COLLECTED",
    "REVIEWED_AND_SHARED",
    "ENGAGEMENT_UNAVAILABLE_ASSUMPTION",
    "EXCHANGE_RATE_ASSUMPTION_LABEL",
    "EXCLUDED_CURRENCY_ASSUMPTION_LABEL",
    "NO_RATE_PUBLISHED_REASON",
    "NORMAL_VARIATION_ASSUMPTION_LABEL",
    "NOT_PAGED_ASSUMPTION",
    "ONSET_UNKNOWN_ASSUMPTION",
    "PAY_BANDS_UNAVAILABLE_ASSUMPTION",
    "PAY_BAND_ASSUMPTION_LABEL",
    "RATES_UNAVAILABLE_REASON",
    "REVENUE_UNAVAILABLE_ASSUMPTION",
    "SHARED_PAGE_ASSUMPTION_LABEL",
    "STANDING_BRIEF",
    "UNPRICED_TITLE_ASSUMPTION_LABEL",
    "WORKING_YEAR_ASSUMPTION_LABEL",
    "ActionRecord",
    "CandidateRecord",
    "EngagedResponder",
    "EngagementAnswer",
    "IncidentEvidence",
    "NotPaged",
    "PayBand",
    "RateTable",
    "Sources",
    "postmortem_policy",
    "write_postmortem"
]
