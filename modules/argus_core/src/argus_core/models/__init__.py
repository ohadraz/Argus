"""The types two modules both name.

A contract lives here rather than inside one of the parties to it: the agent
that produces a `PostmortemDocument`, the repository that persists one and the
page that renders one all have to agree about its shape, and a shape kept inside
the producer is one the others install an agent to read.

Nothing here reaches a database, a model or a network. These are values - what
Argus says about an incident, said once, so that every module saying it is
saying the same thing.
"""

from argus_core.models.action import (
    REVERT_FEATURE_FLAG,
    Action,
    ActionType,
    Outcome,
    RevertFeatureFlag,
    Verdict,
)
from argus_core.models.actor import Actor
from argus_core.models.alert import Alert
from argus_core.models.attempt import Attempt
from argus_core.models.cause import CauseType
from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.models.code_search import CodeSearch
from argus_core.models.evidence import Evidence
from argus_core.models.findings import Findings
from argus_core.models.fix import FixOutcome
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident import Incident
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.metrics import MetricBucket
from argus_core.models.postmortem import Postmortem, PostmortemDocument
from argus_core.models.pull_request import OpenedPullRequest
from argus_core.models.rates import PublishedRates, RatesUnavailable
from argus_core.models.reading import Reading, RetrievalChannel
from argus_core.models.refusal import Refusal
from argus_core.models.taken_action import TakenAction
from argus_core.models.tool_definition import ToolDefinition
from argus_core.models.transcript import (
    Ask,
    Exchange,
    ToolResult,
    ToolResults,
    Transcript,
)
from argus_core.models.turn import ToolCall, Turn
from argus_core.models.undo_descriptor import (
    SET_FEATURE_FLAG_TOOL,
    FlagUndo,
    UndoDescriptor,
    parse_undo_descriptor,
)
from argus_core.models.undone import Undone

__all__ = [
    "REVERT_FEATURE_FLAG",
    "SET_FEATURE_FLAG_TOOL",
    "Action",
    "ActionType",
    "Actor",
    "Alert",
    "Ask",
    "Attempt",
    "CauseType",
    "ChangeEvent",
    "ChangeKind",
    "CodeSearch",
    "Evidence",
    "Exchange",
    "Findings",
    "FixOutcome",
    "FlagChange",
    "FlagUndo",
    "Hypothesis",
    "Incident",
    "IncidentStatus",
    "MetricBucket",
    "OpenedPullRequest",
    "Outcome",
    "Postmortem",
    "PostmortemDocument",
    "PublishedRates",
    "RatesUnavailable",
    "Reading",
    "Refusal",
    "RetrievalChannel",
    "RevertFeatureFlag",
    "TakenAction",
    "ToolCall",
    "ToolDefinition",
    "ToolResult",
    "ToolResults",
    "Transcript",
    "Turn",
    "UndoDescriptor",
    "Undone",
    "Verdict",
    "parse_undo_descriptor"
]
