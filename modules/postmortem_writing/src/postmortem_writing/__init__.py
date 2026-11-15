"""The Postmortem Writer (spec §7.6): the last thing said about an incident.

What the incident cost, who it took, what happened and why - assembled in
`writing`, out of figures measured in `estimate`, sections written from the
record in `sections`, disclosures listed in `assumptions`, and the review in
`reviewing`. The model is asked once, in `conversation`, and for nothing but
words - under the standing brief in `briefing`, which travels in the policy its
client is built with.
"""

from __future__ import annotations

from postmortem_writing.assumptions import (
    ENGAGEMENT_UNAVAILABLE_ASSUMPTION,
    EXCHANGE_RATE_ASSUMPTION_LABEL,
    EXCLUDED_CURRENCY_ASSUMPTION_LABEL,
    NO_RATE_PUBLISHED_REASON,
    NORMAL_VARIATION_ASSUMPTION_LABEL,
    NOT_PAGED_ASSUMPTION,
    NOTHING_READ_ASSUMPTION,
    ONSET_UNKNOWN_ASSUMPTION,
    RATES_UNAVAILABLE_REASON,
    REVENUE_UNAVAILABLE_ASSUMPTION,
    SHARED_PAGE_ASSUMPTION_LABEL,
)
from postmortem_writing.briefing import STANDING_BRIEF, postmortem_policy
from postmortem_writing.conversation import WRITE_UP_TOOLS
from postmortem_writing.evidence import (
    ActionRecord,
    CandidateRecord,
    DeploymentChangesRecord,
    IncidentEvidence,
    RefusalRecord,
    ResolutionRecord,
)
from postmortem_writing.grounding import judge_policy
from postmortem_writing.response_cost_basis import (
    PAY_BAND_ASSUMPTION_LABEL,
    PAY_BANDS_UNAVAILABLE_ASSUMPTION,
    UNPRICED_TITLE_ASSUMPTION_LABEL,
    WORKING_YEAR_ASSUMPTION_LABEL,
)
from postmortem_writing.reviewing import (
    ANALYSIS_COMPLETE,
    IMPACT_ASSESSED,
    ITEMS_OWNED_AND_DATED,
    KEY_DATA_COLLECTED,
    REVIEWED_AND_SHARED,
)
from postmortem_writing.sources import (
    EngagedResponder,
    EngagementAnswer,
    NotPaged,
    PayBand,
    RateTable,
    Sources,
)
from postmortem_writing.summary import said_off_the_page
from postmortem_writing.synopsis_prompting import synopsis_policy
from postmortem_writing.synopsis_writing import write_executive_synopsis
from postmortem_writing.writing import write_postmortem

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
    "NOTHING_READ_ASSUMPTION",
    "ONSET_UNKNOWN_ASSUMPTION",
    "PAY_BANDS_UNAVAILABLE_ASSUMPTION",
    "PAY_BAND_ASSUMPTION_LABEL",
    "RATES_UNAVAILABLE_REASON",
    "REVENUE_UNAVAILABLE_ASSUMPTION",
    "SHARED_PAGE_ASSUMPTION_LABEL",
    "STANDING_BRIEF",
    "UNPRICED_TITLE_ASSUMPTION_LABEL",
    "WORKING_YEAR_ASSUMPTION_LABEL",
    "WRITE_UP_TOOLS",
    "ActionRecord",
    "CandidateRecord",
    "DeploymentChangesRecord",
    "EngagedResponder",
    "EngagementAnswer",
    "IncidentEvidence",
    "NotPaged",
    "PayBand",
    "RateTable",
    "RefusalRecord",
    "ResolutionRecord",
    "Sources",
    "judge_policy",
    "postmortem_policy",
    "said_off_the_page",
    "synopsis_policy",
    "write_executive_synopsis",
    "write_postmortem"
]
