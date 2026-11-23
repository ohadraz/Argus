"""The Postmortem Writer (spec §7.6): the last thing said about an incident.

What the incident cost, who it took, what happened and why - assembled in
`writing`, out of figures measured in `estimate`, sections written from the
record in `sections`, disclosures listed in `assumptions`, and the review in
`reviewing`. The model is asked once, in `conversation`, and for nothing but
words - under the standing brief in `briefing`, which travels in the policy its
client is built with.

The executive synopsis is written from the stored document elsewhere
(`executive_synopsis`), with the figure engine, the judge and the cost by title
exported here for it.
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
from postmortem_writing.breakdown import agreeing_breakdown
from postmortem_writing.briefing import STANDING_BRIEF, postmortem_policy
from postmortem_writing.conversation import WRITE_UP_TOOLS
from postmortem_writing.cost_by_title import cost_by_title
from postmortem_writing.evidence import (
    ActionRecord,
    CandidateRecord,
    DeploymentChangesRecord,
    IncidentEvidence,
    RefusalRecord,
    ResolutionRecord,
)
from postmortem_writing.figure_rules import figure_faults
from postmortem_writing.figures import Figure, names_in, written_in
from postmortem_writing.grounding import (
    Flag,
    Flagging,
    Grounding,
    GroundingFor,
    faults_of,
    judge_policy,
)
from postmortem_writing.pull_requests import the_pull_request_named
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
    Engagement,
    EngagementAnswer,
    NotPaged,
    PayBand,
    PayBands,
    RateTable,
    Sources,
)
from postmortem_writing.summary import said_off_the_page
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
    "Engagement",
    "EngagementAnswer",
    "Figure",
    "Flag",
    "Flagging",
    "Grounding",
    "GroundingFor",
    "IncidentEvidence",
    "NotPaged",
    "PayBand",
    "PayBands",
    "RateTable",
    "RefusalRecord",
    "ResolutionRecord",
    "Sources",
    "agreeing_breakdown",
    "cost_by_title",
    "faults_of",
    "figure_faults",
    "judge_policy",
    "names_in",
    "postmortem_policy",
    "said_off_the_page",
    "the_pull_request_named",
    "write_postmortem",
    "written_in"
]
