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
    CACHE,
    DEPLOYMENT_PLATFORM,
    DISCARD_CACHE_ENTRIES,
    FLAG_PROVIDER,
    PIN_AUTOSCALER,
    RESTART_SERVICE,
    REVERT_FEATURE_FLAG,
    ROLL_BACK_DEPLOYMENT,
    SCALE_OUT,
    Action,
    ActionIdentity,
    ActionType,
    AutoscalingRestored,
    CacheEntriesDiscarded,
    CapacityRestored,
    DeploymentRestored,
    DiscardCacheEntries,
    Outcome,
    PinAutoscaler,
    Platform,
    RestartedService,
    RestartService,
    RevertFeatureFlag,
    RollBackDeployment,
    ScaleOut,
    UnreadVerdict,
    Verdict,
    changes_something_persistent,
    leaves_something_to_put_back,
    reports_what_it_changed,
    the_actions_through,
    the_direction_of,
    the_identity_of,
    the_identity_recorded,
    the_platform_of,
    the_service_addressed_by,
    the_subject_of,
)
from argus_core.models.actor import Actor
from argus_core.models.alert import AlarmClaim, Alert
from argus_core.models.alert_rule import AlertRuleStanding
from argus_core.models.attempt import Attempt
from argus_core.models.candidate import WhatWouldBeTried
from argus_core.models.change_event import ChangeEvent, ChangeKind
from argus_core.models.code_search import CodeSearch
from argus_core.models.disproof import Disproof
from argus_core.models.evidence import Evidence
from argus_core.models.failure_mode import FailureMode
from argus_core.models.findings import Findings
from argus_core.models.fix import FixOutcome
from argus_core.models.flag_change import FlagChange
from argus_core.models.hypothesis import Hypothesis
from argus_core.models.incident import Incident
from argus_core.models.incident_status import IncidentStatus
from argus_core.models.metrics import (
    RULE_READING_FIELD,
    MetricBucket,
    RuleReading,
    WorseWhen,
)
from argus_core.models.model_policy import (
    LARGEST_UNSTREAMED_ANSWER,
    Effort,
    ModelPolicy,
)
from argus_core.models.postmortem import Postmortem, PostmortemDocument
from argus_core.models.pull_request import OpenedPullRequest
from argus_core.models.rates import PublishedRates, RatesUnavailable
from argus_core.models.reading import Reading, RetrievalChannel
from argus_core.models.refusal import Refusal
from argus_core.models.rollout import RolloutProgress
from argus_core.models.service_dependency import Ownership, ServiceDependency
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
    PIN_AUTOSCALER_TOOL,
    ROLL_BACK_DEPLOYMENT_TOOL,
    SCALE_OUT_TOOL,
    SET_FEATURE_FLAG_TOOL,
    AutoscalerUndo,
    DeploymentRollbackUndo,
    FlagUndo,
    ReplicaUndo,
    UndoDescriptor,
    parse_undo_descriptor,
)
from argus_core.models.undone import Undone

__all__ = [
    "CACHE",
    "DEPLOYMENT_PLATFORM",
    "DISCARD_CACHE_ENTRIES",
    "FLAG_PROVIDER",
    "Platform",
    "the_actions_through",
    "the_platform_of",
    "RESTART_SERVICE",
    "REVERT_FEATURE_FLAG",
    "ROLL_BACK_DEPLOYMENT",
    "ROLL_BACK_DEPLOYMENT_TOOL",
    "PIN_AUTOSCALER",
    "PIN_AUTOSCALER_TOOL",
    "SCALE_OUT",
    "SCALE_OUT_TOOL",
    "changes_something_persistent",
    "leaves_something_to_put_back",
    "reports_what_it_changed",
    "the_direction_of",
    "the_identity_of",
    "the_identity_recorded",
    "the_service_addressed_by",
    "the_subject_of",
    "SET_FEATURE_FLAG_TOOL",
    "Action",
    "ActionIdentity",
    "ActionType",
    "Actor",
    "AlarmClaim",
    "Alert",
    "Ask",
    "Attempt",
    "FailureMode",
    "ChangeEvent",
    "ChangeKind",
    "CodeSearch",
    "Disproof",
    "Evidence",
    "Exchange",
    "Findings",
    "FixOutcome",
    "FlagChange",
    "AutoscalerUndo",
    "AutoscalingRestored",
    "CacheEntriesDiscarded",
    "CapacityRestored",
    "DeploymentRollbackUndo",
    "DeploymentRestored",
    "DiscardCacheEntries",
    "FlagUndo",
    "Hypothesis",
    "Incident",
    "IncidentStatus",
    "MetricBucket",
    "LARGEST_UNSTREAMED_ANSWER",
    "Effort",
    "ModelPolicy",
    "OpenedPullRequest",
    "Outcome",
    "Ownership",
    "Postmortem",
    "PostmortemDocument",
    "PublishedRates",
    "RatesUnavailable",
    "Reading",
    "Refusal",
    "RetrievalChannel",
    "RuleReading",
    "RULE_READING_FIELD",
    "PinAutoscaler",
    "ReplicaUndo",
    "RestartService",
    "RollBackDeployment",
    "RolloutProgress",
    "AlertRuleStanding",
    "ScaleOut",
    "RestartedService",
    "RevertFeatureFlag",
    "ServiceDependency",
    "TakenAction",
    "ToolCall",
    "ToolDefinition",
    "ToolResult",
    "ToolResults",
    "Transcript",
    "Turn",
    "UndoDescriptor",
    "Undone",
    "WhatWouldBeTried",
    "WorseWhen",
    # Public because `ClaimedAction` names it in an annotation a consumer has
    # to be able to write, not because callers asked for it.
    "UnreadVerdict",
    "Verdict",
    "parse_undo_descriptor"
]
